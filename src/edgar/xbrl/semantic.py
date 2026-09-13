"""Parent-side offline Arelle extraction adapter (ADR 0009 / 0011).

Runs one isolated offline worker job with ``operation=extract``.
The same load produces closure/replay evidence and native ``ReportExtraction``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from edgar.domain.bundle import FilingBundle, XbrlReportInput
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import DEFAULT_WORKER_TIMEOUT_SECONDS, run_worker_process
from edgar.xbrl.records import SemanticIssueRecord
from edgar.xbrl.replay_normalize import NormalizedReplayView, normalize_replay_for_bundle
from edgar.xbrl.source_records import ReportExtraction
from edgar.xbrl.source_wire import SourceWireError, report_extraction_from_dict


class SourceExtractWorkerError(RuntimeError):
    """Offline source extraction worker failed before a coherent report existed."""

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


# Historical alias used by a few tests during remount.
SemanticWorkerError = SourceExtractWorkerError


@dataclass(frozen=True)
class OfflineExtractResult:
    report: ReportExtraction
    replay: NormalizedReplayView
    arelle_version: str
    raw_result: dict[str, Any]


def _deny_fetch(uri: str) -> dict[str, Any]:
    return {
        "type": "fetch_error",
        "uri": uri,
        "error": "offline source extraction does not permit parent fetches",
    }


def run_offline_extract(
    bundle: FilingBundle,
    store: ObjectStore,
    *,
    report_input: XbrlReportInput | dict[str, Any] | None = None,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> OfflineExtractResult:
    """Load one report offline and return native ``ReportExtraction``.

    Defaults to ``bundle.report_inputs[0]``. Pass ``report_input`` to select a
    specific report when the bundle carries more than one.
    """
    selected: XbrlReportInput | dict[str, Any]
    selected = report_input if report_input is not None else bundle.report_inputs[0]
    report_payload = dict(selected) if isinstance(selected, dict) else selected.to_dict()
    job = {
        "mode": "offline",
        "operation": "extract",
        "report_input": report_payload,
        "object_store_root": str(store.data_root),
        "uri_bindings": [binding.to_dict() for binding in bundle.uri_bindings],
    }
    try:
        run = run_worker_process(
            job,
            fetch_handler=_deny_fetch,
            python_executable=python_executable,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        raise SourceExtractWorkerError(
            f"source extraction worker process failed: {type(exc).__name__}: {exc}",
            replay=NormalizedReplayView(
                load_completed=False,
                network_attempts=(),
                unresolved_documents=(),
                loaded_source_documents=(),
                resolved_documents=(),
                expected_binding_documents=(),
                diagnostics=(),
                errors=(f"{type(exc).__name__}: {exc}",),
                closure_equal=False,
            ),
            issues=(
                SemanticIssueRecord(
                    severity="fatal",
                    code="SOURCE_EXTRACT_WORKER_PROCESS_FAILED",
                    message=(
                        f"source extraction worker process failed: {type(exc).__name__}: {exc}"
                    ),
                ),
            ),
            arelle_version=None,
        ) from exc
    result = run.result
    replay = normalize_replay_for_bundle(result, bundle)
    arelle_version = str(result.get("engine_version") or "") or None

    if not replay.replay_faithful:
        raise SourceExtractWorkerError(
            "offline source extraction is not replay-faithful",
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
    payload = result.get("extraction_payload")
    if extraction_errors or not isinstance(payload, dict) or payload.get("extraction_failed"):
        issues: list[SemanticIssueRecord] = []
        if isinstance(payload, dict) and payload.get("issues"):
            for raw in payload["issues"]:
                issues.append(SemanticIssueRecord.from_dict(raw))
        if not issues:
            issues.append(
                SemanticIssueRecord(
                    severity="fatal",
                    code="SOURCE_EXTRACTION_FAILED",
                    message="; ".join(extraction_errors) or "extraction payload missing",
                )
            )
        raise SourceExtractWorkerError(
            "source extraction failed",
            replay=replay,
            issues=tuple(issues),
            arelle_version=arelle_version,
        )

    try:
        report = report_extraction_from_dict(payload)
    except SourceWireError as exc:
        raise SourceExtractWorkerError(
            f"invalid extraction_payload: {exc}",
            replay=replay,
            issues=(
                SemanticIssueRecord(
                    severity="fatal",
                    code="SOURCE_EXTRACTION_PAYLOAD_INVALID",
                    message=str(exc),
                ),
            ),
            arelle_version=arelle_version,
        ) from exc

    return OfflineExtractResult(
        report=report,
        replay=replay,
        arelle_version=str(arelle_version or report.arelle_version),
        raw_result=dict(result),
    )
