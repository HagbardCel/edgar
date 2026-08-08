"""Parent-side online DTS closure discovery (ADR 0009).

The parent process owns the only network client. It launches the isolated
Arelle worker, answers the worker's document requests from the accession map or
by fetching into the content-addressed store, and turns the resulting closure
into the ``UriBinding`` set that makes the filing offline-replayable.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import IO, Any
from urllib.parse import urlsplit

from edgar.domain.bundle import UriBinding, XbrlReportInput
from edgar.domain.identifiers import sanitize_basename
from edgar.sec.client import ControlledFetcher
from edgar.sec.limits import (
    MaxBundleBytesExceeded,
    MaxExternalDependencyBytesExceeded,
    MaxRedirectsExceeded,
    ResourceLimitExceeded,
)
from edgar.sec.ssrf import DestinationForbidden
from edgar.storage.objects import ObjectStore, SizeLimitExceeded
from edgar.xbrl.arelle_env import PROXY_ENV_VARS, XML_CATALOG_ENV_VAR
from edgar.xbrl.uri import normalize_uri, sha256_of_uri
from edgar.xbrl.worker import WORKER_MODULE, WORKER_PROTOCOL_VERSION

DEFAULT_WORKER_TIMEOUT_SECONDS = 900.0

FetchHandler = Callable[[str], dict[str, Any]]


class WorkerProtocolError(RuntimeError):
    """Raised when the worker subprocess violates the IPC contract."""


@dataclass(frozen=True)
class LoadedDocument:
    document_uri: str
    content_sha256: str
    local_path: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LoadedDocument:
        return cls(
            document_uri=data["document_uri"],
            content_sha256=str(data["content_sha256"]).lower(),
            local_path=data.get("local_path"),
        )


@dataclass(frozen=True)
class ResolvedDocument:
    """A document the worker resolved for Arelle.

    ``in_model`` distinguishes DTS documents from XML-schema validation
    resources that Arelle resolves but never adds to the model. Both are needed
    for a faithful offline replay; only the former belong to the DTS closure.
    """

    document_uri: str
    content_sha256: str
    in_model: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ResolvedDocument:
        return cls(
            document_uri=data["document_uri"],
            content_sha256=str(data["content_sha256"]).lower(),
            in_model=bool(data.get("in_model", False)),
        )


@dataclass(frozen=True)
class ExternalDocument:
    """A DTS document fetched by the parent during online closure."""

    document_uri: str
    artifact_path: str
    content_sha256: str
    byte_size: int


@dataclass(frozen=True)
class ClosureDiscovery:
    report_input: XbrlReportInput
    load_completed: bool
    loaded_documents: tuple[LoadedDocument, ...]
    resolved_documents: tuple[ResolvedDocument, ...]
    uri_bindings: tuple[UriBinding, ...]
    external_documents: tuple[ExternalDocument, ...]
    unresolved_documents: tuple[str, ...]
    network_attempts: tuple[dict[str, Any], ...]
    diagnostics: tuple[str, ...]
    errors: tuple[str, ...]
    fatal_safeguard: BaseException | None = None


@dataclass(frozen=True)
class WorkerRun:
    result: dict[str, Any]
    returncode: int
    stderr: str


def external_artifact_path(document_uri: str) -> str:
    """Logical path for a non-accession DTS document (ADR 0009 layout)."""
    basename = sanitize_basename(PurePosixPath(urlsplit(document_uri).path).name or "dependency")
    return f"external/{sha256_of_uri(document_uri)}/{basename}"


def worker_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for the worker with proxies and ambient catalogs removed."""
    env = dict(base if base is not None else os.environ)
    for key in PROXY_ENV_VARS:
        env.pop(key, None)
    env.pop(XML_CATALOG_ENV_VAR, None)
    return env


def _drain(stream: IO[str], sink: list[str]) -> None:
    for line in stream:
        sink.append(line)
    stream.close()


def _pump(stream: IO[str], sink: queue.Queue[str | None]) -> None:
    for line in stream:
        sink.put(line)
    sink.put(None)
    stream.close()


def run_worker_process(
    job: Mapping[str, Any],
    *,
    fetch_handler: FetchHandler,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> WorkerRun:
    """Run one worker job, servicing its fetch requests until it returns."""
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [python_executable, "-m", WORKER_MODULE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=worker_environment(),
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    lines: queue.Queue[str | None] = queue.Queue()
    stderr_lines: list[str] = []
    stdout_thread = threading.Thread(target=_pump, args=(process.stdout, lines), daemon=True)
    stderr_thread = threading.Thread(
        target=_drain, args=(process.stderr, stderr_lines), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()

    deadline = time.monotonic() + timeout_seconds
    result: dict[str, Any] | None = None
    try:
        process.stdin.write(json.dumps({**job, "protocol_version": WORKER_PROTOCOL_VERSION}))
        process.stdin.write("\n")
        process.stdin.flush()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WorkerProtocolError("worker exceeded the configured timeout")
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise WorkerProtocolError("worker exceeded the configured timeout") from exc
            if line is None:
                break
            if not line.strip():
                continue
            message = json.loads(line)
            kind = message.get("type")
            if kind == "fetch":
                response = fetch_handler(str(message["uri"]))
                process.stdin.write(json.dumps(response, ensure_ascii=False))
                process.stdin.write("\n")
                process.stdin.flush()
            elif kind == "result":
                result = message
                break
            else:
                raise WorkerProtocolError(f"unexpected worker message type: {kind!r}")
    finally:
        with contextlib.suppress(OSError):
            process.stdin.close()
        try:
            process.wait(timeout=max(1.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10.0)
        stdout_thread.join(timeout=5.0)
        stderr_thread.join(timeout=5.0)

    if result is None:
        raise WorkerProtocolError(
            f"worker exited without a result (returncode={process.returncode}): "
            f"{''.join(stderr_lines)[-2000:]}"
        )
    return WorkerRun(
        result=result,
        returncode=process.returncode,
        stderr="".join(stderr_lines),
    )


def run_online_closure(
    report_input: XbrlReportInput,
    accession_uri_map: Mapping[str, tuple[str, str]],
    store: ObjectStore,
    fetcher: ControlledFetcher,
    *,
    max_file_bytes: int,
    max_new_payload_bytes: int,
    user_agent: str | None = None,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> ClosureDiscovery:
    """Discover the DTS closure online through the isolated worker.

    ``accession_uri_map`` maps a canonical document URI to
    ``(content_sha256, logical_path)`` for bytes already captured from the
    accession. Those URIs are answered from the store and never re-fetched.

    ``max_new_payload_bytes`` is the remaining aggregate bundle allowance for
    newly captured external logical members (closure-local counter only).
    """
    accession = {
        normalize_uri(uri): (digest.lower(), logical_path)
        for uri, (digest, logical_path) in accession_uri_map.items()
    }
    job = {
        "mode": "online",
        "report_input": report_input.to_dict(),
        "object_store_root": str(store.data_root),
        "user_agent": user_agent,
        "uri_bindings": [
            {
                "document_uri": uri,
                "artifact_path": logical_path,
                "content_sha256": digest,
                "replay_aliases": [],
            }
            for uri, (digest, logical_path) in sorted(accession.items())
        ],
    }

    external: dict[str, ExternalDocument] = {}
    fetch_diagnostics: list[str] = []
    external_remaining = max_new_payload_bytes
    fatal_safeguard: BaseException | None = None
    fetch_blocked = False

    def handle_fetch(uri: str) -> dict[str, Any]:
        nonlocal external_remaining, fatal_safeguard, fetch_blocked
        if fetch_blocked:
            return {
                "type": "fetch_error",
                "uri": uri,
                "error": "fetch blocked after prior fatal safeguard",
            }
        try:
            canonical = normalize_uri(uri)
        except ValueError as exc:
            fetch_diagnostics.append(f"worker requested a non-canonical URI {uri!r}: {exc}")
            return {"type": "fetch_error", "uri": uri, "error": str(exc)}
        known = accession.get(canonical)
        if known is not None:
            digest, _logical_path = known
            return {
                "type": "fetch_result",
                "uri": uri,
                "path": str(store.path_for(digest)),
                "sha256": digest,
            }
        already = external.get(canonical)
        if already is not None:
            return {
                "type": "fetch_result",
                "uri": uri,
                "path": str(store.path_for(already.content_sha256)),
                "sha256": already.content_sha256,
            }
        stream_limit = min(max_file_bytes, external_remaining)
        if stream_limit <= 0:
            fatal_safeguard = MaxBundleBytesExceeded(
                f"no remaining payload budget for external {canonical}"
            )
            fetch_blocked = True
            fetch_diagnostics.append(str(fatal_safeguard))
            return {"type": "fetch_error", "uri": uri, "error": str(fatal_safeguard)}
        try:
            _fetched, obj = fetcher.fetch_to_store(canonical, store, max_bytes=stream_limit)
        except SizeLimitExceeded as exc:
            if stream_limit < max_file_bytes:
                fatal_safeguard = MaxBundleBytesExceeded(str(exc))
            else:
                fatal_safeguard = MaxExternalDependencyBytesExceeded(str(exc))
            fetch_blocked = True
            fetch_diagnostics.append(f"{type(fatal_safeguard).__name__}: {fatal_safeguard}")
            return {
                "type": "fetch_error",
                "uri": uri,
                "error": f"{type(fatal_safeguard).__name__}: {fatal_safeguard}",
            }
        except MaxRedirectsExceeded as exc:
            fatal_safeguard = exc
            fetch_blocked = True
            fetch_diagnostics.append(f"{type(exc).__name__}: {exc}")
            return {"type": "fetch_error", "uri": uri, "error": f"{type(exc).__name__}: {exc}"}
        except DestinationForbidden as exc:
            fatal_safeguard = exc
            fetch_blocked = True
            fetch_diagnostics.append(f"{type(exc).__name__}: {exc}")
            return {"type": "fetch_error", "uri": uri, "error": f"{type(exc).__name__}: {exc}"}
        except ResourceLimitExceeded as exc:
            fatal_safeguard = exc
            fetch_blocked = True
            fetch_diagnostics.append(f"{type(exc).__name__}: {exc}")
            return {"type": "fetch_error", "uri": uri, "error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:  # noqa: BLE001 - surfaced to the worker and diagnostics
            fetch_diagnostics.append(f"fetch failed for {canonical}: {type(exc).__name__}: {exc}")
            return {"type": "fetch_error", "uri": uri, "error": f"{type(exc).__name__}: {exc}"}
        if obj.byte_size > external_remaining:
            fatal_safeguard = MaxBundleBytesExceeded(
                f"external {canonical} size {obj.byte_size} exceeds remaining {external_remaining}"
            )
            fetch_blocked = True
            return {"type": "fetch_error", "uri": uri, "error": str(fatal_safeguard)}
        external_remaining -= obj.byte_size
        external[canonical] = ExternalDocument(
            document_uri=canonical,
            artifact_path=external_artifact_path(canonical),
            content_sha256=obj.sha256,
            byte_size=obj.byte_size,
        )
        return {
            "type": "fetch_result",
            "uri": uri,
            "path": str(obj.storage_path),
            "sha256": obj.sha256,
        }

    run = run_worker_process(
        job,
        fetch_handler=handle_fetch,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    )
    result = run.result

    loaded = tuple(LoadedDocument.from_dict(d) for d in result.get("loaded_source_documents", []))
    resolved = tuple(ResolvedDocument.from_dict(d) for d in result.get("resolved_documents", []))
    diagnostics = [*fetch_diagnostics, *result.get("diagnostics", [])]

    binding_inputs: dict[str, str] = {d.document_uri: d.content_sha256 for d in resolved}
    for document in loaded:
        binding_inputs.setdefault(document.document_uri, document.content_sha256)

    bindings: list[UriBinding] = []
    for document_uri in sorted(binding_inputs):
        content_sha256 = binding_inputs[document_uri]
        known = accession.get(document_uri)
        if known is not None:
            digest, logical_path = known
            if digest != content_sha256:
                diagnostics.append(
                    f"accession bytes differ from loaded bytes for {document_uri}: "
                    f"{digest} vs {content_sha256}"
                )
            artifact_path = logical_path
        else:
            captured = external.get(document_uri)
            if captured is None:
                diagnostics.append(
                    f"loaded document was never captured by the parent fetcher: {document_uri}"
                )
                artifact_path = external_artifact_path(document_uri)
            else:
                artifact_path = captured.artifact_path
        bindings.append(
            UriBinding(
                document_uri=document_uri,
                artifact_path=artifact_path,
                content_sha256=content_sha256,
            )
        )

    return ClosureDiscovery(
        report_input=report_input,
        load_completed=bool(result.get("load_completed")),
        loaded_documents=loaded,
        resolved_documents=resolved,
        uri_bindings=tuple(bindings),
        external_documents=tuple(external[uri] for uri in sorted(external)),
        unresolved_documents=tuple(result.get("unresolved_documents", [])),
        network_attempts=tuple(result.get("network_attempts", [])),
        diagnostics=tuple(diagnostics),
        errors=tuple(result.get("errors", [])),
        fatal_safeguard=fatal_safeguard,
    )
