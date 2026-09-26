"""Guards on destructive test database helpers."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from tests.helpers.database import reset_test_database


def test_reset_refuses_non_test_engine() -> None:
    engine = create_engine("postgresql+psycopg://edgar:edgar@localhost:5432/postgres")
    with pytest.raises(RuntimeError, match="edgar_test"):
        reset_test_database(
            engine, database_url="postgresql+psycopg://edgar:edgar@localhost:5432/edgar_test"
        )
    engine.dispose()
