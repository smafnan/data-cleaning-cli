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


def test_cli_fill_constant_on_numeric_column_stays_numeric(tmp_path: Path):
    # argparse hands --fill-constant through as a plain string (default "0").
    # Filling a numeric column ("Age") with it must not downgrade the column
    # to object dtype with a mix of ints and the literal string "0".
    src = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    _write_messy_csv(src)

    code = main([
        "clean", str(src), "-o", str(out), "--missing", "constant",
        "--fill-constant", "0",
    ])
    assert code == 0

    cleaned = pd.read_csv(out)
    assert pd.api.types.is_integer_dtype(cleaned["age"])
    # The duplicate Alice row is dropped first, leaving Alice/Bob/Carol; Bob's
    # and Carol's missing ages are both filled with the numeric constant 0.
    assert cleaned["age"].tolist() == [30, 0, 0]
