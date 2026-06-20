"""Integration tests for the CLI layer (argument parsing + file I/O)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from datacleaner.cli import main


def _write_messy_csv(path: Path) -> None:
    path.write_text(
        "Name, Age ,Active\n"
        "Alice,30,yes\n"
        "Alice,30,yes\n"   # duplicate
        "Bob,,no\n"        # missing age
        "Carol,NA,YES\n",  # textual missing marker
        encoding="utf-8",
    )


def test_cli_clean_writes_output_and_json_report(tmp_path: Path):
    src = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    rep = tmp_path / "report.json"
    _write_messy_csv(src)

    code = main([
        "clean", str(src), "-o", str(out),
        "--report", str(rep), "--missing", "drop",
    ])
    assert code == 0
    assert out.exists() and rep.exists()

    cleaned = pd.read_csv(out)
    # snake_cased headers; with --missing drop, the duplicate Alice row plus the
    # two rows with a missing age (Bob, Carol) are removed -> only Alice remains.
    assert list(cleaned.columns) == ["name", "age", "active"]
    assert len(cleaned) == 1

    report = json.loads(rep.read_text(encoding="utf-8"))
    assert report["duplicates_removed"] == 1
    assert report["rows_dropped_missing"] >= 1


def test_cli_missing_input_returns_error_code(tmp_path: Path):
    code = main(["clean", str(tmp_path / "does_not_exist.csv")])
    assert code == 2


def test_cli_default_output_path(tmp_path: Path):
    src = tmp_path / "data.csv"
    _write_messy_csv(src)
    code = main(["clean", str(src), "--report", str(tmp_path / "r.md")])
    assert code == 0
    assert (tmp_path / "data.clean.csv").exists()
