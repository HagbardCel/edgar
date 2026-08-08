"""Application-level FilingBundle acquisition orchestration."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from edgar.ingestion.payload import compute_payload_hash
from edgar.ingestion.report_input import UnsupportedReportInput, identify_report_input
from edgar.sec.accession import (
    classify_source_and_role,
    parse_index_html,
    parse_index_json,
    parse_sgml_documents,
    reconcile_sgml_inventory,
)
from edgar.sec.client import ControlledFetcher
from edgar.sec.submissions import lookup_accession_metadata
from edgar.storage.bundles import BundleRepository, PublishResult
from edgar.storage.objects import ObjectStore, write_json_atomic
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
        self.fetcher = fetcher or ControlledFetcher(
            settings.require_user_agent(),
            min_interval_seconds=settings.sec_min_interval_seconds,
            max_redirects=settings.max_redirects,
            timeout_seconds=settings.sec_timeout_seconds,
            max_retries=settings.sec_max_retries,
        )
        self.bundles = BundleRepository(self.data_root, self.store)
        self._owns_fetcher = fetcher is None

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
        observations: list[dict[str, Any]] = []
        issues: list[QualityIssue] = []

        meta, meta_issues = lookup_accession_metadata(
            self.fetcher,
            self.store,
            accession,
            max_bytes=self.settings.max_file_bytes,
        )
        issues.extend(meta_issues)
        observations.append(
            {
                "kind": "submissions",
                "content_sha256": meta.submissions_content_sha256,
                "accession": accession,
            }
        )

        cik = meta.cik
        archive = accession_archive_base(cik, accession)
        payload_total = 0
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
            nonlocal payload_total
            payload_total += byte_size
            if payload_total > self.settings.max_bundle_bytes:
                raise RuntimeError(
                    f"MAX_BUNDLE_BYTES exceeded: {payload_total} > {self.settings.max_bundle_bytes}"
                )
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

        def fetch_put(url: str, logical_path: str, *, artifact_kind: str, required: bool) -> None:
            result, obj = self.fetcher.fetch_to_store(
                url, self.store, max_bytes=self.settings.max_file_bytes
            )
            observations.append(result.to_observation_dict())
            add_object(
                logical_path,
                obj.sha256,
                obj.byte_size,
                artifact_kind=artifact_kind,
                required=required,
            )

        # discovery.json (stable; no shard URL)
        discovery_bytes = (
            json.dumps(meta.discovery, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        disc_obj = self.store.put_bytes(discovery_bytes)
        add_object(
            "metadata/discovery.json",
            disc_obj.sha256,
            disc_obj.byte_size,
            artifact_kind="discovery",
            required=True,
        )

        # index.json — physical inventory
        index_json_url = f"{archive}index.json"
        fetch_put(index_json_url, "metadata/index.json", artifact_kind="index_json", required=True)
        json_entries = parse_index_json(artifact_bytes["metadata/index.json"], archive)

        # index HTML / headers
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
            try:
                fetch_put(url, logical, artifact_kind=kind, required=required)
            except Exception:
                if required:
                    raise

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
            fetch_put(
                entry.url,
                logical,
                artifact_kind=_artifact_kind(role, source_class),
                required=required,
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
            self._write_attempt(attempt_dir, accession, observations, issues, None)
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
            self._write_attempt(attempt_dir, accession, observations, issues, None)
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
            self._write_attempt(attempt_dir, accession, observations, issues, None)
            raise

        # Accession URI map for online closure (no re-fetch).
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
            user_agent=self.settings.sec_user_agent or None,
        )
        if not discovery.load_completed:
            self._write_attempt(attempt_dir, accession, observations, issues, None)
            raise RuntimeError(f"online closure failed: {discovery.errors}")

        # Capture external artifacts into payload.
        for binding in discovery.uri_bindings:
            if not binding.artifact_path.startswith("external/"):
                continue
            if any(a.logical_path == binding.artifact_path for a in artifacts):
                continue
            if not self.store.exists(binding.content_sha256):
                raise RuntimeError(f"missing external CAS object {binding.content_sha256}")
            data = self.store.open_bytes(binding.content_sha256)
            add_object(
                binding.artifact_path,
                binding.content_sha256,
                len(data),
                artifact_kind="external",
                required=True,
            )
            observations.append(
                {
                    "kind": "external_binding",
                    "document_uri": binding.document_uri,
                    "content_sha256": binding.content_sha256,
                    "artifact_path": binding.artifact_path,
                }
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

        replay = validate_offline_replay(bundle, self.store)
        if not replay.replay_faithful:
            self._write_attempt(attempt_dir, accession, observations, issues, None)
            raise RuntimeError(
                "offline replay failed: "
                f"load={replay.load_completed} equal={replay.closure_equal} "
                f"unresolved={replay.unresolved_documents} errors={replay.errors}"
            )

        publish = self.bundles.publish(bundle)
        attempt_path = self._write_attempt(
            attempt_dir,
            accession,
            observations,
            issues,
            {
                "bundle_dir": str(publish.bundle_dir),
                "opaque_id": publish.opaque_id,
                "reused": publish.reused,
                "payload_hash": bundle.payload_hash,
                "submissions_content_sha256": meta.submissions_content_sha256,
            },
        )
        return AcquisitionResult(
            bundle=bundle,
            publish=publish,
            attempt_id=attempt_id,
            attempt_path=attempt_path,
            issues=issues,
            replay_faithful=True,
        )

    def _write_attempt(
        self,
        attempt_dir: Path,
        accession: str,
        observations: list[dict[str, Any]],
        issues: list[QualityIssue],
        result: dict[str, Any] | None,
    ) -> Path:
        path = attempt_dir / "result.json"
        payload = {
            "attempt_id": attempt_dir.name,
            "accession": accession,
            "finished_at": datetime.now(UTC).isoformat(),
            "observations": observations,
            "issues": [i.to_dict() for i in issues],
            "result": result,
            "cik": accession_to_cik(accession),
        }
        write_json_atomic(path, payload)
        return path
