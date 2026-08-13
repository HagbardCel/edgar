"""Synthetic metric registry fixtures backed by projected XBRL evidence."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, select

from edgar.db import schema as tables
from edgar.db.semantic import load_semantic_projection
from edgar.metrics.registry import (
    ConceptDeclarationCitation,
    EvidenceSnapshot,
    ExpandedQNameRecord,
    FilingScope,
    GlobalScope,
    IssuerPeriodScope,
    MappingRuleRecord,
    SourceLocatorRecord,
    SupersedesRef,
)
from edgar.projection.semantic import ProjectPublishedBundleResult
from edgar.xbrl.config import SEMANTIC_PROJECTION_VERSION

_REPO_REGISTRY = Path(__file__).resolve().parents[2] / "semantic-registry"


def copy_registry_skeleton(dest: Path) -> None:
    """Copy Git registry files into ``dest`` (families + definitions; empty rules)."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("metric-families.json", "metric-definitions.json"):
        shutil.copy2(_REPO_REGISTRY / name, dest / name)
    (dest / "mapping-rules.json").write_text(
        json.dumps({"registry_schema_version": 1, "rules": []}, indent=2) + "\n",
        encoding="utf-8",
    )


def _projection_identity(
    conn: Connection,
    *,
    projection_id: int,
    bundle_opaque_id: str,
    accession: str,
) -> dict[str, Any]:
    row = (
        conn.execute(
            select(
                tables.semantic_projection.c.arelle_version,
                tables.semantic_projection.c.semantic_config_fingerprint,
                tables.xbrl_report_input.c.ordinal,
            )
            .select_from(
                tables.semantic_projection.join(
                    tables.xbrl_report_input,
                    tables.xbrl_report_input.c.id
                    == tables.semantic_projection.c.xbrl_report_input_id,
                )
            )
            .where(tables.semantic_projection.c.id == projection_id)
        )
        .mappings()
        .one()
    )
    return {
        "accession_number": accession,
        "filing_bundle_opaque_id": bundle_opaque_id,
        "xbrl_report_input_ordinal": int(row["ordinal"]),
        "projection_version": SEMANTIC_PROJECTION_VERSION,
        "arelle_version": str(row["arelle_version"]),
        "semantic_config_fingerprint": str(row["semantic_config_fingerprint"]),
    }


def concept_declaration_citation(
    conn: Connection,
    *,
    projection_id: int,
    bundle_opaque_id: str,
    accession: str,
    namespace_uri: str,
    local_name: str,
) -> ConceptDeclarationCitation:
    """Build a sync-resolvable concept declaration citation from persisted projection."""
    data, _arelle = load_semantic_projection(conn, projection_id)
    identity = _projection_identity(
        conn,
        projection_id=projection_id,
        bundle_opaque_id=bundle_opaque_id,
        accession=accession,
    )
    for decl in data.concept_declarations:
        if (
            decl.concept.namespace_uri == namespace_uri
            and decl.concept.local_name == local_name
        ):
            return ConceptDeclarationCitation(
                **identity,
                concept=ExpandedQNameRecord(
                    namespace_uri=decl.concept.namespace_uri,
                    local_name=decl.concept.local_name,
                ),
                source_locator=SourceLocatorRecord(
                    document_uri=decl.source_locator.document_uri,
                    scheme=decl.source_locator.scheme,
                    value=decl.source_locator.value,
                ),
            )
    raise LookupError(
        f"concept declaration not found in projection {projection_id}: "
        f"{{{namespace_uri}}}{local_name}"
    )


def _write_rules(dest: Path, rules: list[MappingRuleRecord]) -> None:
    payload = {
        "registry_schema_version": 1,
        "rules": [json.loads(r.model_dump_json()) for r in rules],
    }
    (dest / "mapping-rules.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_test_registry_with_projection_rule(
    dest: Path,
    *,
    conn: Connection,
    projection: ProjectPublishedBundleResult,
    bundle_opaque_id: str,
    accession: str,
    namespace_uri: str = "http://example.com/test",
    local_name: str = "Assets",
    rule_key: str = "map-test-assets-equivalent",
    target_metric_code: str = "cash_and_cash_equivalents",
    relationship_type: str = "equivalent",
) -> tuple[Path, str]:
    """Materialize a registry dir with one resolvable equivalent mapping rule."""
    copy_registry_skeleton(dest)
    citation = concept_declaration_citation(
        conn,
        projection_id=projection.projection.projection_id,
        bundle_opaque_id=bundle_opaque_id,
        accession=accession,
        namespace_uri=namespace_uri,
        local_name=local_name,
    )
    rule = MappingRuleRecord(
        rule_schema_version=1,
        rule_key=rule_key,
        source_concept=ExpandedQNameRecord(namespace_uri=namespace_uri, local_name=local_name),
        target_metric_code=target_metric_code,
        target_definition_version=1,
        relationship_type=relationship_type,  # type: ignore[arg-type]
        scope_kind="global",
        scope=GlobalScope(),
        confidence_tier="high",
        rationale=(
            "Synthetic acceptance fixture: minimal bundle Assets concept reviewed as "
            "cash proxy for integration testing only."
        ),
        evidence_snapshot=EvidenceSnapshot({"review": "synthetic fixture", "label": "Assets"}),
        evidence_citations=(citation,),
        reviewed_by="human-reviewer",
        reviewed_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
        supersedes=None,
    )
    _write_rules(dest, [rule])
    return dest, rule_key


def build_acceptance_registry(
    dest: Path,
    *,
    conn: Connection,
    projection: ProjectPublishedBundleResult,
    bundle_opaque_id: str,
    accession: str,
) -> Path:
    """Build synthetic A–F acceptance mapping rules for the rich semantic bundle."""
    copy_registry_skeleton(dest)
    rich_ns = "http://example.com/rich"
    pid = projection.projection.projection_id
    rules: list[MappingRuleRecord] = []
    reviewed_at = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)

    def add_rule(
        *,
        rule_key: str,
        local_name: str,
        target_metric_code: str,
        relationship_type: str,
        scope_kind: str,
        scope: GlobalScope | IssuerPeriodScope | FilingScope,
        rationale: str,
        supersedes: str | None = None,
        snapshot: dict[str, object] | None = None,
    ) -> None:
        citation = concept_declaration_citation(
            conn,
            projection_id=pid,
            bundle_opaque_id=bundle_opaque_id,
            accession=accession,
            namespace_uri=rich_ns,
            local_name=local_name,
        )
        rules.append(
            MappingRuleRecord(
                rule_schema_version=1,
                rule_key=rule_key,
                source_concept=ExpandedQNameRecord(namespace_uri=rich_ns, local_name=local_name),
                target_metric_code=target_metric_code,
                target_definition_version=1,
                relationship_type=relationship_type,  # type: ignore[arg-type]
                scope_kind=scope_kind,  # type: ignore[arg-type]
                scope=scope,
                confidence_tier="high",
                rationale=rationale,
                evidence_snapshot=EvidenceSnapshot(snapshot or {"case": rule_key}),
                evidence_citations=(citation,),
                reviewed_by="human-reviewer",
                reviewed_at=reviewed_at,
                supersedes=SupersedesRef(rule_key=supersedes) if supersedes else None,
            )
        )

    # A: global equivalent
    add_rule(
        rule_key="map-acc-a-equivalent",
        local_name="Assets",
        target_metric_code="cash_and_cash_equivalents",
        relationship_type="equivalent",
        scope_kind="global",
        scope=GlobalScope(),
        rationale="Case A: global standard-taxonomy equivalent for consolidated Assets.",
    )
    # B: issuer-period issuer_equivalent
    add_rule(
        rule_key="map-acc-b-issuer-equivalent",
        local_name="Liabilities",
        target_metric_code="long_term_debt_noncurrent",
        relationship_type="issuer_equivalent",
        scope_kind="issuer_period",
        scope=IssuerPeriodScope(
            cik="0000000001",
            report_period_from=date(2024, 1, 1),
            report_period_through=date(2024, 12, 31),
        ),
        rationale="Case B: issuer-period scoped issuer_equivalent for Liabilities.",
    )
    # C: incompatible (bank-like revenue proxy)
    add_rule(
        rule_key="map-acc-c-incompatible",
        local_name="Equity",
        target_metric_code="operating_company_revenue",
        relationship_type="incompatible",
        scope_kind="global",
        scope=GlobalScope(),
        rationale="Case C: incompatible — equity concept must not map to operating revenue.",
    )
    # D: component_of
    add_rule(
        rule_key="map-acc-d-component",
        local_name="Liabilities",
        target_metric_code="long_term_debt_noncurrent",
        relationship_type="component_of",
        scope_kind="global",
        scope=GlobalScope(),
        rationale="Case D: Liabilities component_of long-term debt (distinct from case B scope).",
    )
    # E: unresolved supersedes prior equivalent attempt on TextNote
    add_rule(
        rule_key="map-acc-e-equivalent-old",
        local_name="TextNote",
        target_metric_code="operating_company_revenue",
        relationship_type="equivalent",
        scope_kind="global",
        scope=GlobalScope(),
        rationale="Case E predecessor: abandoned equivalent attempt for TextNote.",
    )
    add_rule(
        rule_key="map-acc-e-unresolved",
        local_name="TextNote",
        target_metric_code="operating_company_revenue",
        relationship_type="unresolved",
        scope_kind="global",
        scope=GlobalScope(),
        rationale="Case E: reviewed abstention; prior equivalent fully retired.",
        supersedes="map-acc-e-equivalent-old",
    )
    # F uses Assets occurrences only (no extra rule needed beyond A)

    _write_rules(dest, rules)
    return dest
