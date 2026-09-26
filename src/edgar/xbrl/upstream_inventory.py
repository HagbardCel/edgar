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


def _resolve_member_canonical_uri(
    uri: str,
    bindings: Sequence[UriBinding],
) -> str | None:
    normalized = normalize_uri(uri)
    canonicals: list[str] = []
    for binding in bindings:
        canonical = normalize_uri(binding.document_uri)
        aliases = {normalize_uri(alias) for alias in binding.replay_aliases}
        if normalized == canonical or normalized in aliases:
            canonicals.append(canonical)
    unique = frozenset(canonicals)
    if len(unique) > 1:
        return None
    if len(unique) == 1:
        return next(iter(unique))
    return None


def _ixds_membership_for_input(
    report_input: IxdsReportInput,
    bindings: Sequence[UriBinding],
) -> frozenset[str] | InventoryFailure:
    canonical_members: list[str] = []
    for uri in report_input.document_uris:
        canonical = _resolve_member_canonical_uri(uri, bindings)
        if canonical is None:
            return InventoryFailure(
                report_key=compute_report_key(report_input),
                code="IXDS_MEMBER_URI_AMBIGUOUS",
                message=f"ambiguous or unbound IXDS member URI {uri!r}",
            )
        canonical_members.append(canonical)
    if len(canonical_members) != len(set(canonical_members)):
        return InventoryFailure(
            report_key=compute_report_key(report_input),
            code="IXDS_DUPLICATE_CANONICAL_MEMBER",
            message="duplicate canonical IXDS member after URI binding resolution",
        )
    return frozenset(canonical_members)


def ixds_membership_key(
    report_input: IxdsReportInput,
    bindings: Sequence[UriBinding] | None = None,
) -> frozenset[str]:
    """Membership key for tests; requires bindings when replay aliases matter."""
    if bindings is None:
        return frozenset(normalize_uri(u) for u in report_input.document_uris)
    resolved = _ixds_membership_for_input(report_input, bindings)
    if isinstance(resolved, InventoryFailure):
        raise ValueError(resolved.message)
    return resolved


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
    item_continued_at: list[tuple[tuple[str, str], str]] = field(default_factory=list)
    footnote_continued_at: list[str] = field(default_factory=list)
    continuation_continued_at: dict[str, str] = field(default_factory=dict)
    instance_root_invalid: bool = False


def _local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rpartition("}")[2]
    return tag


def _inline_local_name(el: etree._Element) -> str | None:
    if not isinstance(el.tag, str):
        return None
    qname = etree.QName(el)
    if qname.namespace not in INLINE_NS:
        return None
    return qname.localname


def _element_path(root: etree._Element, el: etree._Element) -> str:
    return etree.ElementTree(root).getelementpath(el)


def _scan_inline_member(path: str, root: etree._Element, scan: _MembershipScan) -> None:
    for ctx in root.iter(CONTEXT_LOCAL):
        cid = ctx.get("id")
        if cid:
            scan.raw_context_count += 1
            scan.context_id_locs.setdefault(cid, []).append((path, _element_path(root, ctx)))
    for unit in root.iter(UNIT_LOCAL):
        uid = unit.get("id")
        if uid:
            scan.raw_unit_count += 1
            scan.unit_id_locs.setdefault(uid, []).append((path, _element_path(root, unit)))

    for el in root.iter():
        local = _inline_local_name(el)
        if local is None:
            continue
        if local == "continuation":
            cid = el.get("id")
            if cid:
                scan.continuation_count += 1
                scan.elements_by_id[cid].append((path, f"continuation:{cid}"))
                continued = el.get("continuedAt")
                if continued:
                    scan.continuation_continued_at[cid] = continued
            continue
        if local == "footnote":
            continued = el.get("continuedAt")
            if continued:
                scan.footnote_continued_at.append(continued)
            continue
        if local in ("nonNumeric", "nonFraction", "fraction"):
            tid = target_identity_key(target_identity_from_inline_attribute(el.get("target")))
            scan.item_counts_by_target[tid] += 1
            if local == "fraction":
                scan.fraction_by_target[tid] += 1
            continued = el.get("continuedAt")
            if continued:
                scan.item_continued_at.append((tid, continued))
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
    qname = etree.QName(root)
    if qname.namespace != XBRLI_NS or qname.localname != "xbrl":
        scan.instance_root_invalid = True
        return
    for ctx in root.iter(CONTEXT_LOCAL):
        cid = ctx.get("id")
        if cid:
            scan.raw_context_count += 1
            scan.context_id_locs.setdefault(cid, []).append((path, _element_path(root, ctx)))
    for unit in root.iter(UNIT_LOCAL):
        uid = unit.get("id")
        if uid:
            scan.raw_unit_count += 1
            scan.unit_id_locs.setdefault(uid, []).append((path, _element_path(root, unit)))
    tid = target_identity_key(DefaultTarget())
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.get("contextRef") is not None:
            scan.item_counts_by_target[tid] += 1
            scan.context_refs_by_target[tid].add(el.get("contextRef") or "")
            uref = el.get("unitRef")
            if uref:
                scan.unit_refs_by_target[tid].add(uref)


def _check_id_collisions(scan: _MembershipScan) -> InventoryFailure | None:
    for cid, locs in scan.context_id_locs.items():
        if len(locs) > 1:
            a, b = locs[0], locs[1]
            return InventoryFailure(
                report_key="",
                code="CONTEXT_ID_COLLISION",
                message=f"context id={cid!r} first={a!r} second={b!r}",
            )
    for uid, locs in scan.unit_id_locs.items():
        if len(locs) > 1:
            a, b = locs[0], locs[1]
            return InventoryFailure(
                report_key="",
                code="UNIT_ID_COLLISION",
                message=f"unit id={uid!r} first={a!r} second={b!r}",
            )
    return None


def _resolve_continuation_node(scan: _MembershipScan, ref: str) -> str | None:
    nodes = scan.elements_by_id.get(ref, [])
    if len(nodes) > 1:
        return "CONTINUATION_AMBIGUOUS"
    if len(nodes) == 0:
        return "CONTINUATION_UNRESOLVED"
    return None


def _walk_continuation_chain(
    scan: _MembershipScan,
    start_ref: str,
    *,
    max_steps: int,
) -> tuple[str | None, list[str]]:
    visited: set[str] = set()
    chain: list[str] = []
    current: str | None = start_ref
    steps = 0
    while current is not None and steps <= max_steps:
        err = _resolve_continuation_node(scan, current)
        if err is not None:
            return err, chain
        if current in visited:
            return "CONTINUATION_CYCLE", chain
        visited.add(current)
        chain.append(current)
        current = scan.continuation_continued_at.get(current)
        steps += 1
    if steps > max_steps:
        return "CONTINUATION_CYCLE", chain
    return None, chain


def _check_continuation_for_target(
    scan: _MembershipScan,
    sel_key: tuple[str, str],
) -> InventoryFailure | None:
    max_steps = max(scan.continuation_count, 1)
    root_starts: list[tuple[str, tuple[str, str] | None, str]] = []
    for tid_key, continued in scan.item_continued_at:
        root_starts.append(("item", tid_key, continued))
    for continued in scan.footnote_continued_at:
        root_starts.append(("footnote", None, continued))

    node_to_roots: dict[str, set[int]] = defaultdict(set)
    for root_index, (_kind, tid_key, start_ref) in enumerate(root_starts):
        err, chain = _walk_continuation_chain(scan, start_ref, max_steps=max_steps)
        if tid_key == sel_key and err is not None:
            return InventoryFailure(
                report_key="",
                code=err,
                message=f"continuation failure from selected target at {start_ref!r}",
            )
        for node in chain:
            node_to_roots[node].add(root_index)

    for node, roots in node_to_roots.items():
        if len(roots) < 2:
            continue
        has_selected_item = any(
            root_starts[i][0] == "item" and root_starts[i][1] == sel_key for i in roots
        )
        if has_selected_item:
            return InventoryFailure(
                report_key="",
                code="CONTINUATION_REUSE",
                message=f"continuation id {node!r} reused across chains",
            )
    return None


def _inventory_for_selected(
    scan: _MembershipScan,
    selected: TargetIdentity,
) -> UpstreamInventory | InventoryFailure:
    sel_key = target_identity_key(selected)
    if scan.fraction_by_target.get(sel_key, 0) > 0 or scan.tuple_by_target.get(sel_key, 0) > 0:
        return InventoryFailure(
            report_key="",
            code="UNSUPPORTED_INLINE_FRACTION_OR_TUPLE",
            message="selected target has inline fraction or tuple container",
        )
    cont_err = _check_continuation_for_target(scan, sel_key)
    if cont_err is not None:
        return cont_err
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
            ref for key, refs in scan.unit_refs_by_target.items() if key != sel_key for ref in refs
        ),
        fraction_count=scan.fraction_by_target.get(sel_key, 0),
        tuple_container_count=scan.tuple_by_target.get(sel_key, 0),
        continuation_count=scan.continuation_count,
    )


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
    ixds_failures: list[InventoryFailure] = []

    for inp in inputs:
        key = compute_report_key(inp)
        if isinstance(inp, IxdsReportInput):
            membership_or_fail = _ixds_membership_for_input(inp, bundle.uri_bindings)
            if isinstance(membership_or_fail, InventoryFailure):
                ixds_failures.append(
                    InventoryFailure(
                        report_key=key,
                        code=membership_or_fail.code,
                        message=membership_or_fail.message,
                    )
                )
            else:
                ixds_groups[membership_or_fail].append(inp)
        elif isinstance(inp, InstanceReportInput):
            instance_inputs.append((key, inp))

    outcomes.extend(ixds_failures)

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
        if collision is not None:
            for inp in group:
                outcomes.append(
                    InventoryFailure(
                        report_key=compute_report_key(inp),
                        code=collision.code,
                        message=collision.message,
                    )
                )
            continue
        for inp in group:
            key = compute_report_key(inp)
            selected = selected_target_for_report_input(domain_target=inp.target)
            inv_or_err = _inventory_for_selected(scan, selected)
            if isinstance(inv_or_err, InventoryFailure):
                outcomes.append(
                    InventoryFailure(
                        report_key=key,
                        code=inv_or_err.code,
                        message=inv_or_err.message,
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
        if scan.instance_root_invalid:
            outcomes.append(
                InventoryFailure(
                    report_key=key,
                    code="INSTANCE_ROOT_INVALID",
                    message="document root is not xbrli:xbrl",
                )
            )
            continue
        collision = _check_id_collisions(scan)
        if collision is not None:
            outcomes.append(
                InventoryFailure(
                    report_key=key,
                    code=collision.code,
                    message=collision.message,
                )
            )
            continue
        inv_or_err = _inventory_for_selected(scan, DefaultTarget())
        if isinstance(inv_or_err, InventoryFailure):
            outcomes.append(
                InventoryFailure(
                    report_key=key,
                    code=inv_or_err.code,
                    message=inv_or_err.message,
                )
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
