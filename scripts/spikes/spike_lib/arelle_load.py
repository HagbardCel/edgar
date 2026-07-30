"""Arelle load, DTS closure capture, relationship extraction, and cache helpers.

All persisted identities use canonical URIs (uri-identity-v1) and Clark-notation
QNames. Loaded documents/edges are partitioned exhaustively into a source-backed
partition (bytes captured from payload artifacts) and a synthetic partition
(engine-created structures, inventoried and hashed separately). Arelle objects
never escape this adapter boundary.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from spike_lib import CATALOG_GENERATOR_VERSION, RELATIONSHIP_SERIALIZATION_VERSION
from spike_lib.arelle_errors import ErrorCapture, summarize_errors
from spike_lib.hashing import canonical_json_bytes, sha256_hex
from spike_lib.quality import QualityIssue
from spike_lib.relationships import collect_relationships
from spike_lib.sec import sanitize_basename
from spike_lib.synthetic import (
    inline_document_set_identity,
    synthetic_document_set_hash,
    synthetic_edge_set_hash,
    unknown_synthetic_identity,
)
from spike_lib.uri_identity import (
    UriIdentityError,
    is_http_uri,
    normalize_uri,
    resolve_document_uri,
    strip_fragment,
)

__all__ = [
    "is_http_uri",
    "strip_fragment",
    "classify_document_type",
    "map_discovery_type",
    "map_discovery_types",
    "materialize_working_tree",
    "materialize_arelle_web_cache",
    "build_oasis_catalog",
    "build_accession_uri_map",
    "external_logical_path",
    "load_and_inspect",
    "occurrence_collection_hash",
    "ClosureDocument",
    "ClosureEdge",
    "InspectionSnapshot",
    "ArelleLoadResult",
]


def classify_document_type(model_document: Any) -> str:
    type_obj = getattr(model_document, "type", None)
    type_name = getattr(type_obj, "name", None)
    if type_name is None and hasattr(model_document, "gettype"):
        try:
            type_name = model_document.gettype()
        except Exception:  # noqa: BLE001
            type_name = None
    text = str(type_name or type_obj or "")
    upper = text.upper()
    if "INLINEDOCUMENTSET" in upper:
        return "inline_document_set"
    if "INLINE" in upper:
        return "inline_instance"
    if "INSTANCE" in upper:
        return "instance"
    if "SCHEMA" in upper:
        return "schema"
    if "LINKBASE" in upper:
        return "linkbase"
    return "unknown"


def _normalize_ref_token(token: str) -> str:
    return str(token).lower().replace("-", "").replace("_", "")


# Exact normalized tokens → discovery type. arcroleref checked before roleref.
_DISCOVERY_EXACT: dict[str, str] = {
    "schemaref": "schema_ref",
    "linkbaseref": "linkbase_ref",
    "import": "schema_import",
    "include": "schema_include",
    "arcroleref": "arcrole_ref",
    "roleref": "role_ref",
    "href": "locator_reference",
}


def map_discovery_type(reference_type: str | None) -> str:
    """Map a single Arelle referenceTypes token to a discovery_type."""
    if not reference_type:
        return "other"
    key = _normalize_ref_token(reference_type)
    if key in _DISCOVERY_EXACT:
        return _DISCOVERY_EXACT[key]
    return "other"


def map_discovery_types(reference_types: Any) -> list[str]:
    """Enumerate all reference types; emit one discovery type per concrete token."""
    if reference_types is None:
        return ["other"]
    if isinstance(reference_types, (set, list, tuple)):
        tokens = list(reference_types)
    else:
        tokens = [reference_types]

    def sort_key(t: Any) -> tuple[int, str]:
        n = _normalize_ref_token(str(t))
        if n == "arcroleref":
            return (0, n)
        if n == "roleref":
            return (1, n)
        return (2, n)

    out: list[str] = []
    seen: set[str] = set()
    for token in sorted(tokens, key=sort_key):
        mapped = map_discovery_type(str(token))
        if mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return out or ["other"]


@dataclass
class ClosureDocument:
    canonical_uri: str
    content_sha256: str
    document_type: str
    local_path: str | None
    byte_size: int


@dataclass
class ClosureEdge:
    source_uri: str
    discovery_type: str
    target_uri: str
    normalized_href: str


@dataclass
class InspectionSnapshot:
    documents: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    concept_count: int
    context_count: int
    unit_count: int
    fact_count: int
    relationship_counts: dict[str, int]
    resource_relationship_counts: dict[str, int]
    concept_records: list[dict[str, Any]]
    resource_records: list[dict[str, Any]]
    concept_relationship_occurrence_hash: str
    resource_relationship_occurrence_hash: str
    unsupported_inventory: dict[str, Any]
    extraction: dict[str, Any]
    synthetic_documents: list[dict[str, Any]]
    synthetic_document_set_hash: str
    synthetic_document_count: int
    synthetic_edges: list[dict[str, Any]]
    synthetic_edge_set_hash: str
    synthetic_edge_count: int
    entry_points: list[str]
    unresolved_uris: list[str]
    fact_locator_stats: dict[str, Any]
    error_summary: dict[str, Any]
    engine_name: str
    engine_version: str
    engine_config: dict[str, Any]
    log_sha256: str | None
    log_error_count: int
    log_warning_count: int


@dataclass
class ArelleLoadResult:
    snapshot: InspectionSnapshot
    closure_documents: list[ClosureDocument] = field(default_factory=list)
    closure_edges: list[ClosureEdge] = field(default_factory=list)
    reference_uris: list[str] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    raw_log: str = ""
    network_attempts: list[dict[str, Any]] = field(default_factory=list)
    offline_cache_was_empty: bool | None = None


def _safe_len(obj: Any) -> int:
    try:
        return len(obj)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return 0


def occurrence_collection_hash(records: list[dict[str, Any]]) -> str:
    """Hash of an occurrence collection (canonically sorted records)."""
    ordered = sorted(canonical_json_bytes(r) for r in records)
    payload = {
        "serialization_version": RELATIONSHIP_SERIALIZATION_VERSION,
        "records": [r.decode("utf-8") for r in ordered],
    }
    return sha256_hex(canonical_json_bytes(payload))


def fact_locator_stats(model_xbrl: Any) -> dict[str, Any]:
    """Full-coverage fact locator statistics (candidates for Slice 2 occurrence model)."""
    facts = list(getattr(model_xbrl, "facts", []) or [])
    with_id = 0
    without_id = 0
    with_sourceline = 0
    without_sourceline = 0
    numeric = 0
    non_numeric = 0
    nil_facts = 0
    inline_facts = 0
    non_inline_facts = 0
    continuation_starts = 0
    unreconstructable = 0
    ids_by_doc: dict[str, list[str]] = {}
    lines_by_doc: dict[str, dict[int, int]] = {}
    id_to_docs: dict[str, set[str]] = {}
    continuation_chain_lengths: list[int] = []

    for fact in facts:
        fact_id = getattr(fact, "id", None)
        sourceline = getattr(fact, "sourceline", None)
        doc = getattr(fact, "modelDocument", None)
        doc_uri = strip_fragment(str(getattr(doc, "uri", "") or ""))
        is_numeric = bool(getattr(fact, "isNumeric", False))
        is_nil = bool(getattr(fact, "isNil", False))
        concept = getattr(fact, "concept", None)
        doc_type = classify_document_type(doc) if doc is not None else "unknown"
        is_inline = doc_type == "inline_instance"

        if fact_id:
            with_id += 1
            ids_by_doc.setdefault(doc_uri, []).append(str(fact_id))
            id_to_docs.setdefault(str(fact_id), set()).add(doc_uri)
        else:
            without_id += 1

        if sourceline is not None:
            with_sourceline += 1
            try:
                line_i = int(sourceline)
            except (TypeError, ValueError):
                line_i = -1
            lines_by_doc.setdefault(doc_uri, {})
            lines_by_doc[doc_uri][line_i] = lines_by_doc[doc_uri].get(line_i, 0) + 1
        else:
            without_sourceline += 1

        if is_numeric:
            numeric += 1
        else:
            non_numeric += 1
        if is_nil:
            nil_facts += 1
        if is_inline:
            inline_facts += 1
        else:
            non_inline_facts += 1

        cont = getattr(fact, "continuationElement", None) or getattr(fact, "ixContinuation", None)
        if cont is not None or bool(getattr(fact, "isContinuation", False)):
            continuation_starts += 1
            length = 1
            seen_objs: set[int] = set()
            cur = cont
            while cur is not None and id(cur) not in seen_objs and length < 100:
                seen_objs.add(id(cur))
                length += 1
                cur = getattr(cur, "continuationElement", None)
            continuation_chain_lengths.append(length)

        if not fact_id and sourceline is None and concept is None:
            unreconstructable += 1

    duplicate_ids_within_doc = 0
    for _doc, ids in ids_by_doc.items():
        seen_ids: set[str] = set()
        for i in ids:
            if i in seen_ids:
                duplicate_ids_within_doc += 1
            seen_ids.add(i)

    duplicate_ids_across_docs = sum(1 for _i, docs in id_to_docs.items() if len(docs) > 1)

    facts_sharing_source_line = 0
    for _doc, lines in lines_by_doc.items():
        for _line, count in lines.items():
            if count > 1:
                facts_sharing_source_line += count

    total = len(facts)
    return {
        "fact_count": total,
        "with_id": with_id,
        "without_id": without_id,
        "pct_with_id": round(100.0 * with_id / total, 4) if total else 0.0,
        "duplicate_ids_within_document": duplicate_ids_within_doc,
        "duplicate_ids_across_documents": duplicate_ids_across_docs,
        "with_sourceline": with_sourceline,
        "without_sourceline": without_sourceline,
        "facts_sharing_source_line": facts_sharing_source_line,
        "numeric": numeric,
        "non_numeric": non_numeric,
        "nil_facts": nil_facts,
        "inline_facts": inline_facts,
        "non_inline_facts": non_inline_facts,
        "continuation_start_facts": continuation_starts,
        "continuation_chain_count": len(continuation_chain_lengths),
        "continuation_chain_lengths": continuation_chain_lengths[:50],
        "unreconstructable_locator_facts": unreconstructable,
        "notes": (
            "These fields are available candidates for the Slice 2 occurrence model. "
            "A source line is not inherently an occurrence identifier."
        ),
    }


def materialize_working_tree(
    store: Any,
    artifacts: list[Any],
    dest: Path,
) -> dict[str, Path]:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, Path] = {}
    for artifact in artifacts:
        logical_path = artifact.logical_path
        target = dest / logical_path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = store.open_bytes(artifact.sha256)
        if sha256_hex(data) != artifact.sha256:
            raise RuntimeError(f"object store integrity failure for {logical_path}")
        target.write_bytes(data)
        mapping[logical_path] = target
    return mapping


def materialize_arelle_web_cache(
    uri_to_path: dict[str, Path],
    web_cache_dir: Path,
) -> dict[str, str]:
    """Populate an empty Arelle web cache from serialized bindings only.

    This reconstructs Arelle's URL→cache-path layout from the immutable bundle.
    It does not copy a prior online cache.
    """
    from arelle import Cntlr

    if web_cache_dir.exists():
        shutil.rmtree(web_cache_dir)
    web_cache_dir.mkdir(parents=True, exist_ok=True)

    cntlr = Cntlr.Cntlr(logFileName="logToBuffer")
    cntlr.webCache.cacheDir = str(web_cache_dir)
    written: dict[str, str] = {}
    try:
        for uri, source in sorted(uri_to_path.items()):
            if not is_http_uri(uri):
                continue
            if not source.is_file():
                continue
            filepath = cntlr.webCache.urlToCacheFilepath(uri)
            filepath = cntlr.webCache.normalizeFilepath(filepath, uri)
            dest = Path(filepath)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())
            written[uri] = str(dest)
    finally:
        with contextlib.suppress(Exception):
            cntlr.close()
    return written


def build_oasis_catalog(uri_to_path: dict[str, Path], catalog_path: Path) -> bytes:
    """Build an OASIS catalog with paths relative to the catalog file."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- generator={CATALOG_GENERATOR_VERSION} -->",
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">',
    ]
    catalog_path = catalog_path.resolve()
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    for uri in sorted(uri_to_path.keys()):
        target = uri_to_path[uri].resolve()
        try:
            rel = os.path.relpath(target, start=catalog_path.parent)
        except ValueError:
            rel = target.as_uri()
        else:
            rel = Path(rel).as_posix()
        safe_uri = (
            uri.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        safe_path = (
            rel.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lines.append(f'  <uri name="{safe_uri}" uri="{safe_path}"/>')
    lines.append("</catalog>")
    lines.append("")
    data = "\n".join(lines).encode("utf-8")
    catalog_path.write_bytes(data)
    return data


def build_accession_uri_map(
    *,
    archive_base: str,
    artifacts: list[Any],
    working: Path,
) -> dict[str, tuple[Any, str]]:
    """Map resolved local path → (artifact, canonical SEC URI)."""
    archive = normalize_uri(archive_base)
    if not archive.endswith("/"):
        archive += "/"
    mapping: dict[str, tuple[Any, str]] = {}
    for artifact in artifacts:
        if not artifact.logical_path.startswith("accession/"):
            continue
        name = artifact.logical_path.split("/", 1)[1]
        local = (working / artifact.logical_path).resolve()
        canonical = normalize_uri(archive + name)
        mapping[str(local)] = (artifact, canonical)
    return mapping


def _local_candidates(uri: str) -> list[str]:
    """Candidate local-path keys for a raw Arelle document URI."""
    candidates = [uri]
    if uri.startswith("file://"):
        path = unquote(urlsplit(uri).path)
        candidates.append(path)
        candidates.append(str(Path(path).resolve()))
    else:
        with contextlib.suppress(OSError, ValueError):
            candidates.append(str(Path(uri).resolve()))
    return candidates


def make_canonical_resolver(
    aliases: dict[str, str],
) -> Any:
    """Resolve an Arelle model document to its canonical URI (or None).

    Lookup order: resolved local filepath alias → raw URI alias → strict
    normalization of an http(s) URI. Returns None when no canonical identity
    exists (e.g. an unaliased local path).
    """

    def resolve(model_document: Any) -> str | None:
        if model_document is None:
            return None
        uri = str(getattr(model_document, "uri", "") or "")
        filepath = getattr(model_document, "filepath", None)
        if filepath:
            try:
                resolved_path = str(Path(filepath).resolve())
            except (OSError, ValueError):
                resolved_path = None
            if resolved_path and resolved_path in aliases:
                return aliases[resolved_path]
        if uri in aliases:
            return aliases[uri]
        for candidate in _local_candidates(uri):
            if candidate in aliases:
                return aliases[candidate]
        if is_http_uri(uri):
            try:
                return normalize_uri(uri)
            except UriIdentityError:
                return None
        return None

    return resolve


def canonicalize_error_records(records: Any, aliases: dict[str, str]) -> list[Any]:
    """Canonicalize structured error document URIs through the alias map.

    Local-path hrefs are replaced by canonical URIs; unresolvable non-http
    hrefs are dropped (never persisted as volatile local paths).
    """
    from spike_lib.arelle_errors import StructuredError

    canonicalized: list[Any] = []
    for record in records:
        doc_uri = record.document_uri
        canonical: str | None = None
        if doc_uri:
            base = strip_fragment(doc_uri)
            if base in aliases:
                canonical = aliases[base]
            else:
                for candidate in _local_candidates(base):
                    if candidate in aliases:
                        canonical = aliases[candidate]
                        break
            if canonical is None and is_http_uri(base):
                try:
                    canonical = normalize_uri(base)
                except UriIdentityError:
                    canonical = base
        canonicalized.append(
            StructuredError(
                severity=record.severity,
                code=record.code,
                document_uri=canonical,
                source_line=record.source_line,
            )
        )
    return canonicalized


def load_and_inspect(
    entrypoint: str,
    *,
    offline: bool,
    cache_dir: Path,
    catalog_path: Path | None = None,
    user_agent: str | None = None,
    deny_network: bool = False,
    uri_aliases: dict[str, str] | None = None,
    catalogued_uris: list[str] | None = None,
    offline_cache_started_empty: bool | None = None,
    offline_cache_populated_from_manifest: bool | None = None,
) -> ArelleLoadResult:
    """Load with Arelle and extract canonical closure + relationship state."""
    import arelle.Version
    from arelle import Cntlr
    from arelle.ModelDocument import Type as ModelDocumentType

    from spike_lib.network_guard import NetworkDeniedError, NetworkGuard, network_denied

    cache_dir.mkdir(parents=True, exist_ok=True)
    web_cache_dir = cache_dir / "arelle-web-cache"
    if offline:
        web_cache_dir.mkdir(parents=True, exist_ok=True)
        if offline_cache_started_empty is None:
            offline_cache_started_empty = not any(web_cache_dir.iterdir())
        if offline_cache_populated_from_manifest is None:
            offline_cache_populated_from_manifest = any(web_cache_dir.rglob("*"))
    else:
        if web_cache_dir.exists():
            shutil.rmtree(web_cache_dir)
        web_cache_dir.mkdir(parents=True, exist_ok=True)
        offline_cache_started_empty = None
        offline_cache_populated_from_manifest = None

    prior_catalog = os.environ.get("XML_CATALOG_FILES")
    if catalog_path is not None:
        os.environ["XML_CATALOG_FILES"] = str(catalog_path.resolve())
    elif "XML_CATALOG_FILES" in os.environ:
        del os.environ["XML_CATALOG_FILES"]

    cleared_proxy: dict[str, str] = {}
    if offline:
        proxy_keys = (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
        )
        for key in proxy_keys:
            if key in os.environ:
                cleared_proxy[key] = os.environ.pop(key)

    guard = NetworkGuard()
    issues: list[QualityIssue] = []
    raw_log = ""
    network_attempt_dicts: list[dict[str, Any]] = []
    aliases = dict(uri_aliases or {})
    resolve_canonical = make_canonical_resolver(aliases)
    error_capture = ErrorCapture()

    def _do_load() -> ArelleLoadResult:
        nonlocal raw_log
        cntlr = Cntlr.Cntlr(logFileName="logToBuffer")
        cntlr.webCache.cacheDir = str(web_cache_dir)
        cntlr.webCache.workOffline = offline
        if user_agent:
            cntlr.webCache.httpUserAgent = user_agent
        cntlr_logger = getattr(cntlr, "logger", None)
        if cntlr_logger is not None:
            cntlr_logger.addHandler(error_capture)

        if offline and deny_network:
            original_retrieve = getattr(cntlr.webCache, "retrieve", None)
            if original_retrieve is not None:
                catalogued = set(catalogued_uris or [])

                def guarded_retrieve(url, *args, **kwargs):  # type: ignore[no-untyped-def]
                    normalized = strip_fragment(str(url))
                    if is_http_uri(normalized) and normalized not in catalogued:
                        guard.record("arelle_webcache_retrieve", normalized, None)
                        raise NetworkDeniedError(guard.attempts[-1])
                    return original_retrieve(url, *args, **kwargs)

                cntlr.webCache.retrieve = guarded_retrieve  # type: ignore[method-assign]

        try:
            model_xbrl = cntlr.modelManager.load(entrypoint)
        except NetworkDeniedError:
            raise
        if model_xbrl is None:
            raise RuntimeError("Arelle failed to load entrypoint")

        try:
            log_handler = getattr(cntlr, "logHandler", None)
            if log_handler is not None and hasattr(log_handler, "getBuffer"):
                raw_log = str(log_handler.getBuffer() or "")
            else:
                buf = getattr(cntlr, "logBuffer", None) or getattr(
                    getattr(cntlr, "logHandler", None), "buffer", None
                )
                raw_log = str(buf or "")
        except Exception:  # noqa: BLE001
            raw_log = ""

        log_error_count = raw_log.lower().count("[error") + raw_log.lower().count(" error ")
        log_warning_count = raw_log.lower().count("[warning") + raw_log.lower().count(" warning ")

        url_docs = getattr(model_xbrl, "urlDocs", {}) or {}
        closure_documents: list[ClosureDocument] = []
        synthetic_docs: list[dict[str, Any]] = []
        synthetic_engine_uris: set[str] = set()
        unresolved: list[str] = []

        for uri, doc in url_docs.items():
            raw_uri = strip_fragment(str(uri))
            doc_type = classify_document_type(doc)
            filepath = getattr(doc, "filepath", None)

            if getattr(doc, "type", None) == ModelDocumentType.INLINEXBRLDOCUMENTSET:
                member_uris: list[str] = []
                for member in getattr(doc, "referencesDocument", {}) or {}:
                    if getattr(member, "type", None) == ModelDocumentType.INLINEXBRL:
                        member_uri = resolve_canonical(member)
                        if member_uri:
                            member_uris.append(member_uri)
                if member_uris:
                    identity = inline_document_set_identity(member_uris)
                else:
                    identity = unknown_synthetic_identity(raw_uri)
                synthetic_docs.append(
                    {"synthetic_document_identity": identity, "engine_uri": raw_uri}
                )
                synthetic_engine_uris.add(raw_uri)
                continue

            canonical = resolve_canonical(doc)
            if canonical is None:
                canonical = raw_uri
                issues.append(
                    QualityIssue(
                        severity="fatal",
                        code="UNRESOLVED_DOC_IDENTITY",
                        message="loaded document has no canonical URI identity",
                        context={"raw_uri": raw_uri, "offline": offline},
                    )
                )
            content_sha = ""
            byte_size = 0
            local_path = None
            if filepath and Path(filepath).is_file():
                data = Path(filepath).read_bytes()
                content_sha = sha256_hex(data)
                byte_size = len(data)
                local_path = str(Path(filepath).resolve())
            else:
                unresolved.append(canonical)
                issues.append(
                    QualityIssue(
                        severity="fatal",
                        code="UNRESOLVED_DTS_DOCUMENT",
                        message="loaded document URI has no local filepath bytes",
                        context={"uri": canonical, "offline": offline},
                    )
                )
            closure_documents.append(
                ClosureDocument(
                    canonical_uri=canonical,
                    content_sha256=content_sha,
                    document_type=doc_type,
                    local_path=local_path,
                    byte_size=byte_size,
                )
            )

        synthetic_by_engine_uri = {d["engine_uri"]: d for d in synthetic_docs}

        source_backed_edges: list[ClosureEdge] = []
        synthetic_edges: list[dict[str, Any]] = []
        reference_uris: set[str] = set()

        for uri, doc in url_docs.items():
            raw_uri = strip_fragment(str(uri))
            source_synthetic = raw_uri in synthetic_engine_uris
            source_uri = resolve_canonical(doc) or raw_uri
            references = getattr(doc, "referencesDocument", {}) or {}
            for target_doc, ref_info in references.items():
                target_raw = strip_fragment(str(getattr(target_doc, "uri", "") or ""))
                if not target_raw:
                    continue
                target_synthetic = target_raw in synthetic_engine_uris
                target_uri = resolve_canonical(target_doc) or target_raw
                ref_list = ref_info if isinstance(ref_info, list) else [ref_info]
                for ref in ref_list:
                    reference_types = getattr(ref, "referenceTypes", None)
                    if reference_types is None:
                        singular = getattr(ref, "referenceType", None) or getattr(ref, "type", None)
                        reference_types = {singular} if singular is not None else set()
                    href = getattr(ref, "href", None) or target_uri
                    try:
                        normalized_href = resolve_document_uri(source_uri, str(href))
                        if is_http_uri(normalized_href):
                            reference_uris.add(normalized_href)
                    except (UriIdentityError, ValueError):
                        normalized_href = strip_fragment(str(href))
                    mapped_types = map_discovery_types(reference_types)
                    # Arelle records linkbaseRef/schemaRef/roleRef/arcroleRef edges
                    # with the generic "href" reference type; the specific element
                    # is available on referringModelObject.
                    referring = getattr(ref, "referringModelObject", None)
                    referring_ln = getattr(referring, "localName", None)
                    if referring_ln in ("linkbaseRef", "schemaRef", "roleRef", "arcroleRef"):
                        specific = map_discovery_type(referring_ln)
                        mapped_types = [
                            specific if m == "locator_reference" else m for m in mapped_types
                        ]
                    for discovery_type in mapped_types:
                        if source_synthetic or target_synthetic:
                            if source_synthetic:
                                source_identity: dict[str, Any] = {
                                    "kind": "synthetic_document",
                                    "synthetic_document_identity": synthetic_by_engine_uri[raw_uri][
                                        "synthetic_document_identity"
                                    ],
                                }
                            else:
                                source_identity = {
                                    "kind": "source_backed_document",
                                    "document_uri": source_uri,
                                }
                            if target_synthetic:
                                target_identity: dict[str, Any] = {
                                    "kind": "synthetic_document",
                                    "synthetic_document_identity": synthetic_by_engine_uri[
                                        target_raw
                                    ]["synthetic_document_identity"],
                                }
                            else:
                                target_identity = {
                                    "kind": "source_backed_document",
                                    "document_uri": target_uri,
                                }
                            synthetic_edges.append(
                                {
                                    "kind": "engine_reference",
                                    "source": source_identity,
                                    "target": target_identity,
                                    "edge_attributes": {
                                        "discovery_type": discovery_type,
                                        "normalized_href": normalized_href,
                                    },
                                }
                            )
                        else:
                            source_backed_edges.append(
                                ClosureEdge(
                                    source_uri=source_uri,
                                    discovery_type=discovery_type,
                                    target_uri=target_uri,
                                    normalized_href=normalized_href,
                                )
                            )

        entry_points: list[str] = []
        model_doc = getattr(model_xbrl, "modelDocument", None)
        if model_doc is not None:
            ep = resolve_canonical(model_doc)
            if ep is not None:
                entry_points.append(ep)

        concepts = getattr(model_xbrl, "qnameConcepts", {}) or {}
        contexts = getattr(model_xbrl, "contexts", {}) or {}
        units = getattr(model_xbrl, "units", {}) or {}
        facts = getattr(model_xbrl, "facts", []) or []

        rel_result = collect_relationships(model_xbrl, canonical_doc_uri=resolve_canonical)
        concept_records = rel_result["concept_records"]
        resource_records = rel_result["resource_records"]
        concept_occ_hash = occurrence_collection_hash(concept_records)
        resource_occ_hash = occurrence_collection_hash(resource_records)

        version = str(
            getattr(arelle.Version, "__version__", None)
            or getattr(arelle.Version, "version", None)
            or "unknown"
        )

        plugins: list[str] = []
        try:
            plugin_info = getattr(cntlr, "pluginInfo", None) or {}
            plugins = sorted(str(k) for k in plugin_info)
        except Exception:  # noqa: BLE001
            plugins = []

        engine_config = {
            "cache_mode": ("isolated-manifest-seeded" if offline else "isolated-online"),
            "work_offline": offline,
            "catalog_generator_version": CATALOG_GENERATOR_VERSION,
            "catalog_configured": catalog_path is not None,
            "validation_enabled": False,
            "plugins": plugins,
            "deny_network": deny_network,
            "offline_cache_started_empty": offline_cache_started_empty,
            "offline_cache_populated_from_manifest": offline_cache_populated_from_manifest,
        }

        log_digest = sha256_hex(raw_log.encode("utf-8")) if raw_log else None

        synthetic_identities = [d["synthetic_document_identity"] for d in synthetic_docs]

        snapshot = InspectionSnapshot(
            documents=[
                {
                    "canonical_uri": d.canonical_uri,
                    "content_sha256": d.content_sha256,
                    "document_type": d.document_type,
                    "byte_size": d.byte_size,
                }
                for d in sorted(closure_documents, key=lambda x: x.canonical_uri)
            ],
            edges=[
                {
                    "source_uri": e.source_uri,
                    "discovery_type": e.discovery_type,
                    "target_uri": e.target_uri,
                    "normalized_href": e.normalized_href,
                }
                for e in sorted(
                    source_backed_edges,
                    key=lambda x: (
                        x.source_uri,
                        x.discovery_type,
                        x.target_uri,
                        x.normalized_href,
                    ),
                )
            ],
            concept_count=_safe_len(concepts),
            context_count=_safe_len(contexts),
            unit_count=_safe_len(units),
            fact_count=_safe_len(facts),
            relationship_counts=rel_result["relationship_counts"],
            resource_relationship_counts=rel_result["resource_relationship_counts"],
            concept_records=concept_records,
            resource_records=resource_records,
            concept_relationship_occurrence_hash=concept_occ_hash,
            resource_relationship_occurrence_hash=resource_occ_hash,
            unsupported_inventory=rel_result["unsupported_inventory"],
            extraction=rel_result["extraction"],
            synthetic_documents=sorted(synthetic_docs, key=lambda d: canonical_json_bytes(d)),
            synthetic_document_set_hash=synthetic_document_set_hash(synthetic_identities),
            synthetic_document_count=len(synthetic_docs),
            synthetic_edges=sorted(synthetic_edges, key=lambda e: canonical_json_bytes(e)),
            synthetic_edge_set_hash=synthetic_edge_set_hash(synthetic_edges),
            synthetic_edge_count=len(synthetic_edges),
            entry_points=sorted(set(entry_points)),
            unresolved_uris=sorted(set(unresolved)),
            fact_locator_stats=fact_locator_stats(model_xbrl),
            error_summary=summarize_errors(
                canonicalize_error_records(error_capture.records, aliases)
            ),
            engine_name="arelle",
            engine_version=version,
            engine_config=engine_config,
            log_sha256=log_digest,
            log_error_count=log_error_count,
            log_warning_count=log_warning_count,
        )

        with contextlib.suppress(Exception):
            model_xbrl.close()
        with contextlib.suppress(Exception):
            cntlr.close()

        return ArelleLoadResult(
            snapshot=snapshot,
            closure_documents=closure_documents,
            closure_edges=source_backed_edges,
            reference_uris=sorted(reference_uris),
            issues=issues,
            raw_log=raw_log,
            network_attempts=network_attempt_dicts,
            offline_cache_was_empty=offline_cache_started_empty,
        )

    try:
        if deny_network:
            with network_denied(guard):
                result = _do_load()
        else:
            result = _do_load()
    finally:
        if prior_catalog is None:
            os.environ.pop("XML_CATALOG_FILES", None)
        else:
            os.environ["XML_CATALOG_FILES"] = prior_catalog
        for key, value in cleared_proxy.items():
            os.environ[key] = value

    result.network_attempts = [a.to_dict() for a in guard.attempts]
    return result


def external_logical_path(original_uri: str) -> str:
    from spike_lib.hashing import sha256_of_uri

    basename = sanitize_basename(Path(urlsplit(original_uri).path).name or "dependency")
    return f"external/{sha256_of_uri(original_uri)}/{basename}"
