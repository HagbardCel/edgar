"""Parent-side offline Arelle semantic projection adapter (ADR 0008 / 0009).

Runs one isolated offline worker job with ``operation=semantic_projection``.
The same load produces closure/replay evidence and plain semantic records.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from edgar.domain.bundle import FilingBundle
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import DEFAULT_WORKER_TIMEOUT_SECONDS, run_worker_process
from edgar.xbrl.extract import semantic_status
from edgar.xbrl.records import SemanticIssueRecord, SemanticProjectionData
from edgar.xbrl.replay_normalize import NormalizedReplayView, normalize_replay_for_bundle


class SemanticWorkerError(RuntimeError):
    """Offline semantic worker failed before a coherent projection existed."""

    def __init__(
        self,
        message: str,
        *,
        replay: NormalizedReplayView,
        issues: tuple[SemanticIssueRecord, ...] = (),
        arelle_version: str | None = None,
    ) -> None:
        super().__init__(message)
        self.replay = replay
        self.issues = issues
        self.arelle_version = arelle_version


@dataclass(frozen=True)
class SemanticWorkerResult:
    data: SemanticProjectionData
    status: str  # complete | incomplete
    replay: NormalizedReplayView
    arelle_version: str
    raw_result: dict[str, Any]


def _deny_fetch(uri: str) -> dict[str, Any]:
    return {
        "type": "fetch_error",
        "uri": uri,
        "error": "offline semantic projection does not permit parent fetches",
    }


def run_offline_semantic_projection(
    bundle: FilingBundle,
    store: ObjectStore,
    *,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> SemanticWorkerResult:
    """Load the primary report offline and return validated semantic records."""
    report_input = bundle.report_inputs[0]
    job = {
        "mode": "offline",
        "operation": "semantic_projection",
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
    replay = normalize_replay_for_bundle(result, bundle)
    arelle_version = str(result.get("engine_version") or "") or None

    if not replay.replay_faithful:
        raise SemanticWorkerError(
            "offline semantic projection is not replay-faithful",
            replay=replay,
            arelle_version=arelle_version,
            issues=(
                SemanticIssueRecord(
                    severity="fatal",
                    code="REPLAY_NOT_FAITHFUL",
                    message="load completed / closure / network / unresolved checks failed",
                    context={
                        "load_completed": replay.load_completed,
                        "closure_equal": replay.closure_equal,
                        "network_attempts": len(replay.network_attempts),
                        "unresolved_documents": list(replay.unresolved_documents),
                        "errors": list(replay.errors),
                    },
                ),
            ),
        )

    extraction_errors = tuple(result.get("semantic_extraction_errors") or ())
    payload = result.get("semantic_payload")
    if extraction_errors or not isinstance(payload, dict) or payload.get("extraction_failed"):
        issues: list[SemanticIssueRecord] = []
        if isinstance(payload, dict) and payload.get("issues"):
            for raw in payload["issues"]:
                issues.append(SemanticIssueRecord.from_dict(raw))
        if not issues:
            issues.append(
                SemanticIssueRecord(
                    severity="fatal",
                    code="SEMANTIC_EXTRACTION_FAILED",
                    message="; ".join(extraction_errors) or "semantic payload missing",
                )
            )
        raise SemanticWorkerError(
            "semantic extraction failed",
            replay=replay,
            issues=tuple(issues),
            arelle_version=arelle_version,
        )

    data = SemanticProjectionData.from_dict(payload)
    return SemanticWorkerResult(
        data=data,
        status=semantic_status(data),
        replay=replay,
        arelle_version=str(arelle_version or data.engine_version),
        raw_result=dict(result),
    )
