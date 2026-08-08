"""Parent-side offline replay validation for a published FilingBundle (ADR 0009).

Replay uses the same isolated worker as online closure discovery, but the only
resolvable inputs are the bundle's own ``UriBinding`` records and the content
objects they name. A replay is faithful when the loaded closure equals the
bound closure after alias normalization, with no network attempt and no
unresolved document.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from edgar.domain.bundle import FilingBundle
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import (
    DEFAULT_WORKER_TIMEOUT_SECONDS,
    LoadedDocument,
    ResolvedDocument,
    run_worker_process,
)
from edgar.xbrl.uri import normalize_uri


@dataclass(frozen=True)
class ReplayValidationResult:
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


def _deny_fetch(uri: str) -> dict[str, Any]:
    return {
        "type": "fetch_error",
        "uri": uri,
        "error": "offline replay does not permit parent fetches",
    }


def validate_offline_replay(
    bundle: FilingBundle,
    store: ObjectStore,
    *,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> ReplayValidationResult:
    """Replay the bundle's primary report input with networking denied."""
    report_input = bundle.report_inputs[0]
    job = {
        "mode": "offline",
        "report_input": report_input.to_dict(),
        "object_store_root": str(store.data_root),
        "uri_bindings": [binding.to_dict() for binding in bundle.uri_bindings],
    }
    run = run_worker_process(
        job,
        fetch_handler=_deny_fetch,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    )
    result = run.result

    loaded = tuple(LoadedDocument.from_dict(d) for d in result.get("loaded_source_documents", []))
    resolved = tuple(ResolvedDocument.from_dict(d) for d in result.get("resolved_documents", []))
    diagnostics = list(result.get("diagnostics", []))

    alias_to_primary: dict[str, str] = {}
    for binding in bundle.uri_bindings:
        for alias in binding.replay_aliases:
            alias_to_primary[normalize_uri(alias)] = binding.document_uri
    expected = {(binding.document_uri, binding.content_sha256) for binding in bundle.uri_bindings}
    observed: dict[str, str] = {d.document_uri: d.content_sha256 for d in resolved}
    for document in loaded:
        observed.setdefault(document.document_uri, document.content_sha256)
    actual = {(alias_to_primary.get(uri, uri), digest) for uri, digest in observed.items()}
    for document_uri, digest in sorted(actual - expected):
        diagnostics.append(f"loaded document is not a bundle binding: {document_uri} {digest}")
    for document_uri, digest in sorted(expected - actual):
        diagnostics.append(f"bound document was not loaded on replay: {document_uri} {digest}")

    return ReplayValidationResult(
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
