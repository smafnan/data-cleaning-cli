"""Command-line interface for the data cleaner.

Usage example::

    datacleaner clean messy.csv -o clean.csv --report report.md \\
        --missing median --drop-threshold 0.9

The CLI is a thin layer over :func:`datacleaner.cleaner.clean_dataframe`: it
handles argument parsing, file I/O, logging and error reporting, then delegates
all real work to the (pure) cleaning function.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from . import __version__
from .cleaner import CleaningConfig, clean_dataframe
from .report import to_json, to_markdown

logger = logging.getLogger("datacleaner")


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser. Separated out so tests can introspect it."""
    parser = argparse.ArgumentParser(
        prog="datacleaner",
        description="Clean a messy CSV (missing values, wrong types, "
        "duplicates) and emit a summary report.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    clean = sub.add_parser("clean", help="Clean a CSV file.")
    clean.add_argument("input", type=Path, help="Path to the input CSV.")
    clean.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Path for the cleaned CSV (default: <input>.clean.csv).",
    )
    clean.add_argument(
        "--report", type=Path, default=None,
        help="Where to write the summary report. Extension picks the format: "
        ".json -> JSON, anything else -> Markdown. Omit to print to stderr.",
    )
    clean.add_argument(
        "--missing",
        choices=["keep", "drop", "mean", "median", "mode", "constant"],
        default="keep",
        help="How to handle missing values (default: keep as NaN).",
    )
    clean.add_argument(
        "--fill-constant", default="0",
        help="Value used when --missing constant (default: 0).",
    )
    clean.add_argument(
        "--drop-threshold", type=float, default=None,
        help="Drop columns whose missing fraction exceeds this (0-1).",
    )
    clean.add_argument(
        "--datetime-cols", nargs="*", default=[],
        help="Column names to force-parse as datetimes.",
    )
    clean.add_argument(
        "--dup-subset", nargs="*", default=None,
        help="Columns that define a duplicate (default: whole row).",
    )
    clean.add_argument(
        "--no-normalize-columns", action="store_true",
        help="Keep original column names instead of snake_casing them.",
    )
    clean.add_argument(
        "--no-infer-types", action="store_true",
        help="Do not attempt numeric/datetime/boolean coercion.",
    )
    clean.add_argument(
        "--no-drop-duplicates", action="store_true",
        help="Keep duplicate rows.",
    )
    clean.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging."
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> CleaningConfig:
    """Translate parsed CLI args into a :class:`CleaningConfig`."""
    return CleaningConfig(
        normalize_columns=not args.no_normalize_columns,
        missing_strategy=args.missing,
        fill_constant=args.fill_constant,
        drop_threshold=args.drop_threshold,
        infer_types=not args.no_infer_types,
        datetime_columns=tuple(args.datetime_cols),
        drop_duplicates=not args.no_drop_duplicates,
        duplicate_subset=tuple(args.dup_subset) if args.dup_subset else None,
    )


def run_clean(args: argparse.Namespace) -> int:
    """Execute the ``clean`` subcommand. Returns a process exit code."""
    if not args.input.exists():
        logger.error("Input file not found: %s", args.input)
        return 2

    try:
        # `keep_default_na=False` so WE decide what counts as missing, not pandas.
        df = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    except Exception as exc:  # pragma: no cover - depends on file contents
        logger.error("Failed to read CSV '%s': %s", args.input, exc)
        return 2

    if df.empty:
        logger.warning("Input CSV has no rows; nothing to clean.")

    config = _config_from_args(args)
    cleaned, report = clean_dataframe(df, config)

    output = args.output or args.input.with_suffix(".clean.csv")
    try:
        cleaned.to_csv(output, index=False)
    except OSError as exc:
        logger.error("Failed to write output '%s': %s", output, exc)
        return 2
    logger.info("Wrote cleaned data to %s", output)

    # Write or print the report.
    if args.report is not None:
        text = (
            to_json(report)
            if args.report.suffix.lower() == ".json"
            else to_markdown(report)
        )
        args.report.write_text(text, encoding="utf-8")
        logger.info("Wrote report to %s", args.report)
    else:
        # No report path given: still show the human a summary on stderr.
        print(to_markdown(report), file=sys.stderr)

    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point used by the ``datacleaner`` console script and by tests."""
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.command == "clean":
        return run_clean(args)

    parser.error(f"Unknown command: {args.command}")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
