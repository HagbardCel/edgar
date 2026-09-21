"""Unit tests for strict SemanticConfig.from_dict decoding."""

from __future__ import annotations

import pytest

from edgar.xbrl.config import SemanticConfig, build_semantic_config


def test_from_dict_round_trip_exact() -> None:
    cfg = build_semantic_config()
    decoded = SemanticConfig.from_dict(cfg.to_dict())
    assert decoded.to_dict() == cfg.to_dict()
    assert decoded == cfg


def test_from_dict_rejects_missing_key() -> None:
    data = build_semantic_config().to_dict()
    del data["item_facts_only"]
    with pytest.raises(ValueError, match="missing"):
        SemanticConfig.from_dict(data)


def test_from_dict_rejects_unknown_key() -> None:
    data = build_semantic_config().to_dict()
    data["extra"] = True
    with pytest.raises(ValueError, match="unknown"):
        SemanticConfig.from_dict(data)


def test_from_dict_rejects_string_bool() -> None:
    data = build_semantic_config().to_dict()
    data["item_facts_only"] = "false"
    with pytest.raises(ValueError, match="boolean"):
        SemanticConfig.from_dict(data)


def test_from_dict_rejects_unsorted_arcroles() -> None:
    data = build_semantic_config().to_dict()
    data["presentation_arcroles"] = list(reversed(data["presentation_arcroles"]))
    if len(data["presentation_arcroles"]) < 2:
        data["presentation_arcroles"] = ["z-role", "a-role"]
    with pytest.raises(ValueError, match="sorted"):
        SemanticConfig.from_dict(data)


def test_from_dict_does_not_normalize_via_builder() -> None:
    """Unsorted input must fail, not be silently sorted by build_semantic_config."""
    data = build_semantic_config().to_dict()
    data["excluded_arcroles"] = ["http://b.example/role", "http://a.example/role"]
    with pytest.raises(ValueError, match="sorted"):
        SemanticConfig.from_dict(data)
