"""Fail-closed classification of engine diagnostics (ADR 0008 §10).

An unrecognized diagnostic must prevent a *clean / complete* semantic status
without forcing the filing to be discarded. Classification is therefore closed
by default: a warning-or-worse diagnostic is compatible with a complete
projection only when its message code is listed in
:data:`COMPLETE_COMPATIBLE_DIAGNOSTICS` together with a written rationale.

Admitting a code to that registry requires evidence that

1. the diagnostic reports on *filed content*, not on the extraction process, and
2. every structure the projection persists (concepts, relationships, contexts,
   units, and fact occurrences with their values) survives the diagnostic
   unchanged, verified against offline fixtures.

The registry starts empty on purpose. The Slice-0 spike registry
(``scripts/spikes/spike_lib/arelle_errors.py``) is *not* inherited: its
rationales were written for document/relationship closure evidence and
explicitly disclaimed fact-value fidelity, which this projection does claim.
Each code must be re-justified against the production projection before it is
added here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from edgar.xbrl.records import DiagnosticRecord

DIAGNOSTIC_POLICY_VERSION = "diagnostic-policy-v1"

# Placeholder code for a diagnostic the engine emitted without a message code.
# An unstructured diagnostic can never be recognized, so it always blocks.
UNSTRUCTURED_CODE = "UNSTRUCTURED"

DiagnosticClassification = Literal["complete_compatible", "completeness_blocking"]

# Severities that never block semantic completeness on their own. Anything at
# warning level or above must be justified by code.
NON_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"info"})

# Message code -> rationale for why the diagnostic cannot hide a projection
# defect. Empty by deliberate policy; see the module docstring.
COMPLETE_COMPATIBLE_DIAGNOSTICS: Mapping[str, str] = {}


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
