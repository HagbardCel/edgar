"""Arelle load, DTS closure capture, and offline catalog helpers."""

from __future__ import annotations

import contextlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urlparse

from spike_lib import CATALOG_GENERATOR_VERSION
from spike_lib.hashing import sha256_hex, sha256_of_uri
from spike_lib.quality import QualityIssue
from spike_lib.sec import sanitize_basename


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


def map_discovery_type(reference_type: str | None) -> str:
    if not reference_type:
        return "other"
    key = str(reference_type).lower()
    mapping = {
        "schemaref": "schema_ref",
        "schema_ref": "schema_ref",
        "linkbaseref": "linkbase_ref",
        "linkbase_ref": "linkbase_ref",
        "import": "schema_import",
        "include": "schema_include",
        "roleref": "role_ref",
        "role_ref": "role_ref",
        "arcroleref": "arcrole_ref",
        "href": "locator_reference",
    }
    for token, value in mapping.items():
        if token in key.replace("-", "").replace("_", ""):
            return value
    if "schema" in key and "ref" in key:
        return "schema_ref"
    if "linkbase" in key:
        return "linkbase_ref"
    if "role" in key and "arc" not in key:
        return "role_ref"
    if "arcrole" in key:
        return "arcrole_ref"
    return "other"


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
    entry_points: list[str]
    unresolved_uris: list[str]
    fact_locator_samples: list[dict[str, Any]]
    engine_name: str
    engine_version: str


@dataclass
class ArelleLoadResult:
    snapshot: InspectionSnapshot
    closure_documents: list[ClosureDocument] = field(default_factory=list)
    closure_edges: list[ClosureEdge] = field(default_factory=list)
    uri_to_local_file: dict[str, Path] = field(default_factory=dict)
    issues: list[QualityIssue] = field(default_factory=list)


def _safe_len(obj: Any) -> int:
    try:
        return len(obj)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return 0


def _relationship_counts(model_xbrl: Any) -> dict[str, int]:
    counts = {"presentation": 0, "calculation": 0, "definition": 0, "other": 0}
    base_sets = getattr(model_xbrl, "baseSets", None) or {}
    for key, rels in base_sets.items():
        arcrole = str(key[0]) if isinstance(key, tuple) and key else str(key)
        n = _safe_len(rels)
        lower = arcrole.lower()
        if "parent-child" in lower:
            counts["presentation"] += n
        elif "summation" in lower:
            counts["calculation"] += n
        elif "dim/arcrole" in lower or "/dimension" in lower:
            counts["definition"] += n
        else:
            counts["other"] += n
    return counts


def _fact_locator_samples(model_xbrl: Any, limit: int = 25) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    facts = list(getattr(model_xbrl, "facts", []) or [])
    for fact in facts[:limit]:
        concept = getattr(fact, "concept", None)
        qname = str(getattr(concept, "qname", None) or getattr(fact, "qname", ""))
        doc = getattr(fact, "modelDocument", None)
        samples.append(
            {
                "qname": qname,
                "id": getattr(fact, "id", None),
                "sourceline": getattr(fact, "sourceline", None),
                "document_uri": normalize_uri_for_identity(str(getattr(doc, "uri", "") or "")),
                "context_id": getattr(getattr(fact, "context", None), "id", None),
                "unit_id": getattr(getattr(fact, "unit", None), "id", None),
                "is_numeric": bool(getattr(fact, "isNumeric", False)),
                "xpath_hint": getattr(fact, "elementXpath", None),
            }
        )
    return samples


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


def build_oasis_catalog(uri_to_path: dict[str, Path], catalog_path: Path) -> bytes:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- generator={CATALOG_GENERATOR_VERSION} -->",
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">',
    ]
    for uri in sorted(uri_to_path.keys()):
        path = uri_to_path[uri].resolve().as_uri()
        safe_uri = (
            uri.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        safe_path = (
            path.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lines.append(f'  <uri name="{safe_uri}" uri="{safe_path}"/>')
    lines.append("</catalog>")
    lines.append("")
    data = "\n".join(lines).encode("utf-8")
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_bytes(data)
    return data


def load_with_arelle(
    entrypoint: Path,
    *,
    offline: bool,
    cache_dir: Path,
    catalog_path: Path | None = None,
    user_agent: str | None = None,
) -> ArelleLoadResult:
    import arelle.Version
    from arelle import Cntlr

    cache_dir.mkdir(parents=True, exist_ok=True)
    web_cache_dir = cache_dir / "arelle-web-cache"
    web_cache_dir.mkdir(parents=True, exist_ok=True)

    if catalog_path is not None:
        os.environ["XML_CATALOG_FILES"] = str(catalog_path.resolve())
    elif "XML_CATALOG_FILES" in os.environ:
        del os.environ["XML_CATALOG_FILES"]

    cntlr = Cntlr.Cntlr(logFileName="logToBuffer")
    cntlr.webCache.cacheDir = str(web_cache_dir)
    cntlr.webCache.workOffline = offline
    if user_agent:
        # Ensure SEC-friendly identity for taxonomy fetches when online.
        cntlr.webCache.httpUserAgent = user_agent

    issues: list[QualityIssue] = []
    model_xbrl = cntlr.modelManager.load(str(entrypoint.resolve()))
    if model_xbrl is None:
        raise RuntimeError("Arelle failed to load entrypoint")

    url_docs = getattr(model_xbrl, "urlDocs", {}) or {}
    closure_documents: list[ClosureDocument] = []
    uri_to_local: dict[str, Path] = {}
    unresolved: list[str] = []

    for uri, doc in url_docs.items():
        canonical = normalize_uri_for_identity(str(uri))
        filepath = getattr(doc, "filepath", None)
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
        source_uri = normalize_uri_for_identity(str(uri))
        references = getattr(doc, "referencesDocument", {}) or {}
        for target_doc, ref_info in references.items():
            target_uri = normalize_uri_for_identity(str(getattr(target_doc, "uri", "") or ""))
            if not target_uri:
                continue
            ref_list = ref_info if isinstance(ref_info, list) else [ref_info]
            for ref in ref_list:
                reference_type = getattr(ref, "referenceType", None) or getattr(ref, "type", None)
                href = getattr(ref, "href", None) or target_uri
                closure_edges.append(
                    ClosureEdge(
                        source_uri=source_uri,
                        discovery_type=map_discovery_type(
                            str(reference_type) if reference_type is not None else None
                        ),
                        target_uri=target_uri,
                        normalized_href=normalize_uri_for_identity(str(href)),
                    )
                )

    entry_points: list[str] = []
    model_doc = getattr(model_xbrl, "modelDocument", None)
    if model_doc is not None:
        entry_points.append(normalize_uri_for_identity(str(model_doc.uri)))

    concepts = getattr(model_xbrl, "qnameConcepts", {}) or {}
    contexts = getattr(model_xbrl, "contexts", {}) or {}
    units = getattr(model_xbrl, "units", {}) or {}
    facts = getattr(model_xbrl, "facts", []) or []

    version = str(
        getattr(arelle.Version, "__version__", None)
        or getattr(arelle.Version, "version", None)
        or "unknown"
    )

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
                key=lambda x: (x.source_uri, x.discovery_type, x.target_uri, x.normalized_href),
            )
        ],
        concept_count=_safe_len(concepts),
        context_count=_safe_len(contexts),
        unit_count=_safe_len(units),
        fact_count=_safe_len(facts),
        relationship_counts=_relationship_counts(model_xbrl),
        entry_points=sorted(set(entry_points)),
        unresolved_uris=sorted(set(unresolved)),
        fact_locator_samples=_fact_locator_samples(model_xbrl),
        engine_name="arelle",
        engine_version=version,
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
    )


def is_http_uri(uri: str) -> bool:
    return urlparse(uri).scheme in {"http", "https"}


def external_logical_path(original_uri: str) -> str:
    basename = sanitize_basename(Path(urlparse(original_uri).path).name or "dependency")
    return f"external/{sha256_of_uri(original_uri)}/{basename}"
