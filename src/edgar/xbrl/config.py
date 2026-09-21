"""Versioned Arelle extraction configuration (policy knobs only).

Engine version and wire-format version stay out of this object. V2 ``source.*``
persistence does not key identity on configuration fingerprints.
``SemanticConfig`` contains no ``projection_version`` and no config-fingerprint
identity field.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from edgar.domain.decode import (
    BundleDecodeError,
    require_bool,
    require_exact_keys,
    require_list_of_str,
    require_object,
    require_str,
)
from edgar.xbrl.diagnostics import (
    COMPLETE_COMPATIBLE_DIAGNOSTICS,
    DIAGNOSTIC_POLICY_VERSION,
    registry_codes,
)

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

RESOURCE_ARCROLES: frozenset[str] = frozenset({CONCEPT_LABEL_ARCROLE, CONCEPT_REFERENCE_ARCROLE})
EXCLUDED_ARCROLES: frozenset[str] = frozenset({FACT_FOOTNOTE_ARCROLE})
DEFERRED_ARCROLES: frozenset[str] = frozenset(
    {
        "http://xbrl.org/arcrole/2008/element-label",
        "http://xbrl.org/arcrole/2008/element-reference",
    }
)


def _sorted_tuple(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


SEMANTIC_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "fact_lexical_version",
        "element_locator_version",
        "xml_fragment_version",
        "diagnostic_policy_version",
        "complete_compatible_diagnostics",
        "presentation_arcroles",
        "calculation_arcroles",
        "definition_arcroles",
        "resource_arcroles",
        "excluded_arcroles",
        "deferred_arcroles",
        "custom_definition_link_arcroles_supported",
        "reported_dimensions_only",
        "non_dimensional_context_policy",
        "item_facts_only",
    }
)


@dataclass(frozen=True)
class SemanticConfig:
    """Interpretation-affecting policy knobs for one Arelle source extraction."""

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
    non_dimensional_context_policy: str
    item_facts_only: bool

    def __post_init__(self) -> None:
        for name in (
            "fact_lexical_version",
            "element_locator_version",
            "xml_fragment_version",
            "diagnostic_policy_version",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        if self.non_dimensional_context_policy != "incomplete":
            raise ValueError("non_dimensional_context_policy must be 'incomplete'")
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
                raise ValueError(f"{name} must be sorted for stable policy")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} contains duplicates")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SemanticConfig:
        """Strict persisted/wire decode: no defaults, no sorting, no repair.

        Instantiates :class:`SemanticConfig` directly. Does **not** call
        :func:`build_semantic_config`. Unsorted lists and duplicates fail in
        ``__post_init__``.
        """
        try:
            obj = require_object(data, label="semantic_config")
            require_exact_keys(obj, SEMANTIC_CONFIG_KEYS, label="semantic_config")
            return cls(
                fact_lexical_version=require_str(
                    obj["fact_lexical_version"], label="semantic_config.fact_lexical_version"
                ),
                element_locator_version=require_str(
                    obj["element_locator_version"],
                    label="semantic_config.element_locator_version",
                ),
                xml_fragment_version=require_str(
                    obj["xml_fragment_version"], label="semantic_config.xml_fragment_version"
                ),
                diagnostic_policy_version=require_str(
                    obj["diagnostic_policy_version"],
                    label="semantic_config.diagnostic_policy_version",
                ),
                complete_compatible_diagnostics=tuple(
                    require_list_of_str(
                        obj["complete_compatible_diagnostics"],
                        label="semantic_config.complete_compatible_diagnostics",
                    )
                ),
                presentation_arcroles=tuple(
                    require_list_of_str(
                        obj["presentation_arcroles"],
                        label="semantic_config.presentation_arcroles",
                    )
                ),
                calculation_arcroles=tuple(
                    require_list_of_str(
                        obj["calculation_arcroles"],
                        label="semantic_config.calculation_arcroles",
                    )
                ),
                definition_arcroles=tuple(
                    require_list_of_str(
                        obj["definition_arcroles"],
                        label="semantic_config.definition_arcroles",
                    )
                ),
                resource_arcroles=tuple(
                    require_list_of_str(
                        obj["resource_arcroles"],
                        label="semantic_config.resource_arcroles",
                    )
                ),
                excluded_arcroles=tuple(
                    require_list_of_str(
                        obj["excluded_arcroles"],
                        label="semantic_config.excluded_arcroles",
                    )
                ),
                deferred_arcroles=tuple(
                    require_list_of_str(
                        obj["deferred_arcroles"],
                        label="semantic_config.deferred_arcroles",
                    )
                ),
                custom_definition_link_arcroles_supported=require_bool(
                    obj["custom_definition_link_arcroles_supported"],
                    label="semantic_config.custom_definition_link_arcroles_supported",
                ),
                reported_dimensions_only=require_bool(
                    obj["reported_dimensions_only"],
                    label="semantic_config.reported_dimensions_only",
                ),
                non_dimensional_context_policy=require_str(
                    obj["non_dimensional_context_policy"],
                    label="semantic_config.non_dimensional_context_policy",
                ),
                item_facts_only=require_bool(
                    obj["item_facts_only"], label="semantic_config.item_facts_only"
                ),
            )
        except BundleDecodeError as exc:
            raise ValueError(str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
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
            "non_dimensional_context_policy": self.non_dimensional_context_policy,
            "item_facts_only": self.item_facts_only,
        }


def build_semantic_config(
    *,
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
    non_dimensional_context_policy: str = "incomplete",
    item_facts_only: bool = True,
) -> SemanticConfig:
    """Build extraction policy; defaults are the Phase 1/2B source policy."""
    diagnostics = (
        registry_codes(COMPLETE_COMPATIBLE_DIAGNOSTICS)
        if complete_compatible_diagnostics is None
        else _sorted_tuple(complete_compatible_diagnostics)
    )
    return SemanticConfig(
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
        non_dimensional_context_policy=non_dimensional_context_policy,
        item_facts_only=item_facts_only,
    )
