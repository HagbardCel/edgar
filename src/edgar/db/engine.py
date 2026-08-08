"""SQLAlchemy engine helpers for the PostgreSQL catalog."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine


def create_db_engine(url: str, *, echo: bool = False) -> Engine:
    """Create a synchronous SQLAlchemy engine. Does not connect until first use."""
    return create_engine(url, echo=echo, future=True)
