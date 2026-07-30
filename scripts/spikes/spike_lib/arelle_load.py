"""Arelle load, DTS closure capture, relationship sets, and offline catalog helpers."""

from __future__ import annotations

import contextlib
import os
import shutil
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urlparse

from spike_lib import CATALOG_GENERATOR_VERSION
from spike_lib.hashing import relationship_set_hash, sha256_hex, sha256_of_uri
from spike_lib.quality import QualityIssue
from spike_lib.sec import sanitize_basename

# Standard XBRL arcroles used for Phase 1 network persistence.
PRESENTATION_ARCROLE = "http://www.xbrl.org/2003/arcrole/parent-child"
CALCULATION_ARCROLE = "http://www.xbrl.org/2003/arcrole/summation-item"
DIMENSION_ARCROLES = (
    "http://xbrl.org/int/dim/arcrole/all",
    "http://xbrl.org/int/dim/arcrole/notAll",
    "http://xbrl.org/int/dim/arcrole/hypercube-dimension",
    "http://xbrl.org/int/dim/arcrole/dimension-domain",
    "http://xbrl.org/int/dim/arcrole/domain-member",
    "http://xbrl.org/int/dim/arcrole/dimension-default",
)


def strip_fragment(uri: str) -> str:
    base, _frag = urldefrag(uri)
    return base


def normalize_uri_for_identity(uri: str) -> str:
    return strip_fragment(uri.strip())


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
    if "INLINE" in upper:
        return "inline_instance"
    if "INSTANCE" in upper:
        return "instance"
    if "SCHEMA" in upper:
        return "schema"
    if "LINKBASE" in upper:
        return "linkbase"
    if "UNKNOWN" in upper:
        return "unknown"
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

    # Prefer arcroleref before roleref when both present by sorting with priority.
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
    relationship_records: list[dict[str, Any]]
    relationship_set_hash: str
    entry_points: list[str]
    unresolved_uris: list[str]
    fact_locator_stats: dict[str, Any]
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
    uri_to_local_file: dict[str, Path] = field(default_factory=dict)
    issues: list[QualityIssue] = field(default_factory=list)
    raw_log: str = ""
    network_attempts: list[dict[str, Any]] = field(default_factory=list)
    offline_cache_was_empty: bool | None = None


def _safe_len(obj: Any) -> int:
    try:
        return len(obj)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return 0


def _qname_str(obj: Any) -> str | None:
    if obj is None:
        return None
    qname = getattr(obj, "qname", None)
    if qname is None:
        return None
    return str(qname)


def _decimal_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return format(Decimal(str(value)), "f")
    except Exception:  # noqa: BLE001
        return str(value)


def _network_type_for_arcrole(arcrole: str) -> str:
    lower = arcrole.lower()
    if "parent-child" in lower:
        return "presentation"
    if "summation" in lower:
        return "calculation"
    if "dim/arcrole" in lower or "/dimension" in lower:
        return "definition"
    return "other"


def canonical_relationship_record(rel: Any, *, network_type: str, arcrole: str) -> dict[str, Any]:
    """Build a canonical effective relationship record.

    Absent fields are serialized as null consistently. Only applicable fields
    for the relationship type are populated when available.
    """
    link_role = getattr(rel, "linkrole", None) or getattr(rel, "linkRole", None)
    preferred = getattr(rel, "preferredLabel", None)
    target_role = getattr(rel, "targetRole", None)
    closed = getattr(rel, "closed", None)
    usable = getattr(rel, "usable", None)
    context_element = getattr(rel, "contextElement", None)
    order = getattr(rel, "order", None)
    weight = getattr(rel, "weight", None)
    from_model = getattr(rel, "fromModelObject", None)
    to_model = getattr(rel, "toModelObject", None)
    return {
        "network_type": network_type,
        "arcrole_uri": arcrole,
        "link_role_uri": str(link_role) if link_role else None,
        "source_concept": _qname_str(from_model),
        "target_concept": _qname_str(to_model),
        "order": _decimal_or_none(order),
        "weight": _decimal_or_none(weight),
        "preferred_label_role": str(preferred) if preferred else None,
        "target_role": str(target_role) if target_role else None,
        "closed": closed if isinstance(closed, bool) else None,
        "usable": usable if isinstance(usable, bool) else None,
        "context_element": str(context_element) if context_element else None,
    }


def relationship_key(record: dict[str, Any]) -> tuple[Any, ...]:
    def norm(value: Any) -> tuple[int, str]:
        if value is None:
            return (0, "")
        return (1, str(value))

    return (
        norm(record.get("network_type")),
        norm(record.get("arcrole_uri")),
        norm(record.get("link_role_uri")),
        norm(record.get("source_concept")),
        norm(record.get("target_concept")),
        norm(record.get("order")),
        norm(record.get("weight")),
        norm(record.get("preferred_label_role")),
        norm(record.get("target_role")),
        norm(record.get("closed")),
        norm(record.get("usable")),
        norm(record.get("context_element")),
    )


def collect_effective_relationships(model_xbrl: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Enumerate unique effective relationships via relationshipSet(...).

    Iterates known arcroles and each link role present in baseSets to avoid
    unpredictable aggregation across link roles.
    """
    records_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    counts = {"presentation": 0, "calculation": 0, "definition": 0, "other": 0}

    arcroles = [PRESENTATION_ARCROLE, CALCULATION_ARCROLE, *DIMENSION_ARCROLES]
    # Also include any other arcroles present in baseSets keys.
    base_sets = getattr(model_xbrl, "baseSets", None) or {}
    for key in base_sets:
        if isinstance(key, tuple) and key and key[0]:
            arc = str(key[0])
            if arc not in arcroles and arc != "XBRL-footnotes":
                arcroles.append(arc)

    linkroles_by_arcrole: dict[str, set[str | None]] = {a: {None} for a in arcroles}
    for key in base_sets:
        if isinstance(key, tuple) and len(key) >= 2 and key[0]:
            arc = str(key[0])
            link = key[1]
            linkroles_by_arcrole.setdefault(arc, {None}).add(str(link) if link else None)

    for arcrole in arcroles:
        network_type = _network_type_for_arcrole(arcrole)
        for linkrole in sorted(
            (lr for lr in linkroles_by_arcrole.get(arcrole, {None})),
            key=lambda x: (x is None, str(x) if x else ""),
        ):
            try:
                if linkrole is None:
                    rel_set = model_xbrl.relationshipSet(arcrole)
                else:
                    rel_set = model_xbrl.relationshipSet(arcrole, linkrole)
            except Exception:  # noqa: BLE001
                continue
            if rel_set is None:
                continue
            model_rels = getattr(rel_set, "modelRelationships", None) or []
            for rel in model_rels:
                record = canonical_relationship_record(
                    rel, network_type=network_type, arcrole=arcrole
                )
                key = relationship_key(record)
                if key not in records_by_key:
                    records_by_key[key] = record

    records = sorted(records_by_key.values(), key=lambda r: relationship_key(r))
    for record in records:
        counts[record["network_type"]] = counts.get(record["network_type"], 0) + 1
    return records, counts


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
        doc_uri = normalize_uri_for_identity(str(getattr(doc, "uri", "") or ""))
        is_numeric = bool(getattr(fact, "isNumeric", False))
        is_nil = bool(getattr(fact, "isNil", False))
        concept = getattr(fact, "concept", None)
        # Inline detection: document type or ix attributes.
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

        # Continuation: Arelle exposes continuationElement / isContinuation.
        cont = getattr(fact, "continuationElement", None) or getattr(fact, "ixContinuation", None)
        if cont is not None or bool(getattr(fact, "isContinuation", False)):
            continuation_starts += 1
            # Best-effort chain length walk.
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

    # ID uniqueness within each document
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
        target.write_bytes(store.open_bytes(artifact.sha256))
        mapping[logical_path] = target
    return mapping


def materialize_arelle_web_cache(
    uri_to_path: dict[str, Path],
    web_cache_dir: Path,
) -> dict[str, str]:
    """Populate an empty Arelle web cache from manifested local files.

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
    """Build an OASIS catalog with paths relative to the catalog file.

    Relative paths keep catalog bytes stable across different absolute data roots
    when the working-tree layout is identical.
    """
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
            # Prefer file URI only when relative form is unavailable; else use path.
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
    archive = normalize_uri_for_identity(archive_base)
    if not archive.endswith("/"):
        archive += "/"
    mapping: dict[str, tuple[Any, str]] = {}
    for artifact in artifacts:
        if not artifact.logical_path.startswith("accession/"):
            continue
        name = artifact.logical_path.split("/", 1)[1]
        local = (working / artifact.logical_path).resolve()
        canonical = normalize_uri_for_identity(archive + name)
        mapping[str(local)] = (artifact, canonical)
        # Also key by content hash for fallback matching.
    return mapping


def load_with_arelle(
    entrypoint: Path,
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
    import arelle.Version
    from arelle import Cntlr

    from spike_lib.network_guard import NetworkDeniedError, NetworkGuard, network_denied

    cache_dir.mkdir(parents=True, exist_ok=True)
    web_cache_dir = cache_dir / "arelle-web-cache"
    if offline:
        web_cache_dir.mkdir(parents=True, exist_ok=True)
        if offline_cache_started_empty is None:
            # If not explicitly reported by caller, infer: no http/https cache trees yet.
            offline_cache_started_empty = not any(web_cache_dir.iterdir())
        if offline_cache_populated_from_manifest is None:
            offline_cache_populated_from_manifest = any(web_cache_dir.rglob("*"))
    else:
        if web_cache_dir.exists():
            shutil.rmtree(web_cache_dir)
        web_cache_dir.mkdir(parents=True, exist_ok=True)
        offline_cache_started_empty = None
        offline_cache_populated_from_manifest = None

    # Fresh catalog env for this load.
    prior_catalog = os.environ.get("XML_CATALOG_FILES")
    if catalog_path is not None:
        os.environ["XML_CATALOG_FILES"] = str(catalog_path.resolve())
    elif "XML_CATALOG_FILES" in os.environ:
        del os.environ["XML_CATALOG_FILES"]

    # Clear common proxy env vars during offline loads where practical.
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

    def _do_load() -> ArelleLoadResult:
        nonlocal raw_log
        cntlr = Cntlr.Cntlr(logFileName="logToBuffer")
        cntlr.webCache.cacheDir = str(web_cache_dir)
        cntlr.webCache.workOffline = offline
        if user_agent:
            cntlr.webCache.httpUserAgent = user_agent

        # Extra guard: if Arelle's web cache attempts a remote retrieve while offline,
        # record it and deny for URIs not present in the manifest-backed catalog.
        if offline and deny_network:
            original_retrieve = getattr(cntlr.webCache, "retrieve", None)
            if original_retrieve is not None:
                catalogued = {normalize_uri_for_identity(u) for u in (catalogued_uris or [])}
                if uri_aliases:
                    catalogued.update(normalize_uri_for_identity(u) for u in uri_aliases.values())

                def guarded_retrieve(url, *args, **kwargs):  # type: ignore[no-untyped-def]
                    normalized = normalize_uri_for_identity(str(url))
                    if is_http_uri(normalized) and normalized not in catalogued:
                        guard.record("arelle_webcache_retrieve", normalized, None)
                        raise NetworkDeniedError(guard.attempts[-1])
                    return original_retrieve(url, *args, **kwargs)

                cntlr.webCache.retrieve = guarded_retrieve  # type: ignore[method-assign]

        try:
            model_xbrl = cntlr.modelManager.load(str(entrypoint.resolve()))
        except NetworkDeniedError:
            raise
        if model_xbrl is None:
            raise RuntimeError("Arelle failed to load entrypoint")

        # Capture log buffer.
        try:
            log_handler = getattr(cntlr, "logHandler", None)
            if log_handler is not None and hasattr(log_handler, "getBuffer"):
                raw_log = str(log_handler.getBuffer() or "")
            elif hasattr(cntlr, "logToBuffer") or True:
                messages = getattr(getattr(cntlr, "logHandler", None), "messages", None)
                if messages:
                    raw_log = "\n".join(str(m) for m in messages)
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
        uri_to_local: dict[str, Path] = {}
        unresolved: list[str] = []
        aliases = uri_aliases or {}

        for uri, doc in url_docs.items():
            raw_uri = normalize_uri_for_identity(str(uri))
            filepath = getattr(doc, "filepath", None)
            if filepath and Path(filepath).is_file():
                local_resolved = str(Path(filepath).resolve())
            else:
                local_resolved = None
            canonical = aliases.get(local_resolved or "", aliases.get(raw_uri, raw_uri))
            # Prefer alias by local path, then by raw URI.
            if local_resolved and local_resolved in aliases:
                canonical = aliases[local_resolved]
            elif raw_uri in aliases:
                canonical = aliases[raw_uri]

            content_sha = ""
            byte_size = 0
            local_path = None
            if filepath and Path(filepath).is_file():
                data = Path(filepath).read_bytes()
                content_sha = sha256_hex(data)
                byte_size = len(data)
                local_path = str(Path(filepath).resolve())
                uri_to_local[canonical] = Path(filepath).resolve()
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
                    document_type=classify_document_type(doc),
                    local_path=local_path,
                    byte_size=byte_size,
                )
            )

        closure_edges: list[ClosureEdge] = []
        for uri, doc in url_docs.items():
            raw_uri = normalize_uri_for_identity(str(uri))
            filepath = getattr(doc, "filepath", None)
            local_resolved = (
                str(Path(filepath).resolve()) if filepath and Path(filepath).is_file() else None
            )
            source_uri = aliases.get(local_resolved or "", aliases.get(raw_uri, raw_uri))
            if local_resolved and local_resolved in aliases:
                source_uri = aliases[local_resolved]
            references = getattr(doc, "referencesDocument", {}) or {}
            for target_doc, ref_info in references.items():
                target_raw = normalize_uri_for_identity(str(getattr(target_doc, "uri", "") or ""))
                if not target_raw:
                    continue
                t_filepath = getattr(target_doc, "filepath", None)
                t_local = (
                    str(Path(t_filepath).resolve())
                    if t_filepath and Path(t_filepath).is_file()
                    else None
                )
                target_uri = aliases.get(t_local or "", aliases.get(target_raw, target_raw))
                if t_local and t_local in aliases:
                    target_uri = aliases[t_local]
                ref_list = ref_info if isinstance(ref_info, list) else [ref_info]
                for ref in ref_list:
                    # Arelle 2.x exposes plural referenceTypes set.
                    reference_types = getattr(ref, "referenceTypes", None)
                    if reference_types is None:
                        singular = getattr(ref, "referenceType", None) or getattr(ref, "type", None)
                        reference_types = {singular} if singular is not None else set()
                    href = getattr(ref, "href", None) or target_uri
                    for discovery_type in map_discovery_types(reference_types):
                        closure_edges.append(
                            ClosureEdge(
                                source_uri=source_uri,
                                discovery_type=discovery_type,
                                target_uri=target_uri,
                                normalized_href=normalize_uri_for_identity(str(href)),
                            )
                        )

        entry_points: list[str] = []
        model_doc = getattr(model_xbrl, "modelDocument", None)
        if model_doc is not None:
            ep_raw = normalize_uri_for_identity(str(model_doc.uri))
            ep_path = getattr(model_doc, "filepath", None)
            ep_local = str(Path(ep_path).resolve()) if ep_path and Path(ep_path).is_file() else None
            ep = aliases.get(ep_local or "", aliases.get(ep_raw, ep_raw))
            if ep_local and ep_local in aliases:
                ep = aliases[ep_local]
            entry_points.append(ep)

        concepts = getattr(model_xbrl, "qnameConcepts", {}) or {}
        contexts = getattr(model_xbrl, "contexts", {}) or {}
        units = getattr(model_xbrl, "units", {}) or {}
        facts = getattr(model_xbrl, "facts", []) or []

        rel_records, rel_counts = collect_effective_relationships(model_xbrl)
        rel_hash = relationship_set_hash(rel_records)

        version = str(
            getattr(arelle.Version, "__version__", None)
            or getattr(arelle.Version, "version", None)
            or "unknown"
        )

        # Plugin inventory (best-effort).
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
                    closure_edges,
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
            relationship_counts=rel_counts,
            relationship_records=rel_records,
            relationship_set_hash=rel_hash,
            entry_points=sorted(set(entry_points)),
            unresolved_uris=sorted(set(unresolved)),
            fact_locator_stats=fact_locator_stats(model_xbrl),
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
            closure_edges=closure_edges,
            uri_to_local_file=uri_to_local,
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


def is_http_uri(uri: str) -> bool:
    return urlparse(uri).scheme in {"http", "https"}


def external_logical_path(original_uri: str) -> str:
    basename = sanitize_basename(Path(urlparse(original_uri).path).name or "dependency")
    return f"external/{sha256_of_uri(original_uri)}/{basename}"
