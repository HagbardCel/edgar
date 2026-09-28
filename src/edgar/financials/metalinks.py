"""Parse SEC MetaLinks.json from a filing bundle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetaLinksStatement:
    role: str
    long_name: str
    group_type: str
    short_name: str


@dataclass(frozen=True)
class MetaLinksView:
    tags: dict[str, dict[str, Any]]
    statements: tuple[MetaLinksStatement, ...]


def parse_metalinks(data: bytes) -> MetaLinksView:
    if not data.strip():
        return MetaLinksView(tags={}, statements=())
    payload = json.loads(data)
    tags: dict[str, dict[str, Any]] = {}
    raw_tags = payload.get("instance", {}).get("dts", {}).get("inline", {}).get("tag", {})
    if isinstance(raw_tags, dict):
        for key, value in raw_tags.items():
            if isinstance(value, dict):
                tags[str(key)] = value
    statements: list[MetaLinksStatement] = []
    for entry in payload.get("report", []) or []:
        if not isinstance(entry, dict):
            continue
        group_type = str(entry.get("groupType", ""))
        if group_type != "statement":
            continue
        statements.append(
            MetaLinksStatement(
                role=str(entry.get("role", "")),
                long_name=str(entry.get("longName", "")),
                group_type=group_type,
                short_name=str(entry.get("shortName", "")),
            )
        )
    return MetaLinksView(tags=tags, statements=tuple(statements))
