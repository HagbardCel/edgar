"""Inline XBRL Target Document identity (M1A-3 scanner)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class DefaultTarget:
    kind: Literal["default"] = "default"


@dataclass(frozen=True)
class NamedTarget:
    name: str
    kind: Literal["named"] = "named"


TargetIdentity = DefaultTarget | NamedTarget


def target_identity_from_ixds_domain_target(domain_target: str) -> DefaultTarget | NamedTarget:
    """Map production ``IxdsReportInput.target`` (only ``default`` today) to scanner identity."""
    if domain_target == "default":
        return DefaultTarget()
    return NamedTarget(name=domain_target)


def target_identity_from_inline_attribute(raw_target: str | None) -> TargetIdentity:
    if raw_target is None:
        return DefaultTarget()
    return NamedTarget(name=raw_target)


def target_identity_key(identity: TargetIdentity) -> tuple[str, str]:
    if isinstance(identity, DefaultTarget):
        return ("default", "")
    return ("named", identity.name)


def target_identity_to_dict(identity: TargetIdentity) -> dict[str, Any]:
    if isinstance(identity, DefaultTarget):
        return {"kind": "default"}
    return {"kind": "named", "name": identity.name}


def selected_target_for_report_input(
    *,
    domain_target: str | None,
) -> TargetIdentity:
    """Selected target for a production IXDS report input (domain sentinel)."""
    if domain_target is None:
        return DefaultTarget()
    return target_identity_from_ixds_domain_target(domain_target)
