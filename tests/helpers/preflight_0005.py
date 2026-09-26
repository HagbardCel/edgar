"""Parse and execute shipped 0005 preflight SQL (test-only)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Connection, text

PREFLIGHT_SQL_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "preflight" / "0005_readonly_preflight.sql"
)


def statements_from_preflight_sql(sql_text: str) -> list[str]:
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def load_preflight_statements() -> list[str]:
    sql = PREFLIGHT_SQL_PATH.read_text(encoding="utf-8")
    statements = statements_from_preflight_sql(sql)
    assert len(statements) == 9
    assert all(stmt.lstrip().upper().startswith("SELECT") for stmt in statements)
    return statements


def run_preflight(conn: Connection) -> list[list]:
    results: list[list] = []
    for statement in load_preflight_statements():
        rows = conn.execute(text(statement)).fetchall()
        results.append(list(rows))
    return results
