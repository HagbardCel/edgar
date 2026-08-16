"""Fail-closed classification of engine diagnostics (ADR 0008 §10).

An unrecognized diagnostic must prevent a *clean / complete* semantic status
without forcing the filing to be discarded. Classification is therefore closed
by default: a warning-or-worse diagnostic is compatible with a complete
projection only when its message code is listed in
:data:`COMPLETE_COMPATIBLE_DIAGNOSTICS` together with a written rationale.

A warning-or-worse diagnostic may be complete-compatible only when:

1. it concerns *filed content* rather than a failure of extraction/replay; and
2. the projection faithfully represents the affected filed structures and their
   semantic validity state, without silently dropping or fabricating
   information. Any loss of information the projection claims to preserve must
   independently produce a fatal semantic issue.

Completeness does **not** mean every filed fact is valid. It means every
relevant filed occurrence and its semantic validity state are faithfully
represented. For an invalid Inline-XBRL transformation, the fact remains
present with source provenance and raw filed content, ``value_status="invalid"``,
and no fabricated resolved value. If that same occurrence also exposes an
unsupported or lost structure (for example unavailable raw lexical content), a
separate fatal semantic issue keeps the projection incomplete.

The Slice-0 spike registry (``scripts/spikes/spike_lib/arelle_errors.py``) is
*not* inherited: its rationales were written for document/relationship closure
evidence and explicitly disclaimed fact-value fidelity. Each code must be
re-justified against the production projection before it is added here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from edgar.xbrl.records import DiagnosticRecord

DIAGNOSTIC_POLICY_VERSION = "diagnostic-policy-v2"

# Placeholder code for a diagnostic the engine emitted without a message code.
# An unstructured diagnostic can never be recognized, so it always blocks.
UNSTRUCTURED_CODE = "UNSTRUCTURED"

DiagnosticClassification = Literal["complete_compatible", "completeness_blocking"]

# Severities that never block semantic completeness on their own. Anything at
# warning level or above must be justified by code.
NON_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"info"})

_INVALID_TRANSFORMATION_RATIONALE = (
    "Filed Inline-XBRL transformation failure: the affected fact occurrence is "
    "retained with source provenance and raw lexical content, value_status="
    "'invalid', and no fabricated resolved value. Completeness requires faithful "
    "representation of validity state, not validity of every filed fact. Any "
    "independent loss of claimed evidence (for example unavailable raw lexical "
    "content) still produces a separate fatal semantic issue."
)

# Message code -> rationale for why the diagnostic is complete-compatible under
# the faithful-representation doctrine above.
COMPLETE_COMPATIBLE_DIAGNOSTICS: Mapping[str, str] = {
    "ix11.10.1.2:invalidTransformation": _INVALID_TRANSFORMATION_RATIONALE,
    "ix11.11.1.2:invalidTransformation": _INVALID_TRANSFORMATION_RATIONALE,
}


def registry_codes(
    registry: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Sorted codes of the active complete-compatible registry."""
    active = COMPLETE_COMPATIBLE_DIAGNOSTICS if registry is None else registry
    return tuple(sorted(active))


def classify_diagnostic(
    diagnostic: DiagnosticRecord,
    *,
    registry: Mapping[str, str] | None = None,
) -> DiagnosticClassification:
    """Classify one diagnostic occurrence against the completeness policy."""
    active = COMPLETE_COMPATIBLE_DIAGNOSTICS if registry is None else registry
    if diagnostic.severity in NON_BLOCKING_SEVERITIES:
        return "complete_compatible"
    if diagnostic.code == UNSTRUCTURED_CODE:
        return "completeness_blocking"
    if diagnostic.code in active:
        return "complete_compatible"
    return "completeness_blocking"


def blocking_diagnostics(
    diagnostics: Iterable[DiagnosticRecord],
    *,
    registry: Mapping[str, str] | None = None,
) -> tuple[DiagnosticRecord, ...]:
    """Diagnostics that prevent a complete/clean semantic status, in input order."""
    return tuple(
        diagnostic
        for diagnostic in diagnostics
        if classify_diagnostic(diagnostic, registry=registry) == "completeness_blocking"
    )


def diagnostics_allow_complete(
    diagnostics: Iterable[DiagnosticRecord],
    *,
    registry: Mapping[str, str] | None = None,
) -> bool:
    """True when no diagnostic blocks a complete semantic status."""
    return not blocking_diagnostics(diagnostics, registry=registry)


def blocking_occurrence_count(
    diagnostics: Iterable[DiagnosticRecord],
    *,
    registry: Mapping[str, str] | None = None,
) -> int:
    """Total multiplicity of blocking diagnostics (occurrences, not classes)."""
    return sum(
        diagnostic.occurrence_count
        for diagnostic in blocking_diagnostics(diagnostics, registry=registry)
    )
