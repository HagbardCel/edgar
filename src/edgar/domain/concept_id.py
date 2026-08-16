"""Deterministic global concept identity (Phase 2B).

``concept.id`` is a UUIDv5 of the exact expanded QName so durable mapping
assertions can reference a regenerable source layer without opaque surrogates.
"""

from __future__ import annotations

from uuid import UUID, uuid5

# Frozen project namespace UUID. Never regenerate or derive at runtime.
# This constant is a Phase-2B compatibility contract.
EDGAR_CONCEPT_NAMESPACE_UUID = UUID("a7c4e2f1-9b3d-4e8a-b6c5-1d2e3f4a5b6c")


def clark_qname(namespace_uri: str, local_name: str) -> str:
    """Return Clark notation ``{namespace}local`` (prefix-independent identity)."""
    if not namespace_uri:
        raise ValueError("namespace_uri must be non-empty")
    if not local_name:
        raise ValueError("local_name must be non-empty")
    if "}" in namespace_uri:
        raise ValueError(f"namespace_uri must not contain '}}': {namespace_uri!r}")
    return "{" + namespace_uri + "}" + local_name


def concept_id(namespace_uri: str, local_name: str) -> UUID:
    """Stable UUIDv5 for an exact expanded QName."""
    return uuid5(EDGAR_CONCEPT_NAMESPACE_UUID, clark_qname(namespace_uri, local_name))


def concept_id_str(namespace_uri: str, local_name: str) -> str:
    """Stable concept id as a canonical UUID string."""
    return str(concept_id(namespace_uri, local_name))
