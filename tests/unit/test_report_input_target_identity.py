"""TargetIdentity mapping for inline scanner (M1A-3)."""

from __future__ import annotations

from edgar.xbrl.target_identity import (
    DefaultTarget,
    NamedTarget,
    selected_target_for_report_input,
    target_identity_from_inline_attribute,
    target_identity_from_ixds_domain_target,
    target_identity_key,
)


def test_domain_default_is_default_target() -> None:
    assert target_identity_from_ixds_domain_target("default") == DefaultTarget()
    assert selected_target_for_report_input(domain_target="default") == DefaultTarget()


def test_inline_absent_target_is_default() -> None:
    assert target_identity_from_inline_attribute(None) == DefaultTarget()


def test_inline_literal_default_is_named() -> None:
    assert target_identity_from_inline_attribute("default") == NamedTarget(name="default")
    assert target_identity_key(NamedTarget(name="default")) == ("named", "default")
    assert target_identity_key(DefaultTarget()) == ("default", "")
