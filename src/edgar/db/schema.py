"""SQLAlchemy metadata and V2 ``source.*`` table registry.

Phase 2B Commit 6: the live database surface is ``source.*`` only. Phase-1
public-schema projection/catalog tables are removed; recreate local DBs rather
than upgrading from the old 0001–0004 lineage.
"""

from __future__ import annotations

from sqlalchemy import MetaData

metadata = MetaData()

SHA256_CHECK = r"^[0-9a-f]{64}$"

# Import for side-effect registration on ``metadata`` and the ALL_TABLES export.
from edgar.db.source_schema import SOURCE_TABLES  # noqa: E402

ALL_TABLES = SOURCE_TABLES

__all__ = ["ALL_TABLES", "SHA256_CHECK", "SOURCE_TABLES", "metadata"]
