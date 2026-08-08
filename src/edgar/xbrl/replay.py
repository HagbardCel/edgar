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
from edgar.xbrl.replay_normalize import normalize_replay_for_bundle


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
        "operation": "load",
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
    view = normalize_replay_for_bundle(run.result, bundle)
    return ReplayValidationResult(
        load_completed=view.load_completed,
        network_attempts=view.network_attempts,
        unresolved_documents=view.unresolved_documents,
        loaded_source_documents=view.loaded_source_documents,
        resolved_documents=view.resolved_documents,
        expected_binding_documents=view.expected_binding_documents,
        diagnostics=view.diagnostics,
        errors=view.errors,
        closure_equal=view.closure_equal,
    )
