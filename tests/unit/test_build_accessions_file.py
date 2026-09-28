"""Build CLI must honor --accessions-file for the measurement population."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from edgar.cli import app


def test_build_accessions_file_and_accession_mutually_exclusive(tmp_path: Path) -> None:
    acc_file = tmp_path / "accs.txt"
    acc_file.write_text("0000104169-24-000056\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "build",
            "--accessions-file",
            str(acc_file),
            "--accession",
            "0000320193-24-000123",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0
    assert "at most one" in result.stdout + result.stderr


def test_build_uses_accessions_file(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setenv(
        "EDGAR_DATABASE_URL",
        "postgresql+psycopg://edgar:edgar@localhost:5432/edgar_test",
    )
    acc_file = tmp_path / "accs.txt"
    acc_file.write_text(
        "0000104169-24-000056\n0000320193-24-000123\n",
        encoding="utf-8",
    )
    seen: list[tuple[str, ...]] = []

    def fake_run_build(engine, registry_dir, repo_root, accessions, *, check_gold=False):  # noqa: ANN001, ARG001
        seen.append(accessions)
        from edgar.financials.build import BuildResult

        return BuildResult((), (), {}, 0, ())

    def fake_write_build_output(result, output_dir, metrics, accessions):  # noqa: ANN001, ARG001
        output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("edgar.financials.build.run_build", fake_run_build)
    monkeypatch.setattr("edgar.financials.build.write_build_output", fake_write_build_output)
    monkeypatch.setattr(
        "edgar.cli.require_database_at_head",
        lambda _url: None,
    )
    monkeypatch.setattr("edgar.cli.create_db_engine", lambda _url: MagicMock())

    out = tmp_path / "build-out"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "build",
            "--accessions-file",
            str(acc_file),
            "--output-dir",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert seen == [
        (
            "0000104169-24-000056",
            "0000320193-24-000123",
        ),
    ]


def test_resolve_build_accessions_file(tmp_path: Path) -> None:
    from edgar.financials.build import resolve_build_accessions

    repo = Path(__file__).resolve().parents[2]
    acc_file = tmp_path / "list.txt"
    acc_file.write_text("0000104169-24-000056\n", encoding="utf-8")
    assert resolve_build_accessions(
        repo,
        accession=None,
        accessions_file=acc_file,
    ) == ("0000104169-24-000056",)
