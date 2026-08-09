"""Form-specific regulatory section extraction over document blocks."""

from __future__ import annotations

import math
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

# --- Anchored boundary markers ------------------------------------------------

_ANCHORED_ITEM_RE = re.compile(r"(?i)^\W*item\s+(\d+[a-z]?)\b")
_ANCHORED_PART_RE = re.compile(r"(?i)^\W*part\s+([ivx]+)\b")
_ITEM_GLOBAL_RE = re.compile(r"(?i)\bitem\s+(\d+[a-z]?)\s*[.\-:—–)]*")
_SIGNATURE_RE = re.compile(r"(?i)^\s*signatures?\b")
_TOC_RE = re.compile(r"(?i)table\s+of\s+contents")
_PAGE_SUFFIX_RE = re.compile(r"(?i)\s+\d+\s*$")

_AMENDMENT_FORMS = frozenset({"10-K/A", "10-Q/A"})

# --- Frozen sec-item-sequence-v2 scoring --------------------------------------

ITEM_BASE_SCORE = 40
PART_BASE_SCORE = 40
SIGNATURE_BASE_SCORE = 50

HEADING_BONUS = 25
BOLD_BONUS = 15
ANCHOR_BONUS = 20
SHORT_TEXT_MAX_CHARS = 160
SHORT_TEXT_BONUS = 10

TOC_LINK_HEAVY_PENALTY = 40
TOC_MANY_LINKS_PENALTY = 25
TOC_PAGE_SUFFIX_PENALTY = 20
TOC_EARLY_ORDINAL_PENALTY = 5
TOC_CLUSTER_PENALTY = 60

MULTI_ITEM_SCORE_CAP = 25

BODY_SELECTION_BASELINE = 30
SCORE_GAP = 15

_PART_I_10Q_ORDER: tuple[str, ...] = ("1", "2", "3", "4")
_NEG_INF = -math.inf


@dataclass(frozen=True)
class _Candidate:
    boundary_key: str
    block_ordinal: int
    score: int
    toc_like: bool
    item_token: str | None = None


@dataclass(frozen=True)
class _RawOccurrence:
    """Pre-TOC raw marker before Part assignment."""

    kind: str  # "part" | "item" | "terminal"
    block_ordinal: int
    score: int
    part_num: int | None = None
    item_tokens: tuple[str, ...] = ()


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


def _match_all_items(text: str) -> list[str]:
    return [_normalize_item_token(m.group(1)) for m in _ITEM_GLOBAL_RE.finditer(text)]


def _signal_map(signals: Sequence[SectionSignal]) -> dict[int, SectionSignal]:
    return {signal.block_ordinal: signal for signal in signals}


def _toc_penalty(signal: SectionSignal | None, text: str, ordinal: int, block_count: int) -> int:
    penalty = 0
    link_heavy = False
    if signal is not None:
        if (
            signal.internal_link_count >= 1
            and signal.total_text_chars > 0
            and signal.link_text_chars * 2 >= signal.total_text_chars
        ):
            penalty += TOC_LINK_HEAVY_PENALTY
            link_heavy = True
        if signal.internal_link_count >= 3:
            penalty += TOC_MANY_LINKS_PENALTY
    page_suffix = bool(_PAGE_SUFFIX_RE.search(text))
    if page_suffix:
        penalty += TOC_PAGE_SUFFIX_PENALTY
    # Early-ordinal penalty only with other TOC cues — otherwise ordinal 0 is
    # always penalized (0 * 10 < block_count) and plain body Items become
    # skip-ambiguous under SCORE_GAP.
    if (link_heavy or page_suffix) and ordinal * 10 < block_count:
        penalty += TOC_EARLY_ORDINAL_PENALTY
    return penalty


def _body_bonus(signal: SectionSignal | None, text: str) -> int:
    bonus = 0
    if signal is not None:
        if signal.heading_level is not None:
            bonus += HEADING_BONUS
        if signal.is_bold_like:
            bonus += BOLD_BONUS
        if signal.anchor_id:
            bonus += ANCHOR_BONUS
        text_len = signal.total_text_chars if signal.total_text_chars > 0 else len(text)
    else:
        text_len = len(text)
    if text_len <= SHORT_TEXT_MAX_CHARS:
        bonus += SHORT_TEXT_BONUS
    return bonus


def _score_marker(
    base: int,
    signal: SectionSignal | None,
    text: str,
    ordinal: int,
    block_count: int,
) -> int:
    return base + _body_bonus(signal, text) - _toc_penalty(signal, text, ordinal, block_count)


def _contribution(score: int) -> int | None:
    """Return DP contribution, or None if not selectable."""
    if score <= BODY_SELECTION_BASELINE:
        return None
    return score - BODY_SELECTION_BASELINE


def _is_toc_cluster(
    occurrences: Sequence[_RawOccurrence],
    blocks: Sequence[DocumentBlockRecord],
    signals: Mapping[int, SectionSignal],
) -> set[int]:
    """Return ordinals that look like TOC entries.

    A nearby Table of Contents heading alone must not mark a structurally strong
    body boundary as TOC merely because it falls within a fixed ordinal window.
    """
    item_ords = sorted({o.block_ordinal for o in occurrences if o.kind == "item"})
    if not item_ords:
        return set()

    toc_heading_ords = {b.ordinal for b in blocks if b.text is not None and _TOC_RE.search(b.text)}

    def _link_heavy(ordinal: int) -> bool:
        signal = signals.get(ordinal)
        if signal is None or signal.total_text_chars <= 0:
            return False
        return (
            signal.internal_link_count >= 1
            and signal.link_text_chars * 2 >= signal.total_text_chars
        )

    def _near_toc_heading(ordinal: int) -> bool:
        return any(abs(ordinal - h) <= 15 for h in toc_heading_ords)

    def _structurally_strong_body(ordinal: int) -> bool:
        signal = signals.get(ordinal)
        if signal is None or _link_heavy(ordinal):
            return False
        return signal.heading_level is not None or signal.is_bold_like or bool(signal.anchor_id)

    toc_ordinals: set[int] = set()
    # Allow short filings: fewer than 4 candidates when TOC cue or link-heavy.
    min_window = 2 if toc_heading_ords else 4
    for ord_ in item_ords:
        window = [o for o in item_ords if abs(o - ord_) <= 30]
        if len(window) < min_window and not (_near_toc_heading(ord_) or _link_heavy(ord_)):
            continue
        if not (_near_toc_heading(ord_) or _link_heavy(ord_)):
            continue
        for item_ord in window:
            block = blocks[item_ord] if item_ord < len(blocks) else None
            text = (block.text or "") if block else ""
            page_suffix = bool(_PAGE_SUFFIX_RE.search(text))
            link_heavy = _link_heavy(item_ord)
            # Overreach guard: structurally strong body needs own TOC evidence.
            if _structurally_strong_body(item_ord):
                if page_suffix or link_heavy:
                    toc_ordinals.add(item_ord)
                continue
            if link_heavy or page_suffix or _near_toc_heading(item_ord):
                toc_ordinals.add(item_ord)
    return toc_ordinals


def _default_part_for_item_10k(item_token: str) -> int:
    token = item_token.lower()
    if token in {"1", "1a", "1b", "1c", "2", "3", "4"}:
        return 1
    if token in {"5", "6", "7", "7a", "8", "9", "9a", "9b", "9c"}:
        return 2
    if token in {"10", "11", "12", "13", "14"}:
        return 3
    if token in {"15", "16"}:
        return 4
    return 1


def _collect_raw_occurrences(
    parsed: ParsedDocument,
) -> tuple[list[_RawOccurrence], list[_RawOccurrence], list[_RawOccurrence]]:
    """Collect anchored Part/Item/terminal occurrences before TOC/Part assignment."""
    blocks = parsed.blocks
    signals = _signal_map(parsed.section_signals)
    parts: list[_RawOccurrence] = []
    items: list[_RawOccurrence] = []
    terminals: list[_RawOccurrence] = []
    n = len(blocks)

    for block in blocks:
        text = block.text or ""
        signal = signals.get(block.ordinal)
        display = text.strip()
        if not display:
            continue

        if _SIGNATURE_RE.match(display):
            score = _score_marker(SIGNATURE_BASE_SCORE, signal, display, block.ordinal, n)
            terminals.append(
                _RawOccurrence(kind="terminal", block_ordinal=block.ordinal, score=score)
            )

        part_match = _ANCHORED_PART_RE.match(display)
        if part_match:
            part_num = _part_number(part_match.group(1))
            if part_num is not None:
                score = _score_marker(PART_BASE_SCORE, signal, display, block.ordinal, n)
                parts.append(
                    _RawOccurrence(
                        kind="part",
                        block_ordinal=block.ordinal,
                        score=score,
                        part_num=part_num,
                    )
                )

        item_match = _ANCHORED_ITEM_RE.match(display)
        if not item_match:
            continue
        # First marker is boundary-shaped; scan for all Item tokens (same-ordinal).
        item_tokens = _match_all_items(display)
        if not item_tokens:
            item_tokens = [_normalize_item_token(item_match.group(1))]
        score = _score_marker(ITEM_BASE_SCORE, signal, display, block.ordinal, n)
        if len(item_tokens) > 1:
            score = min(score, MULTI_ITEM_SCORE_CAP)
        items.append(
            _RawOccurrence(
                kind="item",
                block_ordinal=block.ordinal,
                score=score,
                item_tokens=tuple(item_tokens),
            )
        )

    return parts, items, terminals


def _apply_toc_marks(
    parts: Sequence[_RawOccurrence],
    items: Sequence[_RawOccurrence],
    terminals: Sequence[_RawOccurrence],
    blocks: Sequence[DocumentBlockRecord],
    signals: Mapping[int, SectionSignal],
) -> tuple[set[int], list[_RawOccurrence], list[_RawOccurrence], list[_RawOccurrence]]:
    toc_ords = _is_toc_cluster(items, blocks, signals)
    # Also mark part/terminal ordinals that sit in TOC windows with TOC cues.
    for occ in (*parts, *terminals):
        if occ.block_ordinal in toc_ords:
            continue
        # Part/terminal near TOC with page suffix or link-heavy → toc.
        signal = signals.get(occ.block_ordinal)
        block = blocks[occ.block_ordinal] if occ.block_ordinal < len(blocks) else None
        text = (block.text or "") if block else ""
        near = any(
            b.text and _TOC_RE.search(b.text)
            for b in blocks[
                max(0, occ.block_ordinal - 15) : min(len(blocks), occ.block_ordinal + 3)
            ]
        )
        link_heavy = False
        if signal is not None and signal.total_text_chars > 0:
            link_heavy = (
                signal.internal_link_count >= 1
                and signal.link_text_chars * 2 >= signal.total_text_chars
            )
        if near and (link_heavy or _PAGE_SUFFIX_RE.search(text)):
            toc_ords.add(occ.block_ordinal)

    def _adjust(seq: Sequence[_RawOccurrence]) -> list[_RawOccurrence]:
        out: list[_RawOccurrence] = []
        for occ in seq:
            if occ.block_ordinal in toc_ords:
                out.append(
                    _RawOccurrence(
                        kind=occ.kind,
                        block_ordinal=occ.block_ordinal,
                        score=occ.score - TOC_CLUSTER_PENALTY,
                        part_num=occ.part_num,
                        item_tokens=occ.item_tokens,
                    )
                )
            else:
                out.append(occ)
        return out

    return toc_ords, _adjust(parts), _adjust(items), _adjust(terminals)


def _selectable_part_candidates(
    parts: Sequence[_RawOccurrence],
    toc_ords: set[int],
    part_num: int,
) -> list[_Candidate]:
    result: list[_Candidate] = []
    for occ in parts:
        if occ.block_ordinal in toc_ords:
            continue
        if occ.part_num != part_num:
            continue
        if _contribution(occ.score) is None:
            continue
        result.append(
            _Candidate(
                boundary_key=f"part_{part_num}",
                block_ordinal=occ.block_ordinal,
                score=occ.score,
                toc_like=False,
            )
        )
    return result


@dataclass
class _DpNode:
    score: float
    last_ord: int
    choice: _Candidate | None
    prev: _DpNode | None
    boundary_index: int


def _node_better(a: _DpNode, b: _DpNode) -> bool:
    if a.score != b.score:
        return a.score > b.score
    if a.last_ord != b.last_ord:
        return a.last_ord < b.last_ord
    # Prefer skip (None) over a candidate when scores and ordinals equal.
    a_skip = a.choice is None
    b_skip = b.choice is None
    if a_skip != b_skip:
        return a_skip
    return False


def _global_monotonic_dp(
    boundary_order: Sequence[str],
    candidates_by_key: Mapping[str, Sequence[_Candidate]],
) -> tuple[dict[str, _Candidate | None], dict[str, bool], dict[str, list[int]]]:
    """Maximize contribution under monotonic ordinals; compute S*/S_alt ambiguity.

    Returns (selected, ambiguous_flags, alt_ordinals).
    """
    n = len(boundary_order)
    options: list[list[_Candidate | None]] = []
    for key in boundary_order:
        cands = [
            c
            for c in candidates_by_key.get(key, ())
            if not c.toc_like and _contribution(c.score) is not None
        ]
        cands = sorted(cands, key=lambda c: (c.block_ordinal, -c.score))
        options.append([None, *cands])

    layer: dict[int, _DpNode] = {
        -1: _DpNode(score=0.0, last_ord=-1, choice=None, prev=None, boundary_index=-1)
    }

    for i, _key in enumerate(boundary_order):
        next_layer: dict[int, _DpNode] = {}
        for opt in options[i]:
            if opt is None:
                contrib = 0.0
                choice = None
            else:
                contrib_val = _contribution(opt.score)
                assert contrib_val is not None
                contrib = float(contrib_val)
                choice = opt

            for prev in layer.values():
                if choice is not None and choice.block_ordinal <= prev.last_ord:
                    continue
                new_ord = prev.last_ord if choice is None else choice.block_ordinal
                new_score = prev.score + contrib
                existing = next_layer.get(new_ord)
                node = _DpNode(
                    score=new_score,
                    last_ord=new_ord,
                    choice=choice,
                    prev=prev,
                    boundary_index=i,
                )
                if existing is None or _node_better(node, existing):
                    next_layer[new_ord] = node
        if not next_layer:
            next_layer = {
                k: _DpNode(
                    score=v.score, last_ord=v.last_ord, choice=None, prev=v, boundary_index=i
                )
                for k, v in layer.items()
            }
        layer = next_layer

    best_node: _DpNode | None = None
    for node in layer.values():
        if best_node is None or _node_better(node, best_node):
            best_node = node
    assert best_node is not None

    selected_list: list[_Candidate | None] = [None] * n
    cursor: _DpNode | None = best_node
    while cursor is not None and cursor.boundary_index >= 0:
        selected_list[cursor.boundary_index] = cursor.choice
        cursor = cursor.prev
    selected = {boundary_order[i]: selected_list[i] for i in range(n)}
    s_star = best_node.score

    ambiguous: dict[str, bool] = {}
    alt_ordinals: dict[str, list[int]] = {}
    for ki, key in enumerate(boundary_order):
        opt_state = selected[key]
        opt_ord = opt_state.block_ordinal if opt_state is not None else None
        s_alt: float = _NEG_INF
        alt_ords: list[int] = []
        alt_options: list[_Candidate | None] = []
        for opt in options[ki]:
            if opt_state is None and opt is None:
                continue
            if (
                opt_state is not None
                and opt is not None
                and opt.block_ordinal == opt_state.block_ordinal
            ):
                continue
            alt_options.append(opt)

        for forced in alt_options:
            score = _score_path_with_forced(boundary_order, options, ki, forced)
            if score > s_alt:
                s_alt = score
            if forced is not None:
                alt_ords.append(forced.block_ordinal)

        if s_alt == _NEG_INF:
            ambiguous[key] = False
        elif s_star - s_alt <= SCORE_GAP:
            ambiguous[key] = True
            alt_ordinals[key] = sorted(set(alt_ords))
            if opt_ord is not None:
                alt_ordinals[key] = sorted(set([*alt_ordinals[key], opt_ord]))
        else:
            ambiguous[key] = False

    for key, is_amb in ambiguous.items():
        if is_amb:
            selected[key] = None

    return selected, ambiguous, alt_ordinals


def _score_path_with_forced(
    boundary_order: Sequence[str],
    options: Sequence[Sequence[_Candidate | None]],
    forced_index: int,
    forced_choice: _Candidate | None,
) -> float:
    """Best monotonic path score forcing boundary forced_index to forced_choice."""
    n = len(boundary_order)

    @dataclass
    class _N:
        score: float
        last_ord: int

    layer: dict[int, _N] = {-1: _N(score=0.0, last_ord=-1)}
    for i in range(n):
        next_layer: dict[int, _N] = {}
        if i == forced_index:
            opts: Sequence[_Candidate | None] = (forced_choice,)
        else:
            opts = options[i]
        for opt in opts:
            if opt is None:
                contrib = 0.0
            else:
                c = _contribution(opt.score)
                if c is None:
                    continue
                contrib = float(c)
            for prev in layer.values():
                if opt is not None and opt.block_ordinal <= prev.last_ord:
                    continue
                new_ord = prev.last_ord if opt is None else opt.block_ordinal
                new_score = prev.score + contrib
                existing = next_layer.get(new_ord)
                node = _N(score=new_score, last_ord=new_ord)
                if (
                    existing is None
                    or node.score > existing.score
                    or (node.score == existing.score and node.last_ord < existing.last_ord)
                ):
                    next_layer[new_ord] = node
        if not next_layer:
            return _NEG_INF
        layer = next_layer
    if not layer:
        return _NEG_INF
    return max(n.score for n in layer.values())


def _resolve_10q_parts(
    parts: Sequence[_RawOccurrence],
    toc_ords: set[int],
) -> tuple[int | None, int | None, bool]:
    """Return (part1_ord, part2_ord, part_transition_ambiguous)."""
    part1 = _selectable_part_candidates(parts, toc_ords, 1)
    part2 = _selectable_part_candidates(parts, toc_ords, 2)
    order = ("part_1", "part_2")
    by_key: dict[str, list[_Candidate]] = {"part_1": part1, "part_2": part2}
    selected, ambiguous, _alts = _global_monotonic_dp(order, by_key)
    p1 = selected.get("part_1")
    p2 = selected.get("part_2")
    transition_ambiguous = ambiguous.get("part_1", False) or ambiguous.get("part_2", False)
    return (
        p1.block_ordinal if p1 is not None else None,
        p2.block_ordinal if p2 is not None else None,
        transition_ambiguous,
    )


def _part_i_token_rank(token: str) -> int | None:
    try:
        return _PART_I_10Q_ORDER.index(token)
    except ValueError:
        return None


def _assign_item_parts(
    form_type: str,
    items: Sequence[_RawOccurrence],
    toc_ords: set[int],
    part1_ord: int | None,
    part2_ord: int | None,
    part_transition_ambiguous: bool,
) -> tuple[list[_Candidate], set[int], dict[str, list[int]]]:
    """Assign Part to Item occurrences. Returns (candidates, unresolved_ords, unresolved_alt)."""
    boundary_set = set(_boundary_keys(form_type))
    form = _base_form(form_type)
    candidates: list[_Candidate] = []
    unresolved_ords: set[int] = set()
    unresolved_alts: dict[str, list[int]] = {}

    # Track Part-I monotonic progress for Part-I-only case.
    part_i_last_rank = -1
    part_i_interval_ended = False

    for occ in sorted(items, key=lambda o: o.block_ordinal):
        toc_like = occ.block_ordinal in toc_ords
        score = occ.score
        for item_token in occ.item_tokens:
            part: int | None = None
            part_unresolved = False

            if form == "10-K":
                part = _default_part_for_item_10k(item_token)
                # Refine with body Part headings when present.
                if part2_ord is not None and occ.block_ordinal >= part2_ord:
                    # 10-K Part II+ headings can refine; keep defaults unless
                    # ordinal is clearly after an explicit later Part marker.
                    pass
                if part1_ord is not None and part2_ord is not None:
                    if part1_ord <= occ.block_ordinal < part2_ord and item_token in {
                        "1",
                        "1a",
                        "1b",
                        "1c",
                        "2",
                        "3",
                        "4",
                    }:
                        part = 1
                    elif occ.block_ordinal >= part2_ord and item_token in {
                        "5",
                        "6",
                        "7",
                        "7a",
                        "8",
                        "9",
                        "9a",
                        "9b",
                        "9c",
                    }:
                        part = 2
            else:
                # 10-Q
                if part_transition_ambiguous:
                    # Items whose Part depends on the transition are unresolved
                    # when they could be either side.
                    if part1_ord is not None and part2_ord is not None:
                        if part1_ord <= occ.block_ordinal < part2_ord:
                            part = 1
                        elif occ.block_ordinal >= part2_ord:
                            part = 2
                        else:
                            part_unresolved = True
                    else:
                        part_unresolved = True
                elif part1_ord is not None and part2_ord is not None:
                    if occ.block_ordinal >= part2_ord:
                        part = 2
                    elif occ.block_ordinal >= part1_ord:
                        part = 1
                    else:
                        part_unresolved = True
                elif part2_ord is not None and part1_ord is None:
                    if occ.block_ordinal >= part2_ord:
                        part = 2
                    else:
                        part_unresolved = True
                elif part1_ord is not None and part2_ord is None:
                    if occ.block_ordinal < part1_ord or part_i_interval_ended:
                        part_unresolved = True
                    else:
                        rank = _part_i_token_rank(item_token)
                        if rank is None:
                            # Requires Part-II interpretation (e.g. 1a after part I).
                            part_i_interval_ended = True
                            part_unresolved = True
                        elif rank < part_i_last_rank:
                            # Reset/decrease ends trusted Part-I interval.
                            part_i_interval_ended = True
                            part_unresolved = True
                        else:
                            part = 1
                            part_i_last_rank = rank
                else:
                    # No reliable Part evidence — do not silently default to Part I.
                    part_unresolved = True

            if part_unresolved:
                unresolved_ords.add(occ.block_ordinal)
                for alt_part in (1, 2):
                    key = f"part_{alt_part}.item_{item_token}"
                    if key in boundary_set:
                        unresolved_alts.setdefault(key, []).append(occ.block_ordinal)
                continue

            assert part is not None
            boundary_key = f"part_{part}.item_{item_token}"
            if boundary_key not in boundary_set:
                continue
            candidates.append(
                _Candidate(
                    boundary_key=boundary_key,
                    block_ordinal=occ.block_ordinal,
                    score=score,
                    toc_like=toc_like,
                    item_token=item_token,
                )
            )

    return candidates, unresolved_ords, unresolved_alts


def _resolve_terminal(
    terminals: Sequence[_RawOccurrence],
    toc_ords: set[int],
    last_body_ordinal: int,
) -> tuple[int | None, list[DocumentIssueRecord]]:
    issues: list[DocumentIssueRecord] = []
    bodyish = [
        t
        for t in terminals
        if t.block_ordinal not in toc_ords
        and t.block_ordinal > last_body_ordinal
        and _contribution(t.score) is not None
    ]
    if not bodyish:
        bodyish = [
            t
            for t in terminals
            if t.block_ordinal not in toc_ords and t.block_ordinal > last_body_ordinal
        ]
    if not bodyish:
        return None, issues
    ordered = sorted(bodyish, key=lambda c: (-c.score, c.block_ordinal))
    best = ordered[0]
    second = ordered[1] if len(ordered) > 1 else None
    if second is not None and (best.score - second.score) <= SCORE_GAP:
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


def _detect_same_ordinal_collapse(
    candidates: Sequence[_Candidate],
) -> tuple[set[str], dict[str, set[int]]]:
    """Detect distinct boundary keys sharing an ordinal (non-TOC pool)."""
    ordinal_to_keys: dict[int, set[str]] = {}
    for cand in candidates:
        if cand.toc_like:
            continue
        ordinal_to_keys.setdefault(cand.block_ordinal, set()).add(cand.boundary_key)
    collapsed_ordinals = {ord_ for ord_, keys in ordinal_to_keys.items() if len(keys) > 1}
    collapsed_keys: set[str] = set()
    collapsed_boundary_ordinals: dict[str, set[int]] = {}
    for cand in candidates:
        if cand.toc_like:
            continue
        if cand.block_ordinal in collapsed_ordinals:
            collapsed_keys.add(cand.boundary_key)
            collapsed_boundary_ordinals.setdefault(cand.boundary_key, set()).add(cand.block_ordinal)
    return collapsed_keys, collapsed_boundary_ordinals


def _later_successor_keys(boundary_order: Sequence[str], start_key: str) -> set[str]:
    try:
        idx = boundary_order.index(start_key)
    except ValueError:
        return set()
    return set(boundary_order[idx + 1 :])


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
    signals = _signal_map(parsed.section_signals)

    raw_parts, raw_items, raw_terminals = _collect_raw_occurrences(parsed)
    toc_ords, parts, items, terminals = _apply_toc_marks(
        raw_parts, raw_items, raw_terminals, parsed.blocks, signals
    )
    # Rebuild toc set from adjusted scores (cluster penalty applied).
    toc_ords = {
        o.block_ordinal for o in (*parts, *items, *terminals) if o.block_ordinal in toc_ords
    }

    part1_ord: int | None = None
    part2_ord: int | None = None
    part_transition_ambiguous = False
    if _base_form(form) == "10-Q":
        part1_ord, part2_ord, part_transition_ambiguous = _resolve_10q_parts(parts, toc_ords)
    else:
        # 10-K: optional Part markers refine defaults; collect non-TOC part ords.
        body_parts = [p for p in parts if p.block_ordinal not in toc_ords]
        for p in sorted(body_parts, key=lambda x: x.block_ordinal):
            if p.part_num == 1 and part1_ord is None and _contribution(p.score) is not None:
                part1_ord = p.block_ordinal
            if p.part_num == 2 and part2_ord is None and _contribution(p.score) is not None:
                part2_ord = p.block_ordinal

    item_candidates, part_unresolved_ords, part_unresolved_alts = _assign_item_parts(
        form,
        items,
        toc_ords,
        part1_ord,
        part2_ord,
        part_transition_ambiguous,
    )

    # Keep TOC candidates for issue routing, but hard-exclude from DP.
    body_candidates = [c for c in item_candidates if not c.toc_like]
    toc_only_by_key: dict[str, list[_Candidate]] = {}
    for occ in items:
        if occ.block_ordinal not in toc_ords:
            continue
            for token in occ.item_tokens:
                # Best-effort key for TOC-only messaging (form defaults for 10-K).
                part = _default_part_for_item_10k(token) if _base_form(form) == "10-K" else 1
                key = f"part_{part}.item_{token}"
                toc_only_by_key.setdefault(key, []).append(
                    _Candidate(
                        boundary_key=key,
                        block_ordinal=occ.block_ordinal,
                        score=occ.score,
                        toc_like=True,
                        item_token=token,
                    )
                )

    collapsed_keys, collapsed_boundary_ordinals = _detect_same_ordinal_collapse(body_candidates)

    by_key: dict[str, list[_Candidate]] = {}
    for cand in body_candidates:
        if cand.boundary_key in collapsed_keys:
            continue  # collapsed starts excluded from DP selection
        by_key.setdefault(cand.boundary_key, []).append(cand)

    selected, ambiguous, alt_ordinals = _global_monotonic_dp(boundary_order, by_key)

    # Ensure collapsed keys are cleared.
    for key in collapsed_keys:
        selected[key] = None

    last_body = max((c.block_ordinal for c in selected.values() if c is not None), default=-1)
    terminal_ord, terminal_issues = _resolve_terminal(terminals, toc_ords, last_body)

    issues: list[DocumentIssueRecord] = list(terminal_issues)
    status = "complete"
    sections: list[FilingSectionRecord] = []
    is_amendment = form in _AMENDMENT_FORMS

    resolved_bounds: list[tuple[str, int]] = []
    for key in boundary_order:
        cand = selected.get(key)
        if cand is not None:
            resolved_bounds.append((key, cand.block_ordinal))

    def end_for(start_key: str, start_ord: int) -> tuple[int | None, dict[str, object]]:
        later = [(k, o) for k, o in resolved_bounds if o > start_ord]
        first_later_ord = later[0][1] if later else None
        terminal_candidate = (
            terminal_ord if terminal_ord is not None and terminal_ord > start_ord else None
        )
        prospective_end = first_later_ord if first_later_ord is not None else terminal_candidate

        successors = _later_successor_keys(boundary_order, start_key)
        # Intervening same-ordinal collapse of a grammar successor.
        for key, ords in collapsed_boundary_ordinals.items():
            if key not in successors:
                continue
            for coll_ord in ords:
                if prospective_end is None:
                    if coll_ord > start_ord:
                        return None, {
                            "section_key": start_key,
                            "boundary_role": "end",
                            "expected_after": start_key,
                            "candidate_ordinals": [coll_ord],
                            "reason": "same_ordinal_collapse",
                        }
                elif start_ord < coll_ord < prospective_end:
                    return None, {
                        "section_key": start_key,
                        "boundary_role": "end",
                        "expected_after": start_key,
                        "candidate_ordinals": [coll_ord],
                        "reason": "same_ordinal_collapse",
                    }

        # Ambiguous intervening successors.
        for key in boundary_order:
            if key == start_key or key not in successors:
                continue
            if not ambiguous.get(key, False):
                continue
            cand_ords = alt_ordinals.get(key, [])
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
            if inside:
                return None, {
                    "section_key": start_key,
                    "boundary_role": "end",
                    "expected_after": start_key,
                    "candidate_ordinals": inside,
                }

        # Part-context unresolved intervening.
        for key, ords in part_unresolved_alts.items():
            if key not in successors:
                continue
            for o in ords:
                if prospective_end is None:
                    if o > start_ord:
                        return None, {
                            "section_key": start_key,
                            "boundary_role": "end",
                            "expected_after": start_key,
                            "candidate_ordinals": [o],
                            "reason": "part_context_unresolved",
                        }
                elif start_ord < o < prospective_end:
                    return None, {
                        "section_key": start_key,
                        "boundary_role": "end",
                        "expected_after": start_key,
                        "candidate_ordinals": [o],
                        "reason": "part_context_unresolved",
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

        if start_cand is None:
            if boundary_key in collapsed_keys:
                issues.append(
                    DocumentIssueRecord(
                        severity="warning",
                        code="SECTION_BOUNDARY_UNRESOLVED",
                        message=f"same-ordinal collapse for {section_key}",
                        context={
                            "section_key": section_key,
                            "boundary_role": "start",
                            "reason": "same_ordinal_collapse",
                            "candidate_ordinals": sorted(
                                collapsed_boundary_ordinals.get(boundary_key, set())
                            ),
                        },
                    )
                )
                status = "incomplete"
                continue

            if ambiguous.get(boundary_key, False):
                issues.append(
                    DocumentIssueRecord(
                        severity="warning",
                        code="SECTION_AMBIGUOUS",
                        message=f"ambiguous start for {section_key}",
                        context={
                            "section_key": section_key,
                            "candidate_ordinals": alt_ordinals.get(boundary_key, []),
                        },
                    )
                )
                status = "incomplete"
                continue

            if boundary_key in part_unresolved_alts:
                issues.append(
                    DocumentIssueRecord(
                        severity="warning",
                        code="SECTION_AMBIGUOUS",
                        message=f"unresolved part context for {section_key}",
                        context={
                            "section_key": section_key,
                            "reason": "part_context_unresolved",
                            "candidate_ordinals": sorted(set(part_unresolved_alts[boundary_key])),
                        },
                    )
                )
                status = "incomplete"
                continue

            toc_cands = toc_only_by_key.get(boundary_key, [])
            # Also check alternate Part keys for 10-Q TOC-only.
            if not toc_cands and _base_form(form) == "10-Q":
                for alt_part in (1, 2):
                    alt_key = re.sub(r"part_\d+", f"part_{alt_part}", boundary_key, count=1)
                    toc_cands = toc_only_by_key.get(alt_key, [])
                    if toc_cands:
                        break
            body_exists = any(
                c.boundary_key == boundary_key and not c.toc_like for c in item_candidates
            )
            if toc_cands and not body_exists:
                issues.append(
                    DocumentIssueRecord(
                        severity="warning",
                        code="TOC_ONLY_SECTION_MATCH",
                        message=f"only TOC candidates for {section_key}",
                        context={
                            "section_key": section_key,
                            "candidate_ordinals": [c.block_ordinal for c in toc_cands],
                        },
                    )
                )
                status = "incomplete"
                continue

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
