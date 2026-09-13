"""SQLAlchemy metadata and V2 table registry.

Live persistence is ``source.*`` plus the Phase 2C ``registry.*`` mirror/ledger.
Phase-1 public-schema projection/catalog tables are removed; recreate local DBs
rather than upgrading from the old 0001–0004 lineage.
"""

from __future__ import annotations

from sqlalchemy import MetaData

metadata = MetaData()

SHA256_CHECK = r"^[0-9a-f]{64}$"

# Import for side-effect registration on ``metadata`` and the ALL_TABLES export.
from edgar.db.registry_schema import REGISTRY_TABLES  # noqa: E402
from edgar.db.source_schema import SOURCE_TABLES  # noqa: E402

ALL_TABLES = SOURCE_TABLES + REGISTRY_TABLES

__all__ = ["ALL_TABLES", "REGISTRY_TABLES", "SHA256_CHECK", "SOURCE_TABLES", "metadata"]
