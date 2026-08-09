"""Form-specific regulatory section extraction over document blocks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from edgar.parsing.config import SECTION_EXTRACTOR_VERSION
from edgar.parsing.records import (
    DocumentBlockRecord,
    DocumentIssueRecord,
    FilingSectionRecord,
    ParsedDocument,
    SectionSignal,
)

# --- Persisted Phase-1 vocabulary ---------------------------------------------

PERSISTED_10K: tuple[str, ...] = (
    "part_1.item_1.business",
    "part_1.item_1a.risk_factors",
    "part_1.item_1b.unresolved_staff_comments",
    "part_1.item_1c.cybersecurity",
    "part_2.item_7.mda",
    "part_2.item_7a.market_risk",
    "part_2.item_8.financial_statements",
)

PERSISTED_10Q: tuple[str, ...] = (
    "part_1.item_1.financial_statements",
    "part_1.item_2.mda",
    "part_1.item_3.market_risk",
    "part_1.item_4.controls_and_procedures",
    "part_2.item_1.legal_proceedings",
    "part_2.item_1a.risk_factors",
)

# Boundary grammar keys (sentinels). Format: part_N.item_X
_BOUNDARY_10K: tuple[str, ...] = (
    "part_1.item_1",
    "part_1.item_1a",
    "part_1.item_1b",
    "part_1.item_1c",
    "part_1.item_2",
    "part_1.item_3",
    "part_1.item_4",
    "part_2.item_5",
    "part_2.item_6",
    "part_2.item_7",
    "part_2.item_7a",
    "part_2.item_8",
    "part_2.item_9",
    "part_2.item_9a",
    "part_2.item_9b",
    "part_2.item_9c",
    "part_3.item_10",
    "part_3.item_11",
    "part_3.item_12",
    "part_3.item_13",
    "part_3.item_14",
    "part_4.item_15",
    "part_4.item_16",
)

_BOUNDARY_10Q: tuple[str, ...] = (
    "part_1.item_1",
    "part_1.item_2",
    "part_1.item_3",
    "part_1.item_4",
    "part_2.item_1",
    "part_2.item_1a",
    "part_2.item_2",
    "part_2.item_3",
    "part_2.item_4",
    "part_2.item_5",
    "part_2.item_6",
)

_PERSISTED_TO_BOUNDARY: dict[str, str] = {
    "part_1.item_1.business": "part_1.item_1",
    "part_1.item_1a.risk_factors": "part_1.item_1a",
    "part_1.item_1b.unresolved_staff_comments": "part_1.item_1b",
    "part_1.item_1c.cybersecurity": "part_1.item_1c",
    "part_2.item_7.mda": "part_2.item_7",
    "part_2.item_7a.market_risk": "part_2.item_7a",
    "part_2.item_8.financial_statements": "part_2.item_8",
    "part_1.item_1.financial_statements": "part_1.item_1",
    "part_1.item_2.mda": "part_1.item_2",
    "part_1.item_3.market_risk": "part_1.item_3",
    "part_1.item_4.controls_and_procedures": "part_1.item_4",
    "part_2.item_1.legal_proceedings": "part_2.item_1",
    "part_2.item_1a.risk_factors": "part_2.item_1a",
}

_ITEM_RE = re.compile(r"(?i)\bitem\s+(\d+[a-z]?)\s*[.\-:—–)]*\s*(.*)$")
_PART_RE = re.compile(r"(?i)\bpart\s+([ivx]+)\b")
_SIGNATURE_RE = re.compile(r"(?i)^\s*signatures?\b")
_TOC_RE = re.compile(r"(?i)table\s+of\s+contents")
_PAGE_SUFFIX_RE = re.compile(r"(?i)\s+\d+\s*$")

_AMENDMENT_FORMS = frozenset({"10-K/A", "10-Q/A"})
_SCORE_GAP = 15  # ambiguity when best-second gap is at most this


@dataclass(frozen=True)
class _Candidate:
    boundary_key: str
    block_ordinal: int
    score: int
    toc_like: bool


def _base_form(form_type: str) -> str:
    form = form_type.strip().upper()
    if form in {"10-K", "10-K/A"}:
        return "10-K"
    if form in {"10-Q", "10-Q/A"}:
        return "10-Q"
    raise ValueError(f"unsupported form_type for document sections: {form_type!r}")


def _persisted_keys(form_type: str) -> tuple[str, ...]:
    return PERSISTED_10K if _base_form(form_type) == "10-K" else PERSISTED_10Q


def _boundary_keys(form_type: str) -> tuple[str, ...]:
    return _BOUNDARY_10K if _base_form(form_type) == "10-K" else _BOUNDARY_10Q


def _part_number(token: str) -> int | None:
    mapping = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
    return mapping.get(token.lower())


def _normalize_item_token(token: str) -> str:
    return token.lower()


_ITEM_GLOBAL_RE = re.compile(r"(?i)\bitem\s+(\d+[a-z]?)\s*[.\-:—–)]*")


def _match_item(text: str) -> tuple[str, str] | None:
    match = _ITEM_RE.search(text.strip())
    if not match:
        return None
    return _normalize_item_token(match.group(1)), (match.group(2) or "").strip()


def _match_all_items(text: str) -> list[str]:
    return [_normalize_item_token(m.group(1)) for m in _ITEM_GLOBAL_RE.finditer(text)]


def _nearest_part(
    ordinal: int,
    part_by_ordinal: Mapping[int, int],
) -> int | None:
    best: int | None = None
    best_ord = -1
    for part_ord, part_num in part_by_ordinal.items():
        if part_ord <= ordinal and part_ord >= best_ord:
            best_ord = part_ord
            best = part_num
    return best


def _signal_map(signals: Sequence[SectionSignal]) -> dict[int, SectionSignal]:
    return {signal.block_ordinal: signal for signal in signals}


def _toc_penalty(signal: SectionSignal | None, text: str, ordinal: int, block_count: int) -> int:
    penalty = 0
    if signal is not None:
        if (
            signal.internal_link_count >= 1
            and signal.total_text_chars > 0
            and signal.link_text_chars * 2 >= signal.total_text_chars
        ):
            penalty += 40
        if signal.internal_link_count >= 3:
            penalty += 25
    if _PAGE_SUFFIX_RE.search(text):
        penalty += 20
    if ordinal * 10 < block_count:  # very early
        penalty += 5
    return penalty


def _body_bonus(signal: SectionSignal | None) -> int:
    bonus = 0
    if signal is None:
        return bonus
    if signal.heading_level is not None:
        bonus += 25
    if signal.is_bold_like:
        bonus += 15
    if signal.anchor_id:
        bonus += 20
    return bonus


def _is_toc_cluster(
    candidates: Sequence[_Candidate],
    blocks: Sequence[DocumentBlockRecord],
    signals: Mapping[int, SectionSignal],
) -> set[int]:
    """Return ordinals that look like TOC entries (require TOC cue or link-heavy rows)."""
    if len(candidates) < 4:
        return set()
    by_ord = sorted(candidates, key=lambda c: c.block_ordinal)
    toc_ordinals: set[int] = set()
    for cand in by_ord:
        window = [c for c in by_ord if abs(c.block_ordinal - cand.block_ordinal) <= 30]
        if len(window) < 4:
            continue
        nearby_toc = False
        start = max(0, cand.block_ordinal - 15)
        end = min(len(blocks), cand.block_ordinal + 5)
        for block in blocks[start:end]:
            if block.text and _TOC_RE.search(block.text):
                nearby_toc = True
                break
        signal = signals.get(cand.block_ordinal)
        link_heavy = False
        if signal is not None and signal.total_text_chars > 0:
            link_heavy = (
                signal.internal_link_count >= 1
                and signal.link_text_chars * 2 >= signal.total_text_chars
            )
        # Density alone is insufficient — body Item sequences are also dense.
        if nearby_toc or link_heavy:
            for item in window:
                item_signal = signals.get(item.block_ordinal)
                item_link_heavy = False
                if item_signal is not None and item_signal.total_text_chars > 0:
                    item_link_heavy = (
                        item_signal.internal_link_count >= 1
                        and item_signal.link_text_chars * 2 >= item_signal.total_text_chars
                    )
                near = any(
                    b.text and _TOC_RE.search(b.text)
                    for b in blocks[
                        max(0, item.block_ordinal - 15) : min(len(blocks), item.block_ordinal + 3)
                    ]
                )
                if near or item_link_heavy:
                    toc_ordinals.add(item.block_ordinal)
    return toc_ordinals


def _default_part_for_item(form_type: str, item_token: str) -> int:
    """Infer Part from item token when Part headings are absent."""
    token = item_token.lower()
    if _base_form(form_type) == "10-Q":
        return 1
    # 10-K item → part mapping
    if token in {"1", "1a", "1b", "1c", "2", "3", "4"}:
        return 1
    if token in {"5", "6", "7", "7a", "8", "9", "9a", "9b", "9c"}:
        return 2
    if token in {"10", "11", "12", "13", "14"}:
        return 3
    if token in {"15", "16"}:
        return 4
    return 1


def _collect_candidates(
    parsed: ParsedDocument,
    form_type: str,
) -> tuple[list[_Candidate], dict[int, int], list[_Candidate]]:
    blocks = parsed.blocks
    signals = _signal_map(parsed.section_signals)
    boundary_set = set(_boundary_keys(form_type))
    part_by_ordinal: dict[int, int] = {}
    signature_candidates: list[_Candidate] = []
    raw: list[_Candidate] = []

    for block in blocks:
        text = block.text or ""
        signal = signals.get(block.ordinal)
        candidate_text = signal.normalized_candidate_text if signal else text.casefold()
        display = text or candidate_text

        part_match = _PART_RE.search(display)
        if part_match:
            part_num = _part_number(part_match.group(1))
            if part_num is not None:
                part_by_ordinal[block.ordinal] = part_num

        if _SIGNATURE_RE.match(display.strip()):
            score = (
                50 + _body_bonus(signal) - _toc_penalty(signal, display, block.ordinal, len(blocks))
            )
            signature_candidates.append(
                _Candidate(
                    boundary_key="terminal.signatures",
                    block_ordinal=block.ordinal,
                    score=score,
                    toc_like=False,
                )
            )

        item = _match_item(display)
        item_tokens = _match_all_items(display)
        if not item_tokens and item is not None:
            item_tokens = [item[0]]
        if not item_tokens:
            continue
        part = _nearest_part(block.ordinal, part_by_ordinal)
        for item_token in item_tokens:
            part_for_item = (
                part if part is not None else _default_part_for_item(form_type, item_token)
            )
            boundary_key = f"part_{part_for_item}.item_{item_token}"
            if boundary_key not in boundary_set:
                if _base_form(form_type) == "10-Q":
                    alt = 2 if part_for_item == 1 else 1
                    alt_key = f"part_{alt}.item_{item_token}"
                    if alt_key in boundary_set:
                        boundary_key = alt_key
                    else:
                        continue
                else:
                    continue
            score = (
                40 + _body_bonus(signal) - _toc_penalty(signal, display, block.ordinal, len(blocks))
            )
            if signal and signal.heading_level is not None:
                score += 5
            # Multiple items on one block: force ambiguity for range purposes.
            if len(item_tokens) > 1:
                score = min(score, 25)
            raw.append(
                _Candidate(
                    boundary_key=boundary_key,
                    block_ordinal=block.ordinal,
                    score=score,
                    toc_like=False,
                )
            )

    toc_ords = _is_toc_cluster(raw, blocks, signals)
    adjusted: list[_Candidate] = []
    for cand in raw:
        if cand.block_ordinal in toc_ords:
            adjusted.append(
                _Candidate(
                    boundary_key=cand.boundary_key,
                    block_ordinal=cand.block_ordinal,
                    score=cand.score - 60,
                    toc_like=True,
                )
            )
        else:
            adjusted.append(cand)

    sig_adj: list[_Candidate] = []
    for cand in signature_candidates:
        if cand.block_ordinal in toc_ords:
            sig_adj.append(
                _Candidate(
                    boundary_key=cand.boundary_key,
                    block_ordinal=cand.block_ordinal,
                    score=cand.score - 60,
                    toc_like=True,
                )
            )
        else:
            sig_adj.append(cand)

    return adjusted, part_by_ordinal, sig_adj


def _best_per_boundary(
    candidates: Sequence[_Candidate],
) -> dict[str, tuple[_Candidate, _Candidate | None]]:
    by_key: dict[str, list[_Candidate]] = {}
    for cand in candidates:
        by_key.setdefault(cand.boundary_key, []).append(cand)
    result: dict[str, tuple[_Candidate, _Candidate | None]] = {}
    for key, items in by_key.items():
        ordered = sorted(items, key=lambda c: (-c.score, c.block_ordinal))
        best = ordered[0]
        second = ordered[1] if len(ordered) > 1 else None
        result[key] = (best, second)
    return result


def _select_monotonic_path(
    boundary_order: Sequence[str],
    best_map: Mapping[str, tuple[_Candidate, _Candidate | None]],
) -> dict[str, _Candidate | None]:
    """Pick a monotonic increasing ordinal path; None means unresolved/ambiguous."""
    selected: dict[str, _Candidate | None] = {}
    last_ord = -1
    for key in boundary_order:
        pair = best_map.get(key)
        if pair is None:
            selected[key] = None
            continue
        best, second = pair
        if best.toc_like and best.score < 20:
            selected[key] = None
            continue
        if second is not None and (best.score - second.score) <= _SCORE_GAP:
            # Ambiguous for this boundary.
            selected[key] = None
            # Mark specially via score sentinel by storing None; caller inspects best_map.
            continue
        if best.block_ordinal <= last_ord:
            # Prefer next body candidate after last_ord if available.
            alternatives = [
                c
                for c in (best, second)
                if c is not None and c.block_ordinal > last_ord and not c.toc_like
            ]
            if not alternatives:
                selected[key] = None
                continue
            choice = max(alternatives, key=lambda c: c.score)
            selected[key] = choice
            last_ord = choice.block_ordinal
            continue
        selected[key] = best
        last_ord = best.block_ordinal
    return selected


def _resolve_terminal(
    signature_candidates: Sequence[_Candidate],
    last_body_ordinal: int,
) -> tuple[int | None, list[DocumentIssueRecord]]:
    issues: list[DocumentIssueRecord] = []
    bodyish = [
        c
        for c in signature_candidates
        if not c.toc_like and c.block_ordinal > last_body_ordinal and c.score >= 30
    ]
    if not bodyish:
        # Fall back to any non-toc after last body.
        bodyish = [
            c
            for c in signature_candidates
            if not c.toc_like and c.block_ordinal > last_body_ordinal
        ]
    if not bodyish:
        return None, issues
    ordered = sorted(bodyish, key=lambda c: (-c.score, c.block_ordinal))
    best = ordered[0]
    second = ordered[1] if len(ordered) > 1 else None
    if second is not None and (best.score - second.score) <= _SCORE_GAP:
        issues.append(
            DocumentIssueRecord(
                severity="warning",
                code="SECTION_BOUNDARY_UNRESOLVED",
                message="ambiguous SIGNATURE(S) terminal marker",
                context={
                    "boundary_role": "terminal",
                    "candidate_ordinals": [best.block_ordinal, second.block_ordinal],
                },
            )
        )
        return None, issues
    return best.block_ordinal, issues


def extract_filing_sections(
    parsed: ParsedDocument,
    *,
    form_type: str,
    extract_regulatory_sections: bool,
) -> tuple[list[FilingSectionRecord], list[DocumentIssueRecord], str, int | None]:
    """Extract regulatory sections.

    Returns (sections, issues, status, terminal_boundary_ordinal).
    Never mutates parsed.blocks.
    """
    if not extract_regulatory_sections:
        return [], [], "complete", None

    form = form_type.strip().upper()
    persisted = _persisted_keys(form)
    boundary_order = _boundary_keys(form)
    candidates, _parts, signature_candidates = _collect_candidates(parsed, form)
    best_map = _best_per_boundary(candidates)
    selected = _select_monotonic_path(boundary_order, best_map)

    # Fix 10-Q part assignment using selected monotonic path: re-score items that
    # appear after an explicit Part II boundary if needed is already handled via
    # nearest part during collection when Part headings exist.

    # Same-ordinal distinct boundary keys: cannot form ordinal ranges.
    ordinal_to_keys: dict[int, set[str]] = {}
    for key, pair in best_map.items():
        best, _second = pair
        if best.toc_like and best.score < 20:
            continue
        ordinal_to_keys.setdefault(best.block_ordinal, set()).add(key)
    collapsed_ordinals = {ord_ for ord_, keys in ordinal_to_keys.items() if len(keys) > 1}
    for key, cand in list(selected.items()):
        if cand is not None and cand.block_ordinal in collapsed_ordinals:
            selected[key] = None
    # Also clear unresolved keys whose only candidates sit on a collapsed ordinal.
    for key, pair in best_map.items():
        best, _second = pair
        if best.block_ordinal in collapsed_ordinals:
            selected[key] = None

    last_body = max((c.block_ordinal for c in selected.values() if c is not None), default=-1)
    terminal_ord, terminal_issues = _resolve_terminal(signature_candidates, last_body)

    issues: list[DocumentIssueRecord] = list(terminal_issues)
    status = "complete"
    sections: list[FilingSectionRecord] = []
    is_amendment = form in _AMENDMENT_FORMS

    # Precompute resolved boundary ordinals in grammar order.
    resolved_bounds: list[tuple[str, int]] = []
    for key in boundary_order:
        cand = selected.get(key)
        if cand is not None:
            resolved_bounds.append((key, cand.block_ordinal))

    def end_for(start_key: str, start_ord: int) -> tuple[int | None, dict[str, object]]:
        """Earliest later resolved boundary or terminal; None if unresolved."""
        later = [(k, o) for k, o in resolved_bounds if o > start_ord]
        first_later_ord = later[0][1] if later else None
        terminal_candidate = (
            terminal_ord if terminal_ord is not None and terminal_ord > start_ord else None
        )
        prospective_end = first_later_ord if first_later_ord is not None else terminal_candidate

        # Same-ordinal distinct boundaries cannot form a range.
        for key, ord_ in resolved_bounds:
            if key != start_key and ord_ == start_ord:
                return None, {
                    "section_key": start_key,
                    "boundary_role": "end",
                    "expected_after": start_key,
                    "candidate_ordinals": [start_ord],
                    "reason": "same_ordinal_collapse",
                }

        # Ambiguous intervening: close-scoring candidates that could fall inside.
        for key in boundary_order:
            if key == start_key:
                continue
            pair = best_map.get(key)
            if pair is None:
                continue
            best, second = pair
            if second is None or (best.score - second.score) > _SCORE_GAP:
                continue
            cand_ords = [best.block_ordinal, second.block_ordinal]
            if prospective_end is None:
                if any(o > start_ord for o in cand_ords):
                    return None, {
                        "section_key": start_key,
                        "boundary_role": "end",
                        "expected_after": start_key,
                        "candidate_ordinals": [o for o in cand_ords if o > start_ord],
                    }
                continue
            inside = [o for o in cand_ords if start_ord < o < prospective_end]
            # Also treat two candidates where the selected end itself is ambiguous.
            selected_cand = selected.get(key)
            if (
                selected_cand is not None
                and selected_cand.block_ordinal == prospective_end
                and any(start_ord < o <= prospective_end for o in cand_ords)
            ):
                return None, {
                    "section_key": start_key,
                    "boundary_role": "end",
                    "expected_after": start_key,
                    "candidate_ordinals": sorted({o for o in cand_ords if start_ord < o}),
                }
            if inside:
                return None, {
                    "section_key": start_key,
                    "boundary_role": "end",
                    "expected_after": start_key,
                    "candidate_ordinals": inside,
                }

        if first_later_ord is not None and terminal_candidate is not None:
            return min(first_later_ord, terminal_candidate), {}
        if first_later_ord is not None:
            return first_later_ord, {}
        if terminal_candidate is not None:
            return terminal_candidate, {}
        return None, {
            "section_key": start_key,
            "boundary_role": "end",
            "expected_after": start_key,
            "candidate_ordinals": [],
        }

    for section_key in persisted:
        boundary_key = _PERSISTED_TO_BOUNDARY[section_key]
        start_cand = selected.get(boundary_key)
        pair = best_map.get(boundary_key)

        if start_cand is None:
            # Distinguish missing vs ambiguous start.
            if pair is not None:
                best, second = pair
                if second is not None and (best.score - second.score) <= _SCORE_GAP:
                    issues.append(
                        DocumentIssueRecord(
                            severity="warning",
                            code="SECTION_AMBIGUOUS",
                            message=f"ambiguous start for {section_key}",
                            context={
                                "section_key": section_key,
                                "candidate_ordinals": [best.block_ordinal, second.block_ordinal],
                                "scores": [best.score, second.score],
                            },
                        )
                    )
                    status = "incomplete"
                elif best.toc_like:
                    issues.append(
                        DocumentIssueRecord(
                            severity="warning",
                            code="TOC_ONLY_SECTION_MATCH",
                            message=f"only TOC candidates for {section_key}",
                            context={
                                "section_key": section_key,
                                "candidate_ordinals": [best.block_ordinal],
                            },
                        )
                    )
                    status = "incomplete"
                else:
                    if not is_amendment:
                        issues.append(
                            DocumentIssueRecord(
                                severity="warning",
                                code="SECTION_NOT_FOUND",
                                message=(
                                    "The deterministic parser did not identify this "
                                    f"configured section: {section_key}"
                                ),
                                context={"section_key": section_key},
                            )
                        )
            else:
                if not is_amendment:
                    issues.append(
                        DocumentIssueRecord(
                            severity="warning",
                            code="SECTION_NOT_FOUND",
                            message=(
                                "The deterministic parser did not identify this "
                                f"configured section: {section_key}"
                            ),
                            context={"section_key": section_key},
                        )
                    )
            continue

        end_ord, end_ctx = end_for(boundary_key, start_cand.block_ordinal)
        if end_ord is None:
            issues.append(
                DocumentIssueRecord(
                    severity="warning",
                    code="SECTION_BOUNDARY_UNRESOLVED",
                    message=f"unresolved end boundary for {section_key}",
                    context=end_ctx or {"section_key": section_key, "boundary_role": "end"},
                )
            )
            status = "incomplete"
            continue

        if end_ord <= start_cand.block_ordinal:
            issues.append(
                DocumentIssueRecord(
                    severity="warning",
                    code="SECTION_BOUNDARY_UNRESOLVED",
                    message=f"same-ordinal or inverted range for {section_key}",
                    context={
                        "section_key": section_key,
                        "boundary_role": "end",
                        "candidate_ordinals": [start_cand.block_ordinal, end_ord],
                    },
                )
            )
            status = "incomplete"
            continue

        confidence = max(0, min(100, start_cand.score))
        sections.append(
            FilingSectionRecord(
                section_key=section_key,
                start_block_ordinal=start_cand.block_ordinal,
                end_block_ordinal_exclusive=end_ord,
                method=SECTION_EXTRACTOR_VERSION,
                confidence_score=confidence,
            )
        )

    return sections, issues, status, terminal_ord


__all__ = [
    "PERSISTED_10K",
    "PERSISTED_10Q",
    "extract_filing_sections",
]
