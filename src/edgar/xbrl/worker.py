"""Isolated Arelle worker subprocess (ADR 0009).

Run as ``python -m edgar.xbrl.worker``. The worker reads exactly one JSON job
object from the first line of stdin and then speaks a newline-delimited JSON
protocol on stdout::

    worker -> parent  {"type": "fetch", "uri": ...}
    parent -> worker  {"type": "fetch_result", "uri": ..., "path": ..., "sha256": ...}
    parent -> worker  {"type": "fetch_error", "uri": ..., "error": ...}
    worker -> parent  {"type": "result", ...}

Both modes deny ``AF_INET``/``AF_INET6`` sockets. In ``online`` mode a document
that is not already bound is requested from the parent, which is the only
component allowed to perform network I/O. In ``offline`` mode only the supplied
bindings can satisfy a reference; anything else is reported as unresolved.

Only JSON-serializable data crosses the process boundary: ``ModelXbrl`` and
every other Arelle object stays inside this process.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TextIO
from urllib.parse import unquote, urlsplit

from edgar.domain.identifiers import validate_logical_path
from edgar.storage.objects import ObjectStore
from edgar.xbrl.arelle_env import (
    IsolatedArelleEnv,
    arelle_version,
    build_oasis_catalog,
    create_isolated_controller,
    create_isolated_env,
    is_http_uri,
    isolated_process_environment,
    materialize_web_cache,
    materialize_workspace,
    write_web_cache_document,
)
from edgar.xbrl.network_guard import NetworkDeniedError, NetworkGuard, deny_inet_sockets
from edgar.xbrl.uri import UriIdentityError, normalize_uri

WORKER_PROTOCOL_VERSION = "arelle-worker-v1"
WORKER_MODULE = "edgar.xbrl.worker"

IXDS_PLUGIN = "inlineXbrlDocumentSet"
IXDS_ARELLE_DEFAULT_TARGET = "(default)"

WorkerMode = Literal["online", "offline"]
WorkerOperation = Literal["load", "semantic_projection"]

_DIAGNOSTIC_LEVELS = frozenset({"WARNING", "ERROR", "CRITICAL"})


@dataclass(frozen=True)
class WorkerBinding:
    """A canonical document URI bound to verified bytes in the object store."""

    document_uri: str
    artifact_path: str
    content_sha256: str
    replay_aliases: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkerBinding:
        return cls(
            document_uri=data["document_uri"],
            artifact_path=validate_logical_path(data["artifact_path"]),
            content_sha256=str(data["content_sha256"]).lower(),
            replay_aliases=tuple(data.get("replay_aliases") or ()),
        )


@dataclass(frozen=True)
class WorkerJob:
    mode: WorkerMode
    report_input: dict[str, Any]
    object_store_root: Path
    bindings: tuple[WorkerBinding, ...] = ()
    workspace_parent: Path | None = None
    user_agent: str | None = None
    operation: WorkerOperation = "load"

    @property
    def offline(self) -> bool:
        return self.mode == "offline"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkerJob:
        version = data.get("protocol_version", WORKER_PROTOCOL_VERSION)
        if version != WORKER_PROTOCOL_VERSION:
            raise ValueError(f"unsupported worker protocol version: {version!r}")
        mode = data["mode"]
        if mode not in ("online", "offline"):
            raise ValueError(f"unknown worker mode: {mode!r}")
        operation = data.get("operation", "load")
        if operation not in ("load", "semantic_projection"):
            raise ValueError(f"unknown worker operation: {operation!r}")
        if operation == "semantic_projection" and mode != "offline":
            raise ValueError("semantic_projection requires mode=offline")
        bindings = [WorkerBinding.from_dict(b) for b in data.get("uri_bindings") or ()]
        for uri, entry in (data.get("uri_objects") or {}).items():
            bindings.append(
                WorkerBinding(
                    document_uri=uri,
                    artifact_path=validate_logical_path(entry["artifact_path"]),
                    content_sha256=str(entry["content_sha256"]).lower(),
                    replay_aliases=tuple(entry.get("replay_aliases") or ()),
                )
            )
        parent = data.get("workspace_parent")
        return cls(
            mode=mode,
            report_input=dict(data["report_input"]),
            object_store_root=Path(data["object_store_root"]),
            bindings=tuple(bindings),
            workspace_parent=Path(parent) if parent else None,
            user_agent=data.get("user_agent"),
            operation=operation,  # type: ignore[arg-type]
        )


@dataclass
class LoadOutcome:
    load_completed: bool = False
    loaded_source_documents: list[dict[str, Any]] = field(default_factory=list)
    resolved_documents: list[dict[str, Any]] = field(default_factory=list)
    unresolved_documents: list[str] = field(default_factory=list)
    fetched_documents: dict[str, str] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    diagnostic_records: list[dict[str, Any]] = field(default_factory=list)
    semantic_payload: dict[str, Any] | None = None
    semantic_extraction_errors: list[str] = field(default_factory=list)
    engine_version: str = "unknown"


class WorkerChannel:
    """Newline-delimited JSON IPC with the parent process."""

    def __init__(self, reader: TextIO, writer: TextIO) -> None:
        self._reader = reader
        self._writer = writer

    def send(self, message: Mapping[str, Any]) -> None:
        self._writer.write(json.dumps(message, ensure_ascii=False, sort_keys=True))
        self._writer.write("\n")
        self._writer.flush()

    def receive(self) -> dict[str, Any] | None:
        line = self._reader.readline()
        if not line:
            return None
        return json.loads(line)

    def request_fetch(self, uri: str) -> dict[str, Any]:
        self.send({"type": "fetch", "uri": uri})
        message = self.receive()
        if message is None:
            return {"type": "fetch_error", "uri": uri, "error": "parent closed IPC channel"}
        if message.get("type") not in ("fetch_result", "fetch_error"):
            return {
                "type": "fetch_error",
                "uri": uri,
                "error": f"unexpected parent message: {message.get('type')!r}",
            }
        if message.get("uri") != uri:
            return {
                "type": "fetch_error",
                "uri": uri,
                "error": f"parent answered for a different URI: {message.get('uri')!r}",
            }
        return message


class DocumentResolver:
    """Closed-world URI resolution for one Arelle load.

    Every satisfied request is recorded in :attr:`resolved`. That set is wider
    than the DTS closure: Arelle also resolves XML-schema validation resources
    (for example the Inline XBRL 1.1 and XHTML module schemas) that never become
    ``ModelDocument`` entries but are still required for a faithful replay.
    """

    def __init__(
        self,
        *,
        web_cache: Any,
        guard: NetworkGuard,
        channel: WorkerChannel | None,
        offline: bool,
        known: Mapping[str, Path],
        known_digests: Mapping[str, str],
        allowed_roots: Sequence[Path],
        diagnostics: list[str],
    ) -> None:
        self._web_cache = web_cache
        self._guard = guard
        self._channel = channel
        self._offline = offline
        self._known: dict[str, Path] = dict(known)
        self._digests: dict[str, str] = dict(known_digests)
        self._allowed_roots = tuple(root.resolve() for root in allowed_roots)
        self._diagnostics = diagnostics
        self.unresolved: list[str] = []
        self.fetched: dict[str, str] = {}
        self.resolved: dict[str, str] = {}

    def _note_unresolved(self, uri: str, reason: str) -> None:
        if uri not in self.unresolved:
            self.unresolved.append(uri)
        self._diagnostics.append(f"unresolved document {uri}: {reason}")

    def _record_resolved(self, uri: str, path: Path) -> None:
        if uri in self.resolved:
            return
        digest = self._digests.get(uri)
        if digest is None:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                self._diagnostics.append(f"resolved document unreadable {uri}: {exc}")
                return
            self._digests[uri] = digest
        self.resolved[uri] = digest

    def resolve_remote(self, uri: str) -> Path | None:
        try:
            canonical = normalize_uri(uri)
        except UriIdentityError as exc:
            self._diagnostics.append(f"non-canonical document URI rejected: {exc}")
            return None
        known = self._known.get(canonical)
        if known is not None:
            self._record_resolved(canonical, known)
            return known
        if self._offline:
            host = urlsplit(canonical).hostname or canonical
            self._guard.record("offline_uri_resolution", host, None)
            self._note_unresolved(canonical, "no binding available for offline replay")
            return None
        if self._channel is None:
            self._note_unresolved(canonical, "no IPC channel for online resolution")
            return None
        response = self._channel.request_fetch(canonical)
        if response.get("type") == "fetch_error":
            self._note_unresolved(canonical, str(response.get("error", "fetch failed")))
            return None
        source = Path(str(response["path"]))
        expected = str(response["sha256"]).lower()
        try:
            content = source.read_bytes()
        except OSError as exc:
            self._note_unresolved(canonical, f"parent-supplied bytes unreadable: {exc}")
            return None
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            self._note_unresolved(
                canonical, f"parent-supplied bytes hash {actual}, expected {expected}"
            )
            return None
        target = write_web_cache_document(self._web_cache, canonical, content)
        self._known[canonical] = target
        self._digests[canonical] = actual
        self.fetched[canonical] = actual
        self._record_resolved(canonical, target)
        return target

    def resolve_local(self, reference: str) -> str | None:
        """Allow only local paths inside the worker's closed world."""
        text = reference
        if text.startswith("file://"):
            text = unquote(urlsplit(text).path)
        elif text.startswith("file:"):
            text = unquote(text[5:])
        try:
            candidate = Path(text).resolve()
        except (OSError, ValueError) as exc:
            self._note_unresolved(reference, f"local reference rejected ({exc})")
            return None
        if not any(candidate.is_relative_to(root) for root in self._allowed_roots):
            self._note_unresolved(reference, "local reference outside workspace denied")
            return None
        return str(candidate)


def install_web_cache_guard(
    cntlr: Any,
    resolver: DocumentResolver,
    guard: NetworkGuard,
) -> None:
    """Route all Arelle document resolution through :class:`DocumentResolver`."""
    from arelle.UrlUtil import IXDS_DOC_SEPARATOR, IXDS_SURROGATE

    surrogate_name = IXDS_SURROGATE.partition(IXDS_DOC_SEPARATOR)[0]
    web_cache = cntlr.webCache
    original_getfilename = web_cache.getfilename

    def is_ixds_surrogate(text: str) -> bool:
        # Arelle addresses the document set both as "<dir>/_IXDS#?#<member>..." and
        # as the bare "<dir>/_IXDS" docset URL. Neither has bytes of its own.
        return IXDS_DOC_SEPARATOR in text or text.rpartition("/")[2] == surrogate_name

    def guarded_getfilename(
        url: Any = None,
        base: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> str | None:
        if url is None:
            return None
        text = str(url)
        if is_ixds_surrogate(text):
            return original_getfilename(url, base, *args, **kwargs)
        normalized = web_cache.normalizeUrl(text, base)
        if is_http_uri(normalized):
            resolved = resolver.resolve_remote(normalized)
            return str(resolved) if resolved is not None else None
        return resolver.resolve_local(normalized)

    def denied_retrieve(url: Any, *args: Any, **kwargs: Any) -> Any:
        host = urlsplit(str(url)).hostname or str(url)
        raise NetworkDeniedError(guard.record("webcache.retrieve", host, None))

    web_cache.getfilename = guarded_getfilename
    web_cache.retrieve = denied_retrieve


def _entrypoint_for(report_input: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Build the Arelle entry URI (and IXDS entrypoint object) from report input.

    IXDS members are passed as canonical HTTP(S) URIs so that every
    ``ModelDocument.uri`` and reference base stays canonical; the bytes are
    found through the pre-seeded web cache.
    """
    from arelle.UrlUtil import IXDS_DOC_SEPARATOR, IXDS_SURROGATE

    kind = report_input["kind"]
    uris = [str(u) for u in report_input["document_uris"]]
    if not uris:
        raise ValueError("report input has no document URIs")
    if kind == "instance":
        if len(uris) != 1:
            raise ValueError("instance report input requires exactly one document URI")
        return uris[0], None
    if kind == "ixds":
        target = report_input.get("target", "default")
        if target != "default":
            raise ValueError(f"unsupported IXDS target: {target!r}")
        base_dir = uris[0].rpartition("/")[0]
        surrogate = f"{base_dir}/{IXDS_SURROGATE}{IXDS_DOC_SEPARATOR.join(uris)}"
        entrypoint = {
            "ixds": [{"file": uri} for uri in uris],
            "ixdsTarget": IXDS_ARELLE_DEFAULT_TARGET,
        }
        return surrogate, entrypoint
    raise ValueError(f"unknown report input kind: {kind!r}")


def _log_diagnostics(cntlr: Any) -> list[str]:
    """Deterministic (timestamp-free) warning/error lines from the Arelle log."""
    handler = getattr(cntlr, "logHandler", None)
    buffer = getattr(handler, "logRecordBuffer", None)
    if not isinstance(buffer, list):
        return []
    lines: list[str] = []
    for record in buffer:
        level = str(getattr(record, "levelname", "INFO")).upper()
        if level not in _DIAGNOSTIC_LEVELS:
            continue
        code = str(getattr(record, "messageCode", "") or "")
        try:
            message = record.getMessage()
        except Exception as exc:  # noqa: BLE001 - never fail the load on logging
            message = f"<unrenderable log record: {exc}>"
        lines.append(f"[{level}] [{code}] {message}")
    return lines


def _collect_documents(
    model_xbrl: Any,
    diagnostics: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract source-backed loaded documents as plain dicts."""
    from arelle.ModelDocument import Type as ModelDocumentType

    documents: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    for raw_uri, document in (getattr(model_xbrl, "urlDocs", {}) or {}).items():
        if getattr(document, "type", None) == ModelDocumentType.INLINEXBRLDOCUMENTSET:
            # Engine-created document-set surrogate; not source-backed.
            continue
        text = str(raw_uri).split("#", 1)[0]
        if not is_http_uri(text):
            diagnostics.append(f"loaded document without canonical URI ignored: {text}")
            continue
        try:
            canonical = normalize_uri(text)
        except UriIdentityError as exc:
            diagnostics.append(f"loaded document URI is not canonical: {exc}")
            continue
        filepath = getattr(document, "filepath", None)
        if not filepath or not Path(filepath).is_file():
            if canonical not in unresolved:
                unresolved.append(canonical)
            continue
        local = Path(filepath)
        content = local.read_bytes()
        record = {
            "document_uri": canonical,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "local_path": str(local.resolve()),
        }
        existing = documents.get(canonical)
        if existing is not None:
            if existing["content_sha256"] != record["content_sha256"]:
                diagnostics.append(
                    f"conflicting bytes for document URI {canonical}: "
                    f"{existing['content_sha256']} vs {record['content_sha256']}"
                )
            continue
        documents[canonical] = record

    for raw_uri in getattr(model_xbrl, "urlUnloadableDocs", {}) or {}:
        text = str(raw_uri).split("#", 1)[0]
        if not is_http_uri(text):
            continue
        try:
            canonical = normalize_uri(text)
        except UriIdentityError:
            continue
        if canonical not in documents and canonical not in unresolved:
            unresolved.append(canonical)

    ordered = [documents[uri] for uri in sorted(documents)]
    return ordered, sorted(unresolved)


@dataclass(frozen=True)
class BoundInputs:
    documents: dict[str, tuple[str, bytes]]
    aliases: dict[str, str]
    digests: dict[str, str]


def _bound_documents(job: WorkerJob) -> BoundInputs:
    """Read bound bytes from the object store; verified against their digests."""
    store = ObjectStore(job.object_store_root)
    documents: dict[str, tuple[str, bytes]] = {}
    aliases: dict[str, str] = {}
    digests: dict[str, str] = {}
    for binding in job.bindings:
        canonical = normalize_uri(binding.document_uri)
        documents[canonical] = (binding.artifact_path, store.open_bytes(binding.content_sha256))
        digests[canonical] = binding.content_sha256
        for alias in binding.replay_aliases:
            alias_uri = normalize_uri(alias)
            aliases[alias_uri] = canonical
            digests[alias_uri] = binding.content_sha256
    return BoundInputs(documents=documents, aliases=aliases, digests=digests)


def _run_load(
    job: WorkerJob,
    env: IsolatedArelleEnv,
    uri_to_path: Mapping[str, Path],
    bound: BoundInputs,
    guard: NetworkGuard,
    channel: WorkerChannel | None,
    diagnostics: list[str],
) -> LoadOutcome:
    plugins = (IXDS_PLUGIN,) if job.report_input.get("kind") == "ixds" else ()
    # Arelle stays in offline mode in both worker modes: the parent process is
    # the only component permitted to perform network I/O.
    cntlr = create_isolated_controller(
        cache_dir=env.cache_dir,
        work_offline=True,
        user_agent=job.user_agent,
        plugins=plugins,
    )
    outcome = LoadOutcome(engine_version=arelle_version())
    model_xbrl: Any = None
    try:
        cached = materialize_web_cache(cntlr.webCache, uri_to_path)
        known = dict(cached)
        for alias, primary in bound.aliases.items():
            target = cached.get(primary)
            if target is not None:
                known[alias] = target
        resolver = DocumentResolver(
            web_cache=cntlr.webCache,
            guard=guard,
            channel=channel,
            offline=job.offline,
            known=known,
            known_digests=bound.digests,
            # Filing content may only reach materialized bytes. The object store
            # is read directly for bound and parent-supplied documents, never
            # through a reference embedded in a filing.
            allowed_roots=(env.workspace, env.cache_dir),
            diagnostics=diagnostics,
        )
        install_web_cache_guard(cntlr, resolver, guard)

        entry_uri, entrypoint = _entrypoint_for(job.report_input)
        if entrypoint is None:
            model_xbrl = cntlr.modelManager.load(entry_uri, "loading")
        else:
            model_xbrl = cntlr.modelManager.load(entry_uri, "loading", entrypoint=entrypoint)

        if model_xbrl is None or getattr(model_xbrl, "modelDocument", None) is None:
            diagnostics.append("Arelle returned no entry model document")
        else:
            outcome.load_completed = True
        if model_xbrl is not None:
            documents, unresolved = _collect_documents(model_xbrl, diagnostics)
            outcome.loaded_source_documents = documents
            outcome.unresolved_documents = sorted(set(unresolved) | set(resolver.unresolved))
        else:
            outcome.unresolved_documents = sorted(set(resolver.unresolved))
        in_model = {d["document_uri"] for d in outcome.loaded_source_documents}
        outcome.resolved_documents = [
            {
                "document_uri": uri,
                "content_sha256": resolver.resolved[uri],
                "in_model": uri in in_model,
            }
            for uri in sorted(resolver.resolved)
        ]
        outcome.fetched_documents = dict(resolver.fetched)
        outcome.diagnostics.extend(_log_diagnostics(cntlr))
        if (
            job.operation == "semantic_projection"
            and outcome.load_completed
            and model_xbrl is not None
            and getattr(model_xbrl, "modelDocument", None) is not None
        ):
            try:
                from edgar.xbrl.extract import SemanticExtractionError, extract_semantic_projection

                data = extract_semantic_projection(
                    model_xbrl,
                    bound_inputs=bound,
                    primary_uris=frozenset(bound.documents),
                    engine_version=outcome.engine_version,
                )
                outcome.semantic_payload = data.to_dict()
                outcome.diagnostic_records = [d.to_dict() for d in data.diagnostics]
            except Exception as exc:  # noqa: BLE001 - structured failure for parent
                from edgar.xbrl.extract import SemanticExtractionError

                if isinstance(exc, SemanticExtractionError):
                    outcome.semantic_extraction_errors.append(str(exc))
                    outcome.semantic_payload = {
                        "extraction_failed": True,
                        "issues": [issue.to_dict() for issue in exc.issues],
                    }
                else:
                    outcome.semantic_extraction_errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        if model_xbrl is not None:
            try:
                model_xbrl.close()
            except Exception as exc:  # noqa: BLE001 - close must not mask results
                diagnostics.append(f"model close failed: {exc}")
        try:
            cntlr.close()
        except Exception as exc:  # noqa: BLE001 - close must not mask results
            diagnostics.append(f"controller close failed: {exc}")
    return outcome


def run_job(job: WorkerJob, channel: WorkerChannel | None = None) -> dict[str, Any]:
    """Execute one worker job and return the JSON-serializable result payload."""
    guard = NetworkGuard()
    diagnostics: list[str] = []
    errors: list[str] = []
    outcome = LoadOutcome()
    env = create_isolated_env(parent=job.workspace_parent)
    try:
        bound = _bound_documents(job)
        uri_to_path = materialize_workspace(bound.documents, env.workspace)
        build_oasis_catalog(uri_to_path, env.catalog_path)
        with (
            isolated_process_environment(env, catalog_path=env.catalog_path),
            deny_inet_sockets(guard),
        ):
            outcome = _run_load(job, env, uri_to_path, bound, guard, channel, diagnostics)
    except NetworkDeniedError as exc:
        errors.append(str(exc))
    except Exception as exc:  # noqa: BLE001 - the parent needs a structured failure
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        env.cleanup()

    result: dict[str, Any] = {
        "type": "result",
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "mode": job.mode,
        "operation": job.operation,
        "engine_name": "arelle",
        "engine_version": outcome.engine_version,
        "load_completed": outcome.load_completed and not errors,
        "network_attempts": guard.to_dicts(),
        "loaded_source_documents": outcome.loaded_source_documents,
        "resolved_documents": outcome.resolved_documents,
        "unresolved_documents": outcome.unresolved_documents,
        "fetched_documents": outcome.fetched_documents,
        "diagnostics": [*diagnostics, *outcome.diagnostics],
        "diagnostic_records": outcome.diagnostic_records,
        "errors": errors,
    }
    if job.operation == "semantic_projection":
        result["semantic_payload"] = outcome.semantic_payload
        result["semantic_extraction_errors"] = outcome.semantic_extraction_errors
    return result


def _reserve_ipc_stdout() -> TextIO:
    """Keep fd 1 for IPC only; incidental stdout writes go to stderr."""
    ipc_fd = os.dup(1)
    os.dup2(2, 1)
    return os.fdopen(ipc_fd, "w", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    writer = _reserve_ipc_stdout()
    channel = WorkerChannel(sys.stdin, writer)
    try:
        first_line = sys.stdin.readline()
        if not first_line.strip():
            raise ValueError("no worker job received on stdin")
        job = WorkerJob.from_dict(json.loads(first_line))
    except Exception as exc:  # noqa: BLE001 - report malformed jobs structurally
        channel.send(
            {
                "type": "result",
                "protocol_version": WORKER_PROTOCOL_VERSION,
                "mode": None,
                "load_completed": False,
                "network_attempts": [],
                "loaded_source_documents": [],
                "resolved_documents": [],
                "unresolved_documents": [],
                "fetched_documents": {},
                "diagnostics": [],
                "errors": [f"{type(exc).__name__}: {exc}"],
            }
        )
        return 1
    channel.send(run_job(job, channel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
