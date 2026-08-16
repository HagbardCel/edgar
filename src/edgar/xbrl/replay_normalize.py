"""Pure helpers for offline replay result normalization (ADR 0009).

Shared by :mod:`edgar.xbrl.replay` and semantic projection so one offline
worker load can feed both closure faithfulness and semantic extraction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from edgar.domain.bundle import FilingBundle, UriBinding
from edgar.xbrl.closure import LoadedDocument, ResolvedDocument
from edgar.xbrl.uri import normalize_uri


@dataclass(frozen=True)
class NormalizedReplayView:
    """Closure comparison inputs derived from a worker result + bindings."""

    load_completed: bool
    network_attempts: tuple[dict[str, Any], ...]
    unresolved_documents: tuple[str, ...]
    loaded_source_documents: tuple[LoadedDocument, ...]
    resolved_documents: tuple[ResolvedDocument, ...]
    expected_binding_documents: tuple[tuple[str, str], ...]
    diagnostics: tuple[str, ...]
    errors: tuple[str, ...]
    closure_equal: bool

    @property
    def replay_faithful(self) -> bool:
        return (
            self.load_completed
            and self.closure_equal
            and not self.network_attempts
            and not self.unresolved_documents
            and not self.errors
        )


def alias_to_primary_map(bindings: Sequence[UriBinding]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for binding in bindings:
        for alias in binding.replay_aliases:
            mapping[normalize_uri(alias)] = binding.document_uri
    return mapping


def normalize_replay_result(
    result: Mapping[str, Any],
    *,
    bindings: Sequence[UriBinding],
) -> NormalizedReplayView:
    """Derive closure equality and faithfulness from a worker result payload."""
    loaded = tuple(LoadedDocument.from_dict(d) for d in result.get("loaded_source_documents", []))
    resolved = tuple(ResolvedDocument.from_dict(d) for d in result.get("resolved_documents", []))
    diagnostics = list(result.get("diagnostics", []))

    alias_to_primary = alias_to_primary_map(bindings)
    expected = {(binding.document_uri, binding.content_sha256) for binding in bindings}
    observed: dict[str, str] = {d.document_uri: d.content_sha256 for d in resolved}
    for document in loaded:
        observed.setdefault(document.document_uri, document.content_sha256)
    actual = {(alias_to_primary.get(uri, uri), digest) for uri, digest in observed.items()}
    for document_uri, digest in sorted(actual - expected):
        diagnostics.append(f"loaded document is not a bundle binding: {document_uri} {digest}")
    for document_uri, digest in sorted(expected - actual):
        diagnostics.append(f"bound document was not loaded on replay: {document_uri} {digest}")

    return NormalizedReplayView(
        load_completed=bool(result.get("load_completed")),
        network_attempts=tuple(result.get("network_attempts", [])),
        unresolved_documents=tuple(result.get("unresolved_documents", [])),
        loaded_source_documents=loaded,
        resolved_documents=resolved,
        expected_binding_documents=tuple(sorted(expected)),
        diagnostics=tuple(diagnostics),
        errors=tuple(result.get("errors", [])),
        closure_equal=expected == actual,
    )


def normalize_replay_for_bundle(
    result: Mapping[str, Any],
    bundle: FilingBundle,
) -> NormalizedReplayView:
    return normalize_replay_result(result, bindings=bundle.uri_bindings)
