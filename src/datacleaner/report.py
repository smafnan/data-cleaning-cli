"""Rendering helpers for :class:`~datacleaner.cleaner.CleaningReport`.

Kept separate from the cleaning logic so that *how we present* a report is
decoupled from *what the report contains*. Supports JSON (machine-readable) and
Markdown (human-readable) output.
"""

from __future__ import annotations

import json

from .cleaner import CleaningReport


def to_json(report: CleaningReport, indent: int = 2) -> str:
    """Serialise the report as pretty-printed JSON."""
    return json.dumps(report.as_dict(), indent=indent, default=str)


def to_markdown(report: CleaningReport) -> str:
    """Render the report as a readable Markdown summary."""
    d = report.as_dict()
    lines: list[str] = ["# Data Cleaning Report", ""]

    lines += [
        "## Overview",
        "",
        f"- **Rows:** {d['rows_before']} -> {d['rows_after']} "
        f"({d['rows_after'] - d['rows_before']:+d})",
        f"- **Columns:** {d['columns_before']} -> {d['columns_after']} "
        f"({d['columns_after'] - d['columns_before']:+d})",
        f"- **Duplicate rows removed:** {d['duplicates_removed']}",
        f"- **Rows dropped for missing values:** {d['rows_dropped_missing']}",
        f"- **Cells imputed:** {d['cells_filled']}",
        "",
    ]

    if d["renamed_columns"]:
        lines += ["## Renamed columns", ""]
        lines += [f"- `{old}` -> `{new}`" for old, new in d["renamed_columns"].items()]
        lines.append("")

    if d["dropped_columns"]:
        lines += ["## Dropped columns (too sparse)", ""]
        lines += [f"- `{c}`" for c in d["dropped_columns"]]
        lines.append("")

    if d["coerced_types"]:
        lines += ["## Inferred types", ""]
        lines += [f"- `{c}` -> `{t}`" for c, t in d["coerced_types"].items()]
        lines.append("")

    # Show only columns that actually had missing values, to keep it readable.
    missing_rows = [
        (col, before, d["missing_after"].get(col, 0))
        for col, before in d["missing_before"].items()
        if before or d["missing_after"].get(col, 0)
    ]
    if missing_rows:
        lines += [
            "## Missing values per column",
            "",
            "| Column | Before | After |",
            "| --- | ---: | ---: |",
        ]
        lines += [f"| `{c}` | {b} | {a} |" for c, b, a in missing_rows]
        lines.append("")

    return "\n".join(lines)
