"""Application-level FilingBundle acquisition orchestration."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from edgar.config import Settings
from edgar.domain.bundle import (
    ACQUISITION_POLICY_VERSION,
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
)
from edgar.domain.identifiers import accession_archive_base, accession_to_cik, validate_accession
from edgar.domain.issues import QualityIssue
from edgar.domain.validation import validate_bundle_structure
from edgar.ingestion.payload import compute_payload_hash
from edgar.ingestion.report_input import UnsupportedReportInput, identify_report_input
from edgar.sec.accession import (
    classify_source_and_role,
    parse_index_html,
    parse_index_json,
    parse_sgml_documents,
    reconcile_sgml_inventory,
)
from edgar.sec.client import ControlledFetcher, FetchTrace
from edgar.sec.limits import (
    LogicalPathConflict,
    MaxBundleBytesExceeded,
    MaxFileBytesExceeded,
    MaxRedirectsExceeded,
    ResourceLimitExceeded,
)
from edgar.sec.ssrf import DestinationForbidden
from edgar.sec.submissions import lookup_accession_metadata
from edgar.storage.bundles import BundleRepository, PublishResult
from edgar.storage.objects import ObjectStore, SizeLimitExceeded, write_json_atomic
from edgar.xbrl.closure import run_online_closure
from edgar.xbrl.replay import validate_offline_replay
from edgar.xbrl.uri import normalize_uri


@dataclass
class AcquisitionResult:
    bundle: FilingBundle
    publish: PublishResult
    attempt_id: str
    attempt_path: Path
    issues: list[QualityIssue] = field(default_factory=list)
    replay_faithful: bool = False


@dataclass
class LogicalPayloadBudget:
    """Authoritative acquisition-owned logical payload byte accounting."""

    limit: int
    _members: dict[str, tuple[str, int]] = field(default_factory=dict)

    @property
    def committed(self) -> int:
        return sum(size for _sha, size in self._members.values())

    @property
    def remaining(self) -> int:
        return self.limit - self.committed

    def register(self, logical_path: str, sha256: str, byte_size: int) -> None:
        existing = self._members.get(logical_path)
        if existing is None:
            if byte_size > self.remaining:
                raise MaxBundleBytesExceeded(
                    f"MAX_BUNDLE_BYTES exceeded registering {logical_path}: "
                    f"{self.committed + byte_size} > {self.limit}"
                )
            self._members[logical_path] = (sha256, byte_size)
            return
        if existing == (sha256, byte_size):
            return
        raise LogicalPathConflict(
            f"logical path {logical_path} already registered with "
            f"{existing!r}, refusing {sha256!r}/{byte_size}"
        )


def _artifact_kind(role: str, source_class: str) -> str:
    mapping = {
        "complete_submission": "complete_submission",
        "primary_document": "primary_document",
        "taxonomy_schema": "taxonomy_schema",
        "linkbase": "linkbase",
        "index_json": "index_json",
        "index_html": "index_html",
        "index_headers": "index_headers",
        "attachment": "attachment",
        "sec_viewer_artifact": "sec_generated",
        "sec_generated_xbrl": "sec_generated",
        "xbrl_zip": "sec_generated",
        "image": "attachment",
    }
    if role in mapping:
        return mapping[role]
    if source_class.startswith("sec_"):
        return "sec_generated"
    return "other"


def _issue_from_safeguard(exc: BaseException) -> QualityIssue:
    if isinstance(exc, ResourceLimitExceeded):
        code = exc.code
    elif isinstance(exc, SizeLimitExceeded):
        code = MaxFileBytesExceeded.code
    elif isinstance(exc, DestinationForbidden):
        code = "DESTINATION_FORBIDDEN"
    else:
        code = "ACQUISITION_FAILURE"
    return QualityIssue(
        severity="fatal",
        code=code,
        message=str(exc),
        context={"exception_type": type(exc).__name__},
    )


class AcquisitionService:
    def __init__(
        self,
        settings: Settings,
        *,
        fetcher: ControlledFetcher | None = None,
        store: ObjectStore | None = None,
    ) -> None:
        self.settings = settings
        self.data_root = settings.edgar_data_root
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.store = store or ObjectStore(self.data_root)
        self._traces: list[FetchTrace] = []
        if fetcher is None:
            self.fetcher = ControlledFetcher(
                settings.require_user_agent(),
                min_interval_seconds=settings.sec_min_interval_seconds,
                max_redirects=settings.max_redirects,
                timeout_seconds=settings.sec_timeout_seconds,
                max_retries=settings.sec_max_retries,
                observation_sink=self._traces.append,
            )
            self._owns_fetcher = True
        else:
            self.fetcher = fetcher
            # Prefer caller-provided sink; still collect if fetcher has none.
            if getattr(fetcher, "observation_sink", None) is None:
                fetcher.observation_sink = self._traces.append  # type: ignore[attr-defined]
            self._owns_fetcher = False
        self.bundles = BundleRepository(self.data_root, self.store)

    def close(self) -> None:
        if self._owns_fetcher:
            self.fetcher.close()

    def __enter__(self) -> AcquisitionService:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def acquire(self, accession: str) -> AcquisitionResult:
        accession = validate_accession(accession)
        attempt_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        attempt_dir = self.data_root / "acquisition-attempts" / attempt_id
        attempt_dir.mkdir(parents=True)
        self._traces.clear()
        issues: list[QualityIssue] = []
        status = "failed"
        terminal_error: dict[str, str] | None = None
        result_payload: dict[str, Any] | None = None
        outcome: AcquisitionResult | None = None

        try:
            outcome = self._acquire_body(
                accession,
                attempt_id=attempt_id,
                issues=issues,
            )
            status = "success"
            result_payload = {
                "bundle_dir": str(outcome.publish.bundle_dir),
                "opaque_id": outcome.publish.opaque_id,
                "reused": outcome.publish.reused,
                "payload_hash": outcome.bundle.payload_hash,
            }
            return outcome
        except Exception as exc:
            if not any(i.severity == "fatal" for i in issues) and isinstance(
                exc,
                (
                    ResourceLimitExceeded,
                    SizeLimitExceeded,
                    DestinationForbidden,
                    MaxRedirectsExceeded,
                ),
            ):
                issues.append(_issue_from_safeguard(exc))
            terminal_error = {
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
            raise
        finally:
            observations = [t.to_observation_dict() for t in self._traces]
            attempt_path = self._write_attempt(
                attempt_dir,
                accession,
                observations,
                issues,
                status=status,
                terminal_error=terminal_error,
                result=result_payload,
            )
            if outcome is not None:
                outcome.attempt_path = attempt_path
                outcome.issues = list(issues)

    def _acquire_body(
        self,
        accession: str,
        *,
        attempt_id: str,
        issues: list[QualityIssue],
    ) -> AcquisitionResult:
        meta, meta_issues = lookup_accession_metadata(
            self.fetcher,
            self.store,
            accession,
            max_bytes=self.settings.max_file_bytes,
        )
        issues.extend(meta_issues)

        cik = meta.cik
        archive = accession_archive_base(cik, accession)
        budget = LogicalPayloadBudget(self.settings.max_bundle_bytes)
        artifacts: list[BundleArtifact] = []
        artifact_bytes: dict[str, bytes] = {}
        artifact_digests: dict[str, str] = {}

        def add_object(
            logical_path: str,
            obj_sha: str,
            byte_size: int,
            *,
            artifact_kind: str,
            required: bool,
        ) -> None:
            budget.register(logical_path, obj_sha, byte_size)
            if any(a.logical_path == logical_path for a in artifacts):
                return
            artifacts.append(
                BundleArtifact(
                    logical_path=logical_path,
                    content=ContentObject(sha256=obj_sha, byte_size=byte_size),
                    artifact_kind=artifact_kind,  # type: ignore[arg-type]
                    required=required,
                )
            )
            data = self.store.open_bytes(obj_sha)
            artifact_bytes[logical_path] = data
            artifact_digests[logical_path] = obj_sha

        def fetch_put(
            url: str,
            logical_path: str,
            *,
            artifact_kind: str,
            required: bool,
            optional_absence: bool = False,
        ) -> bool:
            """Fetch into CAS under the remaining budget. Return False if optional absence."""
            if any(a.logical_path == logical_path for a in artifacts):
                return True
            stream_limit = min(self.settings.max_file_bytes, budget.remaining)
            if stream_limit <= 0:
                raise MaxBundleBytesExceeded(f"no remaining payload budget for {logical_path}")
            try:
                _result, obj = self.fetcher.fetch_to_store(url, self.store, max_bytes=stream_limit)
            except SizeLimitExceeded as exc:
                if stream_limit < self.settings.max_file_bytes:
                    raise MaxBundleBytesExceeded(str(exc)) from exc
                raise MaxFileBytesExceeded(str(exc)) from exc
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if optional_absence and status_code == 404:
                    issues.append(
                        QualityIssue(
                            severity="warning",
                            code="OPTIONAL_ARTIFACT_MISSING",
                            message=f"optional artifact missing: {logical_path}",
                            context={"url": url, "status_code": status_code},
                        )
                    )
                    return False
                if not required and optional_absence:
                    issues.append(
                        QualityIssue(
                            severity="warning",
                            code="OPTIONAL_ARTIFACT_MISSING",
                            message=f"optional artifact unavailable: {logical_path}",
                            context={"url": url, "error": str(exc)},
                        )
                    )
                    return False
                raise
            except (
                MaxRedirectsExceeded,
                DestinationForbidden,
                MaxBundleBytesExceeded,
                MaxFileBytesExceeded,
                ResourceLimitExceeded,
            ):
                # Optionality never downgrades safeguards.
                raise
            except Exception as exc:
                if optional_absence and _is_absence_error(exc):
                    issues.append(
                        QualityIssue(
                            severity="warning",
                            code="OPTIONAL_ARTIFACT_MISSING",
                            message=f"optional artifact missing: {logical_path}",
                            context={"url": url, "error": str(exc)},
                        )
                    )
                    return False
                if required:
                    raise
                raise
            add_object(
                logical_path,
                obj.sha256,
                obj.byte_size,
                artifact_kind=artifact_kind,
                required=required,
            )
            return True

        # discovery.json (payload member; submissions JSON itself is not charged)
        discovery_bytes = (
            json.dumps(meta.discovery, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        if len(discovery_bytes) > min(self.settings.max_file_bytes, budget.remaining):
            raise MaxBundleBytesExceeded("discovery.json exceeds remaining payload budget")
        disc_obj = self.store.put_bytes(discovery_bytes)
        add_object(
            "metadata/discovery.json",
            disc_obj.sha256,
            disc_obj.byte_size,
            artifact_kind="discovery",
            required=True,
        )

        index_json_url = f"{archive}index.json"
        fetch_put(index_json_url, "metadata/index.json", artifact_kind="index_json", required=True)
        json_entries = parse_index_json(artifact_bytes["metadata/index.json"], archive)

        for name, logical, kind, required in (
            (f"{accession}-index.html", "metadata/index.html", "index_html", True),
            (f"{accession}-index.htm", "metadata/index.html", "index_html", False),
            (
                f"{accession}-index-headers.html",
                "metadata/index-headers.html",
                "index_headers",
                False,
            ),
        ):
            if any(a.logical_path == logical for a in artifacts):
                continue
            url = f"{archive}{name}"
            fetch_put(
                url,
                logical,
                artifact_kind=kind,
                required=required,
                optional_absence=not required,
            )

        html_rows = []
        if "metadata/index.html" in artifact_bytes:
            html_rows = parse_index_html(artifact_bytes["metadata/index.html"], archive)

        html_by_name = {r.name: r for r in html_rows}
        for entry in json_entries:
            name = entry.name
            logical = f"accession/{name}"
            if any(a.logical_path == logical for a in artifacts):
                continue
            row = html_by_name.get(name)
            source_class, role = classify_source_and_role(
                name,
                accession=accession,
                description=row.description if row else None,
                document_type=row.document_type if row else None,
            )
            required = source_class == "filer_submitted" or role == "complete_submission"
            optional_absence = source_class == "sec_generated_rendering"
            try:
                ok = fetch_put(
                    entry.url,
                    logical,
                    artifact_kind=_artifact_kind(role, source_class),
                    required=required,
                    optional_absence=optional_absence,
                )
            except Exception:
                if required:
                    raise
                raise
            if not ok and required:
                issues.append(
                    QualityIssue(
                        severity="fatal",
                        code="MISSING_FILER_SUBMITTED_ATTACHMENT",
                        message=f"required filer-submitted attachment missing: {name}",
                        context={"filename": name},
                    )
                )

        complete_name = f"{accession}.txt"
        complete_path = f"accession/{complete_name}"
        if complete_path not in artifact_bytes:
            issues.append(
                QualityIssue(
                    severity="fatal",
                    code="MISSING_COMPLETE_SUBMISSION",
                    message="complete submission text missing",
                    context={"expected": complete_path},
                )
            )
        primary_path = f"accession/{meta.primary_document}"
        if primary_path not in artifact_bytes:
            issues.append(
                QualityIssue(
                    severity="fatal",
                    code="MISSING_PRIMARY_DOCUMENT",
                    message="primary document missing from accession directory",
                    context={"expected": primary_path},
                )
            )
        if any(i.severity == "fatal" for i in issues):
            raise RuntimeError("fatal acquisition completeness issues")

        sgml_docs = parse_sgml_documents(artifact_bytes[complete_path])
        issues.extend(
            reconcile_sgml_inventory(
                accession=accession,
                directory_names={e.name for e in json_entries},
                html_rows=html_rows,
                sgml_docs=sgml_docs,
            )
        )
        if any(i.severity == "fatal" for i in issues):
            raise RuntimeError("fatal SGML reconciliation issues")

        try:
            report_input, ri_issues = identify_report_input(
                cik=cik,
                accession=accession,
                form_type=meta.form_type,
                primary_document=meta.primary_document,
                html_rows=html_rows,
                sgml_docs=sgml_docs,
                artifact_bytes=artifact_bytes,
                artifact_digests=artifact_digests,
            )
            issues.extend(ri_issues)
        except UnsupportedReportInput as exc:
            issues.append(
                QualityIssue(
                    severity="fatal",
                    code="UNSUPPORTED_REPORT_INPUT",
                    message=str(exc),
                )
            )
            raise

        accession_uri_map: dict[str, tuple[str, str]] = {}
        for logical, digest in artifact_digests.items():
            if not logical.startswith("accession/"):
                continue
            name = logical.split("/", 1)[1]
            uri = normalize_uri(f"{archive}{name}")
            accession_uri_map[uri] = (digest, logical)

        discovery = run_online_closure(
            report_input,
            accession_uri_map=accession_uri_map,
            store=self.store,
            fetcher=self.fetcher,
            max_file_bytes=self.settings.max_external_dependency_bytes,
            max_new_payload_bytes=budget.remaining,
            user_agent=self.settings.sec_user_agent or None,
        )
        if discovery.fatal_safeguard is not None:
            issues.append(_issue_from_safeguard(discovery.fatal_safeguard))
            raise discovery.fatal_safeguard

        if (
            not discovery.load_completed
            or discovery.errors
            or discovery.network_attempts
            or discovery.unresolved_documents
        ):
            issues.append(
                QualityIssue(
                    severity="fatal",
                    code="ONLINE_CLOSURE_FAILED",
                    message="online closure gate failed",
                    context={
                        "load_completed": discovery.load_completed,
                        "errors": list(discovery.errors),
                        "network_attempts": list(discovery.network_attempts),
                        "unresolved_documents": list(discovery.unresolved_documents),
                    },
                )
            )
            raise RuntimeError(
                f"online closure failed: load={discovery.load_completed} "
                f"errors={discovery.errors} network={discovery.network_attempts} "
                f"unresolved={discovery.unresolved_documents}"
            )

        for ext in discovery.external_documents:
            if any(a.logical_path == ext.artifact_path for a in artifacts):
                budget.register(ext.artifact_path, ext.content_sha256, ext.byte_size)
                continue
            if not self.store.exists(ext.content_sha256):
                raise RuntimeError(f"missing external CAS object {ext.content_sha256}")
            add_object(
                ext.artifact_path,
                ext.content_sha256,
                ext.byte_size,
                artifact_kind="external",
                required=True,
            )

        filing = FilingIdentity(
            cik=cik,
            accession=accession,
            form_type=meta.form_type,
            filing_date=meta.filing_date,
            accepted_at=meta.accepted_at,
            report_period_end=meta.report_period_end,
            primary_document=meta.primary_document,
        )
        artifact_tuple = tuple(sorted(artifacts, key=lambda a: a.logical_path.encode("utf-8")))
        bundle = FilingBundle(
            filing=filing,
            payload_hash=compute_payload_hash(artifact_tuple),
            artifacts=artifact_tuple,
            report_inputs=(report_input,),
            uri_bindings=tuple(discovery.uri_bindings),
            acquisition_policy_version=ACQUISITION_POLICY_VERSION,
        )

        validate_bundle_structure(bundle)
        replay = validate_offline_replay(bundle, self.store)
        if not replay.replay_faithful:
            raise RuntimeError(
                "offline replay failed: "
                f"load={replay.load_completed} equal={replay.closure_equal} "
                f"unresolved={replay.unresolved_documents} errors={replay.errors}"
            )

        publish = self.bundles.publish(bundle)
        return AcquisitionResult(
            bundle=bundle,
            publish=publish,
            attempt_id=attempt_id,
            attempt_path=Path(),  # filled by acquire() finally
            issues=issues,
            replay_faithful=True,
        )

    def _write_attempt(
        self,
        attempt_dir: Path,
        accession: str,
        observations: list[dict[str, Any]],
        issues: list[QualityIssue],
        *,
        status: str,
        terminal_error: dict[str, str] | None,
        result: dict[str, Any] | None,
    ) -> Path:
        path = attempt_dir / "result.json"
        payload: dict[str, Any] = {
            "attempt_id": attempt_dir.name,
            "accession": accession,
            "finished_at": datetime.now(UTC).isoformat(),
            "status": status,
            "observations": observations,
            "issues": [i.to_dict() for i in issues],
            "result": result,
            "cik": accession_to_cik(accession),
        }
        if terminal_error is not None:
            payload["terminal_error"] = terminal_error
        write_json_atomic(path, payload)
        return path


def _is_absence_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response is not None and exc.response.status_code == 404
    text = str(exc).lower()
    return "404" in text or "not found" in text
