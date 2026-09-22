"""Parent-side raw occurrence inventory (M1A-3)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import lxml.etree as etree

from edgar.domain.bundle import (
    FilingBundle,
    InstanceReportInput,
    IxdsReportInput,
    UriBinding,
)
from edgar.domain.report_key import report_key as compute_report_key
from edgar.domain.uri import normalize_uri
from edgar.storage.objects import ObjectStore
from edgar.xbrl.report_set import ReportSetError, assert_unique_report_keys, validate_outcome_keys
from edgar.xbrl.target_identity import (
    DefaultTarget,
    TargetIdentity,
    selected_target_for_report_input,
    target_identity_from_inline_attribute,
    target_identity_key,
)

UPSTREAM_INVENTORY_VERSION: Literal["upstream-v1"] = "upstream-v1"

XBRLI_NS = "http://www.xbrl.org/2003/instance"
IX_NS_2013 = "http://www.xbrl.org/2013/inlineXBRL"
IX_NS_2008 = "http://www.xbrl.org/2008/inlineXBRL"
INLINE_NS = frozenset({IX_NS_2013, IX_NS_2008})

CONTEXT_LOCAL = f"{{{XBRLI_NS}}}context"
UNIT_LOCAL = f"{{{XBRLI_NS}}}unit"
XBRL_ROOT = f"{{{XBRLI_NS}}}xbrl"


class UpstreamInventoryError(Exception):
    """Raw scanner could not produce inventory."""


@dataclass(frozen=True)
class UpstreamInventory:
    inventory_version: str = UPSTREAM_INVENTORY_VERSION
    raw_context_count: int = 0
    raw_unit_count: int = 0
    selected_target_item_count: int = 0
    alternate_target_item_counts: tuple[tuple[dict[str, Any], int], ...] = ()
    selected_context_refs: frozenset[str] = frozenset()
    selected_unit_refs: frozenset[str] = frozenset()
    alternate_context_refs: frozenset[str] = frozenset()
    alternate_unit_refs: frozenset[str] = frozenset()
    fraction_count: int = 0
    tuple_container_count: int = 0
    continuation_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "inventory_version": self.inventory_version,
            "raw_context_count": self.raw_context_count,
            "raw_unit_count": self.raw_unit_count,
            "selected_target_item_count": self.selected_target_item_count,
            "alternate_target_item_counts": list(self.alternate_target_item_counts),
            "selected_context_refs": sorted(self.selected_context_refs),
            "selected_unit_refs": sorted(self.selected_unit_refs),
            "alternate_context_refs": sorted(self.alternate_context_refs),
            "alternate_unit_refs": sorted(self.alternate_unit_refs),
            "fraction_count": self.fraction_count,
            "tuple_container_count": self.tuple_container_count,
            "continuation_count": self.continuation_count,
        }


@dataclass(frozen=True)
class InventorySuccess:
    report_key: str
    inventory: UpstreamInventory


@dataclass(frozen=True)
class InventoryFailure:
    report_key: str
    code: str
    message: str


InventoryOutcome = InventorySuccess | InventoryFailure


def _hermetic_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )


def _parse_document(data: bytes, *, logical_path: str) -> etree._Element:
    try:
        return etree.fromstring(data, parser=_hermetic_parser())
    except etree.XMLSyntaxError as exc:
        raise UpstreamInventoryError(f"XML parse failed for {logical_path}: {exc}") from exc


def _uri_to_logical_path(bindings: Sequence[UriBinding]) -> dict[str, str]:
    out: dict[str, str] = {}
    for binding in bindings:
        uri = normalize_uri(binding.document_uri)
        out[uri] = binding.artifact_path
        for alias in binding.replay_aliases:
            out[normalize_uri(alias)] = binding.artifact_path
    return out


def _load_member_bytes(
    bundle: FilingBundle,
    store: ObjectStore,
    uri: str,
    uri_paths: Mapping[str, str],
) -> tuple[str, bytes]:
    normalized = normalize_uri(uri)
    path = uri_paths.get(normalized)
    if path is None:
        raise UpstreamInventoryError(f"no bundle binding for document URI {uri!r}")
    digest = next(
        (a.content.sha256 for a in bundle.artifacts if a.logical_path == path),
        None,
    )
    if digest is None:
        raise UpstreamInventoryError(f"artifact missing for logical_path={path!r}")
    try:
        data = store.open_bytes(digest)
    except OSError as exc:
        raise UpstreamInventoryError(f"cannot read {path}: {exc}") from exc
    return path, data


def ixds_membership_key(report_input: IxdsReportInput) -> frozenset[str]:
    return frozenset(normalize_uri(u) for u in report_input.document_uris)


@dataclass
class _MembershipScan:
    raw_context_count: int = 0
    raw_unit_count: int = 0
    continuation_count: int = 0
    context_id_locs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    unit_id_locs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    elements_by_id: dict[str, list[tuple[str, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    item_counts_by_target: dict[tuple[str, str], int] = field(
        default_factory=lambda: defaultdict(int)
    )
    fraction_by_target: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    tuple_by_target: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    context_refs_by_target: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    unit_refs_by_target: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    continued_at_edges: list[tuple[str, str, str]] = field(default_factory=list)
    structural_error: str | None = None


def _local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rpartition("}")[2]
    return tag


def _inline_ns_for_root(root: etree._Element) -> str | None:
    for el in root.iter():
        ns = etree.QName(el).namespace
        if ns in INLINE_NS:
            return ns
    for _prefix, ns in root.nsmap.items():
        if ns in INLINE_NS:
            return ns
    return None


def _scan_inline_member(path: str, root: etree._Element, scan: _MembershipScan) -> None:
    ix_ns = _inline_ns_for_root(root)
    if ix_ns is None:
        return
    for ctx in root.iter(CONTEXT_LOCAL):
        cid = ctx.get("id")
        if cid:
            scan.raw_context_count += 1
            scan.context_id_locs.setdefault(cid, []).append((path, "context"))
    for unit in root.iter(UNIT_LOCAL):
        uid = unit.get("id")
        if uid:
            scan.raw_unit_count += 1
            scan.unit_id_locs.setdefault(uid, []).append((path, "unit"))
    for el in root.iter():
        local = _local_name(el.tag)
        if local == "continuation":
            cid = el.get("id")
            if cid:
                scan.continuation_count += 1
                scan.elements_by_id[cid].append((path, "continuation"))
            continued = el.get("continuedAt")
            if continued and cid:
                scan.continued_at_edges.append((path, cid, continued))
        if local in ("nonNumeric", "nonFraction", "fraction"):
            tid = target_identity_key(target_identity_from_inline_attribute(el.get("target")))
            scan.item_counts_by_target[tid] += 1
            if local == "fraction":
                scan.fraction_by_target[tid] += 1
            cref = el.get("contextRef")
            if cref:
                scan.context_refs_by_target[tid].add(cref)
            uref = el.get("unitRef")
            if uref:
                scan.unit_refs_by_target[tid].add(uref)
        if local == "tuple":
            tid = target_identity_key(target_identity_from_inline_attribute(el.get("target")))
            scan.tuple_by_target[tid] += 1


def _scan_instance_member(path: str, root: etree._Element, scan: _MembershipScan) -> None:
    if etree.QName(root).namespace != XBRLI_NS or _local_name(root.tag) != "xbrl":
        return
    for ctx in root.iter(CONTEXT_LOCAL):
        cid = ctx.get("id")
        if cid:
            scan.raw_context_count += 1
            scan.context_id_locs.setdefault(cid, []).append((path, "context"))
    for unit in root.iter(UNIT_LOCAL):
        uid = unit.get("id")
        if uid:
            scan.raw_unit_count += 1
            scan.unit_id_locs.setdefault(uid, []).append((path, "unit"))
    tid = target_identity_key(DefaultTarget())
    for el in root.iter():
        if el.get("contextRef") is not None:
            scan.item_counts_by_target[tid] += 1
            scan.context_refs_by_target[tid].add(el.get("contextRef") or "")
            uref = el.get("unitRef")
            if uref:
                scan.unit_refs_by_target[tid].add(uref)


def _check_id_collisions(scan: _MembershipScan) -> str | None:
    for cid, locs in scan.context_id_locs.items():
        if len(locs) > 1:
            a, b = locs[0], locs[1]
            return f"CONTEXT_ID_COLLISION id={cid!r} first={a!r} second={b!r}"
    for uid, locs in scan.unit_id_locs.items():
        if len(locs) > 1:
            a, b = locs[0], locs[1]
            return f"UNIT_ID_COLLISION id={uid!r} first={a!r} second={b!r}"
    return None


def _inventory_for_selected(
    scan: _MembershipScan,
    selected: TargetIdentity,
) -> UpstreamInventory | str:
    sel_key = target_identity_key(selected)
    err = _check_continuation_for_target(scan, sel_key)
    if err:
        return err
    alt_counts: list[tuple[dict[str, Any], int]] = []
    for key, count in sorted(scan.item_counts_by_target.items()):
        if key == sel_key:
            continue
        kind, name = key
        if kind == "default":
            alt_counts.append(({"kind": "default"}, count))
        else:
            alt_counts.append(({"kind": "named", "name": name}, count))
    return UpstreamInventory(
        raw_context_count=scan.raw_context_count,
        raw_unit_count=scan.raw_unit_count,
        selected_target_item_count=scan.item_counts_by_target.get(sel_key, 0),
        alternate_target_item_counts=tuple(alt_counts),
        selected_context_refs=frozenset(scan.context_refs_by_target.get(sel_key, set())),
        selected_unit_refs=frozenset(scan.unit_refs_by_target.get(sel_key, set())),
        alternate_context_refs=frozenset(
            ref
            for key, refs in scan.context_refs_by_target.items()
            if key != sel_key
            for ref in refs
        ),
        alternate_unit_refs=frozenset(
            ref
            for key, refs in scan.unit_refs_by_target.items()
            if key != sel_key
            for ref in refs
        ),
        fraction_count=scan.fraction_by_target.get(sel_key, 0),
        tuple_container_count=scan.tuple_by_target.get(sel_key, 0),
        continuation_count=scan.continuation_count,
    )


def _check_continuation_for_target(scan: _MembershipScan, sel_key: tuple[str, str]) -> str | None:
    fact_continued: set[str] = set()
    for _path, _from, to_ref in scan.continued_at_edges:
        fact_continued.add(to_ref)
    for ref in fact_continued:
        nodes = scan.elements_by_id.get(ref, [])
        if len(nodes) > 1:
            return f"CONTINUATION_AMBIGUOUS id={ref!r}"
        if len(nodes) == 0:
            return f"CONTINUATION_UNRESOLVED id={ref!r}"
    return None


def build_inventory_outcomes(
    bundle: FilingBundle,
    store: ObjectStore,
) -> tuple[InventoryOutcome, ...]:
    """Build one inventory outcome per report input before worker execution."""
    inputs = bundle.report_inputs
    keys = [compute_report_key(inp) for inp in inputs]
    assert_unique_report_keys(keys)
    expected = frozenset(keys)

    uri_paths = _uri_to_logical_path(bundle.uri_bindings)
    outcomes: list[InventoryOutcome] = []

    ixds_groups: dict[frozenset[str], list[IxdsReportInput]] = defaultdict(list)
    instance_inputs: list[tuple[str, InstanceReportInput]] = []

    for inp in inputs:
        key = compute_report_key(inp)
        if isinstance(inp, IxdsReportInput):
            ixds_groups[ixds_membership_key(inp)].append(inp)
        elif isinstance(inp, InstanceReportInput):
            instance_inputs.append((key, inp))

    for membership, group in ixds_groups.items():
        scan = _MembershipScan()
        try:
            for uri in sorted(membership):
                path, data = _load_member_bytes(bundle, store, uri, uri_paths)
                root = _parse_document(data, logical_path=path)
                _scan_inline_member(path, root, scan)
        except UpstreamInventoryError as exc:
            for inp in group:
                outcomes.append(
                    InventoryFailure(
                        report_key=compute_report_key(inp),
                        code="INVENTORY_SCAN_FAILED",
                        message=str(exc),
                    )
                )
            continue
        collision = _check_id_collisions(scan)
        if collision:
            for inp in group:
                outcomes.append(
                    InventoryFailure(
                        report_key=compute_report_key(inp),
                        code="CONTEXT_OR_UNIT_COLLISION",
                        message=collision,
                    )
                )
            continue
        for inp in group:
            key = compute_report_key(inp)
            selected = selected_target_for_report_input(domain_target=inp.target)
            inv_or_err = _inventory_for_selected(scan, selected)
            if isinstance(inv_or_err, str):
                outcomes.append(
                    InventoryFailure(
                        report_key=key,
                        code="CONTINUATION_INVALID",
                        message=inv_or_err,
                    )
                )
            else:
                outcomes.append(InventorySuccess(report_key=key, inventory=inv_or_err))

    for key, inp in instance_inputs:
        scan = _MembershipScan()
        try:
            uri = normalize_uri(inp.document_uris[0])
            path, data = _load_member_bytes(bundle, store, uri, uri_paths)
            root = _parse_document(data, logical_path=path)
            _scan_instance_member(path, root, scan)
        except UpstreamInventoryError as exc:
            outcomes.append(
                InventoryFailure(report_key=key, code="INVENTORY_SCAN_FAILED", message=str(exc))
            )
            continue
        collision = _check_id_collisions(scan)
        if collision:
            outcomes.append(
                InventoryFailure(
                    report_key=key, code="CONTEXT_OR_UNIT_COLLISION", message=collision
                )
            )
            continue
        inv_or_err = _inventory_for_selected(scan, DefaultTarget())
        if isinstance(inv_or_err, str):
            outcomes.append(
                InventoryFailure(report_key=key, code="CONTINUATION_INVALID", message=inv_or_err)
            )
        else:
            outcomes.append(InventorySuccess(report_key=key, inventory=inv_or_err))

    validate_outcome_keys(
        expected,
        outcomes,
        key_of=lambda o: o.report_key,
        label="inventory",
    )
    return tuple(outcomes)


def any_inventory_failure(outcomes: Sequence[InventoryOutcome]) -> bool:
    return any(isinstance(o, InventoryFailure) for o in outcomes)


def inventory_by_key(
    outcomes: Sequence[InventoryOutcome],
    expected_keys: frozenset[str],
) -> dict[str, UpstreamInventory]:
    mapped = validate_outcome_keys(
        expected_keys,
        outcomes,
        key_of=lambda o: o.report_key,
        label="inventory",
    )
    result: dict[str, UpstreamInventory] = {}
    for key, outcome in mapped.items():
        if isinstance(outcome, InventoryFailure):
            raise ReportSetError(f"inventory failed for {key!r}: {outcome.message}")
        result[key] = outcome.inventory
    return result
