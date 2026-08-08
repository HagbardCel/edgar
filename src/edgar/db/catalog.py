"""SQL adapter: persist and reconstruct FilingBundles (caller owns the transaction)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from edgar.db import schema as tables
from edgar.domain.bundle import (
    ARTIFACT_KINDS,
    ArtifactKind,
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    IxdsReportInput,
    UriBinding,
    XbrlReportInput,
    bundles_equivalent,
)
from edgar.domain.decode import BundleDecodeError
from edgar.domain.validation import BundleStructureError, validate_bundle_structure


class CatalogConflict(RuntimeError):
    """Persisted catalog state conflicts with the incoming FilingBundle."""


@dataclass(frozen=True)
class CatalogResult:
    filing_id: int
    bundle_id: int
    opaque_id: str
    accession: str
    reused: bool


def catalog_bundle(conn: Connection, bundle: FilingBundle, opaque_id: str) -> CatalogResult:
    """Insert or verify-reuse one FilingBundle. Does not commit."""
    issuer_id = _upsert_issuer(conn, bundle.filing.cik)
    filing_id = _upsert_filing(conn, issuer_id, bundle.filing)
    content_ids = _upsert_content_objects(conn, bundle)
    existing_id = _select_bundle_id(conn, filing_id, opaque_id)
    if existing_id is not None:
        loaded = load_bundle(conn, existing_id)
        if not bundles_equivalent(bundle, loaded):
            raise CatalogConflict(
                f"filing_bundle filing_id={filing_id} opaque_id={opaque_id} "
                "exists but reconstructed state is not equivalent"
            )
        return CatalogResult(
            filing_id=filing_id,
            bundle_id=existing_id,
            opaque_id=opaque_id,
            accession=bundle.filing.accession,
            reused=True,
        )

    stmt = (
        insert(tables.filing_bundle)
        .values(
            filing_id=filing_id,
            opaque_id=opaque_id,
            schema_version=bundle.schema_version,
            acquisition_policy_version=bundle.acquisition_policy_version,
            payload_hash=bundle.payload_hash,
        )
        .on_conflict_do_nothing(index_elements=["filing_id", "opaque_id"])
        .returning(tables.filing_bundle.c.id)
    )
    inserted = conn.execute(stmt).scalar_one_or_none()
    if inserted is None:
        # Concurrent insert won; verify reuse.
        bundle_id = _select_bundle_id(conn, filing_id, opaque_id)
        if bundle_id is None:
            raise CatalogConflict("filing_bundle insert raced and row is missing")
        loaded = load_bundle(conn, bundle_id)
        if not bundles_equivalent(bundle, loaded):
            raise CatalogConflict(
                f"filing_bundle filing_id={filing_id} opaque_id={opaque_id} "
                "exists but reconstructed state is not equivalent"
            )
        return CatalogResult(
            filing_id=filing_id,
            bundle_id=bundle_id,
            opaque_id=opaque_id,
            accession=bundle.filing.accession,
            reused=True,
        )

    bundle_id = int(inserted)
    artifact_ids = _insert_artifacts(conn, bundle_id, bundle, content_ids)
    binding_ids = _insert_uri_bindings(conn, bundle_id, bundle, artifact_ids)
    _insert_report_inputs(conn, bundle_id, bundle, binding_ids)

    loaded = load_bundle(conn, bundle_id)
    if not bundles_equivalent(bundle, loaded):
        raise CatalogConflict("catalog round-trip failed bundles_equivalent check")

    return CatalogResult(
        filing_id=filing_id,
        bundle_id=bundle_id,
        opaque_id=opaque_id,
        accession=bundle.filing.accession,
        reused=False,
    )


def load_bundle(conn: Connection, bundle_id: int) -> FilingBundle:
    """Reconstruct a FilingBundle from catalog rows.

    Existing rows must yield a structurally valid FilingBundle or CatalogConflict.
    Missing bundle_id raises LookupError.
    """
    row = (
        conn.execute(select(tables.filing_bundle).where(tables.filing_bundle.c.id == bundle_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError(f"filing_bundle id={bundle_id} not found")

    filing_row = (
        conn.execute(
            select(tables.filing, tables.issuer.c.cik)
            .join(tables.issuer, tables.issuer.c.id == tables.filing.c.issuer_id)
            .where(tables.filing.c.id == row["filing_id"])
        )
        .mappings()
        .one()
    )

    artifact_rows = (
        conn.execute(
            select(
                tables.bundle_artifact.c.id,
                tables.bundle_artifact.c.logical_path,
                tables.bundle_artifact.c.artifact_kind,
                tables.bundle_artifact.c.required,
                tables.content_object.c.sha256,
                tables.content_object.c.byte_size,
            )
            .join(
                tables.content_object,
                tables.content_object.c.id == tables.bundle_artifact.c.content_object_id,
            )
            .where(tables.bundle_artifact.c.filing_bundle_id == bundle_id)
            .order_by(tables.bundle_artifact.c.logical_path)
        )
        .mappings()
        .all()
    )

    binding_rows = (
        conn.execute(
            select(
                tables.bundle_uri_binding.c.id,
                tables.bundle_uri_binding.c.document_uri,
                tables.bundle_uri_binding.c.replay_aliases,
                tables.bundle_uri_binding.c.bundle_artifact_id,
                tables.bundle_artifact.c.logical_path,
                tables.content_object.c.sha256,
            )
            .join(
                tables.bundle_artifact,
                tables.bundle_artifact.c.id == tables.bundle_uri_binding.c.bundle_artifact_id,
            )
            .join(
                tables.content_object,
                tables.content_object.c.id == tables.bundle_artifact.c.content_object_id,
            )
            .where(tables.bundle_uri_binding.c.filing_bundle_id == bundle_id)
            .order_by(tables.bundle_uri_binding.c.document_uri)
        )
        .mappings()
        .all()
    )

    report_rows = (
        conn.execute(
            select(tables.xbrl_report_input)
            .where(tables.xbrl_report_input.c.filing_bundle_id == bundle_id)
            .order_by(tables.xbrl_report_input.c.ordinal)
        )
        .mappings()
        .all()
    )

    binding_id_to_uri = {int(b["id"]): str(b["document_uri"]) for b in binding_rows}

    try:
        accepted_at = filing_row["accepted_at"]
        if accepted_at is not None:
            accepted_at = cast(datetime, accepted_at).astimezone(UTC)

        filing = FilingIdentity(
            cik=str(filing_row["cik"]),
            accession=str(filing_row["accession_number"]),
            form_type=str(filing_row["form_type"]),
            filing_date=cast(date, filing_row["filing_date"]),
            accepted_at=accepted_at,
            report_period_end=cast(date | None, filing_row["report_period_end"]),
            primary_document=str(filing_row["primary_document"]),
        )

        artifacts: list[BundleArtifact] = []
        for a in artifact_rows:
            kind = str(a["artifact_kind"])
            if kind not in ARTIFACT_KINDS:
                raise ValueError(f"invalid artifact_kind: {kind!r}")
            artifacts.append(
                BundleArtifact(
                    logical_path=str(a["logical_path"]),
                    content=ContentObject(
                        sha256=str(a["sha256"]),
                        byte_size=int(a["byte_size"]),
                    ),
                    artifact_kind=cast(ArtifactKind, kind),
                    required=bool(a["required"]),
                )
            )

        uri_bindings: list[UriBinding] = []
        for b in binding_rows:
            aliases = b["replay_aliases"] or []
            uri_bindings.append(
                UriBinding(
                    document_uri=str(b["document_uri"]),
                    artifact_path=str(b["logical_path"]),
                    content_sha256=str(b["sha256"]),
                    replay_aliases=tuple(str(x) for x in aliases),
                )
            )

        report_inputs: list[XbrlReportInput] = []
        for ri in report_rows:
            members = (
                conn.execute(
                    select(tables.xbrl_report_input_member.c.bundle_uri_binding_id)
                    .where(tables.xbrl_report_input_member.c.report_input_id == ri["id"])
                    .order_by(tables.xbrl_report_input_member.c.ordinal)
                )
                .scalars()
                .all()
            )
            uris = tuple(binding_id_to_uri[int(mid)] for mid in members)
            kind = str(ri["kind"])
            if kind == "instance":
                report_inputs.append(InstanceReportInput(document_uris=uris))
            elif kind == "ixds":
                report_inputs.append(IxdsReportInput(document_uris=uris, target="default"))
            else:
                raise ValueError(f"unknown report input kind: {kind!r}")

        reconstructed = FilingBundle(
            filing=filing,
            payload_hash=str(row["payload_hash"]),
            artifacts=tuple(artifacts),
            report_inputs=tuple(report_inputs),
            uri_bindings=tuple(uri_bindings),
            schema_version=int(row["schema_version"]),
            acquisition_policy_version=str(row["acquisition_policy_version"]),
        )
        validate_bundle_structure(reconstructed)
    except (ValueError, BundleStructureError, BundleDecodeError, KeyError, TypeError) as exc:
        raise CatalogConflict("invalid persisted FilingBundle state") from exc

    return reconstructed


def _upsert_issuer(conn: Connection, cik: str) -> int:
    conn.execute(
        insert(tables.issuer).values(cik=cik).on_conflict_do_nothing(index_elements=["cik"])
    )
    issuer_id = conn.execute(
        select(tables.issuer.c.id).where(tables.issuer.c.cik == cik)
    ).scalar_one()
    return int(issuer_id)


def _filing_comparable(filing: FilingIdentity) -> dict[str, Any]:
    accepted = filing.accepted_at.astimezone(UTC) if filing.accepted_at is not None else None
    return {
        "accession_number": filing.accession,
        "form_type": filing.form_type,
        "filing_date": filing.filing_date,
        "accepted_at": accepted,
        "report_period_end": filing.report_period_end,
        "primary_document": filing.primary_document,
    }


def _upsert_filing(conn: Connection, issuer_id: int, filing: FilingIdentity) -> int:
    values = {
        "issuer_id": issuer_id,
        **_filing_comparable(filing),
    }
    conn.execute(
        insert(tables.filing)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["accession_number"])
    )
    row = (
        conn.execute(
            select(tables.filing).where(tables.filing.c.accession_number == filing.accession)
        )
        .mappings()
        .one()
    )

    existing_accepted = row["accepted_at"]
    if existing_accepted is not None:
        existing_accepted = cast(datetime, existing_accepted).astimezone(UTC)
    existing = {
        "accession_number": row["accession_number"],
        "form_type": row["form_type"],
        "filing_date": row["filing_date"],
        "accepted_at": existing_accepted,
        "report_period_end": row["report_period_end"],
        "primary_document": row["primary_document"],
    }
    expected = _filing_comparable(filing)
    if existing != expected or int(row["issuer_id"]) != issuer_id:
        # Also catch CIK mismatch via issuer_id.
        issuer_cik = conn.execute(
            select(tables.issuer.c.cik).where(tables.issuer.c.id == row["issuer_id"])
        ).scalar_one()
        if str(issuer_cik) != filing.cik or existing != expected:
            raise CatalogConflict(f"filing {filing.accession} exists with incompatible metadata")
    return int(row["id"])


def _upsert_content_objects(conn: Connection, bundle: FilingBundle) -> dict[str, int]:
    ids: dict[str, int] = {}
    seen: dict[str, int] = {}
    for artifact in bundle.artifacts:
        sha = artifact.content.sha256
        size = artifact.content.byte_size
        if sha in seen:
            if seen[sha] != size:
                raise CatalogConflict(f"content_object {sha} has conflicting byte_size in bundle")
            continue
        seen[sha] = size
        conn.execute(
            insert(tables.content_object)
            .values(sha256=sha, byte_size=size)
            .on_conflict_do_nothing(index_elements=["sha256"])
        )
        row = (
            conn.execute(select(tables.content_object).where(tables.content_object.c.sha256 == sha))
            .mappings()
            .one()
        )
        if int(row["byte_size"]) != size:
            raise CatalogConflict(
                f"content_object {sha} exists with byte_size={row['byte_size']}, incoming={size}"
            )
        ids[sha] = int(row["id"])
    return ids


def _select_bundle_id(conn: Connection, filing_id: int, opaque_id: str) -> int | None:
    value = conn.execute(
        select(tables.filing_bundle.c.id).where(
            tables.filing_bundle.c.filing_id == filing_id,
            tables.filing_bundle.c.opaque_id == opaque_id,
        )
    ).scalar_one_or_none()
    return int(value) if value is not None else None


def _insert_artifacts(
    conn: Connection,
    bundle_id: int,
    bundle: FilingBundle,
    content_ids: dict[str, int],
) -> dict[str, int]:
    """Return map logical_path -> artifact id."""
    path_to_id: dict[str, int] = {}
    for artifact in bundle.artifacts:
        result = conn.execute(
            insert(tables.bundle_artifact)
            .values(
                filing_bundle_id=bundle_id,
                logical_path=artifact.logical_path,
                content_object_id=content_ids[artifact.content.sha256],
                artifact_kind=artifact.artifact_kind,
                required=artifact.required,
            )
            .returning(tables.bundle_artifact.c.id)
        )
        path_to_id[artifact.logical_path] = int(result.scalar_one())
    return path_to_id


def _insert_uri_bindings(
    conn: Connection,
    bundle_id: int,
    bundle: FilingBundle,
    artifact_ids: dict[str, int],
) -> dict[str, int]:
    """Return map document_uri -> binding id. Verify SHA via artifact join path."""
    uri_to_id: dict[str, int] = {}
    for binding in bundle.uri_bindings:
        artifact_id = artifact_ids.get(binding.artifact_path)
        if artifact_id is None:
            raise CatalogConflict(
                f"URI binding artifact_path missing from artifacts: {binding.artifact_path}"
            )
        # Verify content SHA matches the artifact's content object.
        sha = conn.execute(
            select(tables.content_object.c.sha256)
            .join(
                tables.bundle_artifact,
                tables.bundle_artifact.c.content_object_id == tables.content_object.c.id,
            )
            .where(tables.bundle_artifact.c.id == artifact_id)
        ).scalar_one()
        if str(sha) != binding.content_sha256:
            raise CatalogConflict(f"URI binding content_sha256 mismatch for {binding.document_uri}")
        result = conn.execute(
            insert(tables.bundle_uri_binding)
            .values(
                filing_bundle_id=bundle_id,
                bundle_artifact_id=artifact_id,
                document_uri=binding.document_uri,
                replay_aliases=list(binding.replay_aliases),
            )
            .returning(tables.bundle_uri_binding.c.id)
        )
        uri_to_id[binding.document_uri] = int(result.scalar_one())
    return uri_to_id


def _insert_report_inputs(
    conn: Connection,
    bundle_id: int,
    bundle: FilingBundle,
    binding_ids: dict[str, int],
) -> None:
    for ordinal, report in enumerate(bundle.report_inputs):
        if isinstance(report, InstanceReportInput):
            kind = "instance"
            target = None
        elif isinstance(report, IxdsReportInput):
            kind = "ixds"
            target = "default"
        else:
            raise CatalogConflict(f"unsupported report input type: {type(report)!r}")

        report_id = conn.execute(
            insert(tables.xbrl_report_input)
            .values(
                filing_bundle_id=bundle_id,
                ordinal=ordinal,
                kind=kind,
                target=target,
            )
            .returning(tables.xbrl_report_input.c.id)
        ).scalar_one()

        for member_ordinal, uri in enumerate(report.document_uris):
            binding_id = binding_ids.get(uri)
            if binding_id is None:
                raise CatalogConflict(f"report input URI has no binding: {uri}")
            conn.execute(
                insert(tables.xbrl_report_input_member).values(
                    report_input_id=int(report_id),
                    ordinal=member_ordinal,
                    bundle_uri_binding_id=binding_id,
                )
            )
