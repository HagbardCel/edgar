"""Versioned semantic-projection configuration and its identity fingerprint.

`semantic_projection` identity is ``filing_bundle`` + ``xbrl_report_input`` +
projection version + engine (Arelle) version + semantic configuration
fingerprint (ADR 0008 §2). This module owns the last two of those inputs that
are ours: the version constants and the deterministic fingerprint over every
interpretation-affecting policy knob.

What belongs in the fingerprint: anything that can change the *meaning* or the
*membership* of persisted records — extraction versions, the supported arcrole
registries, the diagnostic policy version, and the preservation policies.

What must stay out: the engine version (a separate identity component), the
records wire-format version (:data:`edgar.xbrl.records.RECORDS_SCHEMA_VERSION`,
a serialization detail), and all operational metadata such as paths, workspace
locations, timings, and attempt identifiers.

Changing any fingerprinted value yields a *new* projection that coexists with
the old one rather than mutating it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from edgar.xbrl.diagnostics import (
    COMPLETE_COMPATIBLE_DIAGNOSTICS,
    DIAGNOSTIC_POLICY_VERSION,
    registry_codes,
)

SEMANTIC_CONFIG_SCHEMA = "semantic-config-v1"

#: Projection semantics: bump when persisted record meaning or membership changes.
SEMANTIC_PROJECTION_VERSION = "arelle-semantic-v1"

#: Retained lexical fact-value extraction semantics (ADR 0008 §6).
FACT_LEXICAL_VERSION = "fact-lexical-v1"

#: Deterministic element locator contract (:mod:`edgar.xbrl.locators`).
ELEMENT_LOCATOR_VERSION = "element-locator-v1"

#: Namespace-complete typed-member / reference-part XML serialization contract.
XML_FRAGMENT_VERSION = "xml-fragment-v1"

PRESENTATION_ARCROLE = "http://www.xbrl.org/2003/arcrole/parent-child"
CALCULATION_ARCROLE = "http://www.xbrl.org/2003/arcrole/summation-item"
CONCEPT_LABEL_ARCROLE = "http://www.xbrl.org/2003/arcrole/concept-label"
CONCEPT_REFERENCE_ARCROLE = "http://www.xbrl.org/2003/arcrole/concept-reference"
FACT_FOOTNOTE_ARCROLE = "http://www.xbrl.org/2003/arcrole/fact-footnote"

PRESENTATION_ARCROLES: frozenset[str] = frozenset({PRESENTATION_ARCROLE})
CALCULATION_ARCROLES: frozenset[str] = frozenset({CALCULATION_ARCROLE})

# XBRL 2.1 definition arcroles plus the XBRL Dimensions 1.0 registry.
DEFINITION_ARCROLES: frozenset[str] = frozenset(
    {
        "http://www.xbrl.org/2003/arcrole/general-special",
        "http://www.xbrl.org/2003/arcrole/essence-alias",
        "http://www.xbrl.org/2003/arcrole/similar-tuples",
        "http://www.xbrl.org/2003/arcrole/requires-element",
        "http://xbrl.org/int/dim/arcrole/all",
        "http://xbrl.org/int/dim/arcrole/notAll",
        "http://xbrl.org/int/dim/arcrole/hypercube-dimension",
        "http://xbrl.org/int/dim/arcrole/dimension-domain",
        "http://xbrl.org/int/dim/arcrole/domain-member",
        "http://xbrl.org/int/dim/arcrole/dimension-default",
    }
)

# Supported concept-resource relationship classes (ADR 0008 §8).
RESOURCE_ARCROLES: frozenset[str] = frozenset({CONCEPT_LABEL_ARCROLE, CONCEPT_REFERENCE_ARCROLE})

# Counted but neither projected nor failing: footnotes are a later phase and are
# not concept-semantic evidence.
EXCLUDED_ARCROLES: frozenset[str] = frozenset({FACT_FOOTNOTE_ARCROLE})

# Generic labels/references (XBRL Generic Links 1.0). Not supported in Phase 1;
# encountering them fails semantic completeness explicitly rather than dropping
# silently (ADR 0007 deferral).
DEFERRED_ARCROLES: frozenset[str] = frozenset(
    {
        "http://xbrl.org/arcrole/2008/element-label",
        "http://xbrl.org/arcrole/2008/element-reference",
    }
)


def _sorted_tuple(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


@dataclass(frozen=True)
class SemanticConfig:
    """Every interpretation-affecting knob of one semantic projection run."""

    projection_version: str
    fact_lexical_version: str
    element_locator_version: str
    xml_fragment_version: str
    diagnostic_policy_version: str
    complete_compatible_diagnostics: tuple[str, ...]
    presentation_arcroles: tuple[str, ...]
    calculation_arcroles: tuple[str, ...]
    definition_arcroles: tuple[str, ...]
    resource_arcroles: tuple[str, ...]
    excluded_arcroles: tuple[str, ...]
    deferred_arcroles: tuple[str, ...]
    custom_definition_link_arcroles_supported: bool
    reported_dimensions_only: bool
    preserve_non_dimensional_context_content: bool
    item_facts_only: bool

    def __post_init__(self) -> None:
        for name in (
            "projection_version",
            "fact_lexical_version",
            "element_locator_version",
            "xml_fragment_version",
            "diagnostic_policy_version",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        for name in (
            "complete_compatible_diagnostics",
            "presentation_arcroles",
            "calculation_arcroles",
            "definition_arcroles",
            "resource_arcroles",
            "excluded_arcroles",
            "deferred_arcroles",
        ):
            values: tuple[str, ...] = getattr(self, name)
            if list(values) != sorted(values):
                raise ValueError(f"{name} must be sorted for a stable fingerprint")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} contains duplicates")

    def to_dict(self) -> dict[str, Any]:
        """Fingerprint-bearing projection of the configuration."""
        return {
            "projection_version": self.projection_version,
            "fact_lexical_version": self.fact_lexical_version,
            "element_locator_version": self.element_locator_version,
            "xml_fragment_version": self.xml_fragment_version,
            "diagnostic_policy_version": self.diagnostic_policy_version,
            "complete_compatible_diagnostics": list(self.complete_compatible_diagnostics),
            "presentation_arcroles": list(self.presentation_arcroles),
            "calculation_arcroles": list(self.calculation_arcroles),
            "definition_arcroles": list(self.definition_arcroles),
            "resource_arcroles": list(self.resource_arcroles),
            "excluded_arcroles": list(self.excluded_arcroles),
            "deferred_arcroles": list(self.deferred_arcroles),
            "custom_definition_link_arcroles_supported": (
                self.custom_definition_link_arcroles_supported
            ),
            "reported_dimensions_only": self.reported_dimensions_only,
            "preserve_non_dimensional_context_content": (
                self.preserve_non_dimensional_context_content
            ),
            "item_facts_only": self.item_facts_only,
        }


def build_semantic_config(
    *,
    projection_version: str = SEMANTIC_PROJECTION_VERSION,
    fact_lexical_version: str = FACT_LEXICAL_VERSION,
    element_locator_version: str = ELEMENT_LOCATOR_VERSION,
    xml_fragment_version: str = XML_FRAGMENT_VERSION,
    diagnostic_policy_version: str = DIAGNOSTIC_POLICY_VERSION,
    complete_compatible_diagnostics: Sequence[str] | None = None,
    presentation_arcroles: Iterable[str] = PRESENTATION_ARCROLES,
    calculation_arcroles: Iterable[str] = CALCULATION_ARCROLES,
    definition_arcroles: Iterable[str] = DEFINITION_ARCROLES,
    resource_arcroles: Iterable[str] = RESOURCE_ARCROLES,
    excluded_arcroles: Iterable[str] = EXCLUDED_ARCROLES,
    deferred_arcroles: Iterable[str] = DEFERRED_ARCROLES,
    custom_definition_link_arcroles_supported: bool = True,
    reported_dimensions_only: bool = True,
    preserve_non_dimensional_context_content: bool = True,
    item_facts_only: bool = True,
) -> SemanticConfig:
    """Build the active semantic configuration; defaults are the Phase 1 policy.

    Overrides exist for tests and for explicitly versioned policy changes. Any
    override changes the fingerprint and therefore produces a new projection
    identity rather than silently reinterpreting an existing one.
    """
    diagnostics = (
        registry_codes(COMPLETE_COMPATIBLE_DIAGNOSTICS)
        if complete_compatible_diagnostics is None
        else _sorted_tuple(complete_compatible_diagnostics)
    )
    return SemanticConfig(
        projection_version=projection_version,
        fact_lexical_version=fact_lexical_version,
        element_locator_version=element_locator_version,
        xml_fragment_version=xml_fragment_version,
        diagnostic_policy_version=diagnostic_policy_version,
        complete_compatible_diagnostics=diagnostics,
        presentation_arcroles=_sorted_tuple(presentation_arcroles),
        calculation_arcroles=_sorted_tuple(calculation_arcroles),
        definition_arcroles=_sorted_tuple(definition_arcroles),
        resource_arcroles=_sorted_tuple(resource_arcroles),
        excluded_arcroles=_sorted_tuple(excluded_arcroles),
        deferred_arcroles=_sorted_tuple(deferred_arcroles),
        custom_definition_link_arcroles_supported=custom_definition_link_arcroles_supported,
        reported_dimensions_only=reported_dimensions_only,
        preserve_non_dimensional_context_content=preserve_non_dimensional_context_content,
        item_facts_only=item_facts_only,
    )


def semantic_config_fingerprint_bytes(config: SemanticConfig) -> bytes:
    """Exact UTF-8 bytes hashed for the semantic configuration fingerprint."""
    envelope = {"config": config.to_dict(), "schema": SEMANTIC_CONFIG_SCHEMA}
    return json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def semantic_config_fingerprint(config: SemanticConfig) -> str:
    """SHA-256 hex digest of the canonical configuration JSON."""
    return hashlib.sha256(semantic_config_fingerprint_bytes(config)).hexdigest()
