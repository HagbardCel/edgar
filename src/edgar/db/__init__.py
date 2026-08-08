"""PostgreSQL catalog package."""

from edgar.db.engine import create_db_engine
from edgar.db.schema import metadata

__all__ = ["create_db_engine", "metadata"]
