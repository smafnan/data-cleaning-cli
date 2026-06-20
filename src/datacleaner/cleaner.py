"""Core cleaning logic.

Design goals
------------
* **Pure & testable**: :func:`clean_dataframe` takes a DataFrame and a config,
  and returns a *new* cleaned DataFrame plus a structured report. It performs no
  I/O, so it is trivial to unit-test.
* **Defensive**: every transformation is guarded. We never assume a column is a
  given dtype; we *attempt* coercion and fall back gracefully.
* **Observable**: every change is recorded in :class:`CleaningReport` so the
  caller can show the user exactly what happened and why.

The cleaning pipeline runs in a deliberate order:

    1. Normalise column names            (so later steps address columns reliably)
    2. Strip whitespace from string cells (so "  yes" and "yes" are equal)
    3. Standardise missing-value markers  (so "NA", "n/a", "" all become NaN)
    4. Infer & coerce column types        (so "3"/"3.0" become numbers, etc.)
    5. Handle missing values              (drop or impute, per config)
    6. Drop duplicate rows                (after the data is normalised)

Order matters: e.g. we standardise missing markers *before* type inference,
otherwise a column of ["1", "2", "NA"] would refuse to become numeric.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Strings that, case-insensitively, we treat as "missing". These are the markers
# that show up in real-world exports from spreadsheets, databases and APIs.
DEFAULT_NA_TOKENS: tuple[str, ...] = (
    "",
    "na",
    "n/a",
    "nan",
    "null",
    "none",
    "nil",
    "-",
    "--",
    "?",
    "unknown",
)

# Strategy names for filling missing values.
MissingStrategy = Literal["drop", "mean", "median", "mode", "constant", "keep"]


def _is_textual(series: pd.Series) -> bool:
    """True if a column holds free-form text we may want to clean/coerce.

    Covers both the legacy ``object`` dtype and pandas' newer ``StringDtype``
    (the default for string columns from pandas 3.0 onward), so the pipeline
    behaves identically across pandas versions.
    """
    return series.dtype == object or isinstance(series.dtype, pd.StringDtype)


@dataclass
class CleaningConfig:
    """Everything that controls *how* the data is cleaned.

    Attributes are intentionally explicit (no hidden globals) so a run is fully
    reproducible from a single config object.
    """

    # --- column names ---------------------------------------------------
    normalize_columns: bool = True
    """Lower-case column names, trim them, and replace runs of non-alphanumeric
    characters with a single underscore (``"First Name " -> "first_name"``)."""

    # --- missing values -------------------------------------------------
    na_tokens: tuple[str, ...] = DEFAULT_NA_TOKENS
    """Case-insensitive string tokens to reinterpret as missing (NaN)."""

    missing_strategy: MissingStrategy = "keep"
    """How to handle missing values after type inference:
    ``drop`` row-wise, impute with ``mean``/``median``/``mode``, fill with a
    ``constant`` (see :attr:`fill_constant`), or ``keep`` them as NaN."""

    fill_constant: Any = 0
    """Value used when ``missing_strategy == "constant"``."""

    drop_threshold: float | None = None
    """If set (0–1), drop any column whose missing fraction exceeds this value,
    *before* imputation. ``0.9`` drops columns that are >90% empty."""

    # --- types ----------------------------------------------------------
    infer_types: bool = True
    """Attempt to coerce object columns to numeric / datetime / boolean."""

    datetime_columns: tuple[str, ...] = ()
    """Columns to force-parse as datetimes (matched after normalisation)."""

    # --- duplicates -----------------------------------------------------
    drop_duplicates: bool = True
    """Drop fully-duplicate rows."""

    duplicate_subset: tuple[str, ...] | None = None
    """If set, only these columns define a duplicate (e.g. an id column)."""

    # --- whitespace -----------------------------------------------------
    strip_whitespace: bool = True
    """Trim leading/trailing whitespace from every string cell."""


@dataclass
class CleaningReport:
    """A structured, serialisable record of what cleaning did.

    This is the "summary report" the project requires. It is deliberately plain
    data (dicts/lists/ints) so it can be dumped to JSON or rendered to Markdown
    without any further processing.
    """

    rows_before: int = 0
    rows_after: int = 0
    columns_before: int = 0
    columns_after: int = 0

    renamed_columns: dict[str, str] = field(default_factory=dict)
    dropped_columns: list[str] = field(default_factory=list)
    coerced_types: dict[str, str] = field(default_factory=dict)
    missing_before: dict[str, int] = field(default_factory=dict)
    missing_after: dict[str, int] = field(default_factory=dict)
    duplicates_removed: int = 0
    rows_dropped_missing: int = 0
    cells_filled: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-dict view, suitable for ``json.dump``."""
        return {
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "columns_before": self.columns_before,
            "columns_after": self.columns_after,
            "renamed_columns": self.renamed_columns,
            "dropped_columns": self.dropped_columns,
            "coerced_types": self.coerced_types,
            "missing_before": self.missing_before,
            "missing_after": self.missing_after,
            "duplicates_removed": self.duplicates_removed,
            "rows_dropped_missing": self.rows_dropped_missing,
            "cells_filled": self.cells_filled,
        }


# --------------------------------------------------------------------------- #
# Individual pipeline steps. Each takes (df, config, report), mutates the
# report, and returns a new/modified DataFrame. Splitting them out keeps the
# top-level function readable and makes each step independently testable.
# --------------------------------------------------------------------------- #


def _normalize_column_names(
    df: pd.DataFrame, config: CleaningConfig, report: CleaningReport
) -> pd.DataFrame:
    """Make column names predictable: lower snake_case, de-duplicated."""
    if not config.normalize_columns:
        return df

    def norm(name: object) -> str:
        text = str(name).strip().lower()
        # Replace any run of non-alphanumeric chars with a single underscore.
        cleaned = "".join(ch if ch.isalnum() else "_" for ch in text)
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_") or "column"

    new_names: list[str] = []
    seen: dict[str, int] = {}
    for original in df.columns:
        candidate = norm(original)
        # Guard against collisions after normalisation (e.g. "A" and "a").
        if candidate in seen:
            seen[candidate] += 1
            candidate = f"{candidate}_{seen[candidate]}"
        else:
            seen[candidate] = 0
        new_names.append(candidate)
        if candidate != str(original):
            report.renamed_columns[str(original)] = candidate

    df = df.copy()
    df.columns = new_names
    return df


def _strip_whitespace(
    df: pd.DataFrame, config: CleaningConfig, report: CleaningReport
) -> pd.DataFrame:
    """Trim surrounding whitespace from every object/string cell."""
    if not config.strip_whitespace:
        return df
    df = df.copy()
    for col in df.columns:
        if _is_textual(df[col]):
            # Leaves non-string entries (e.g. NaN) untouched.
            df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
    return df


def _standardize_missing(
    df: pd.DataFrame, config: CleaningConfig, report: CleaningReport
) -> pd.DataFrame:
    """Turn assorted textual 'missing' markers into real NaN."""
    tokens = {t.lower() for t in config.na_tokens}
    df = df.copy()
    for col in df.columns:
        if _is_textual(df[col]):
            # Normalise to object first so we can hold a mix of strings and NaN
            # uniformly, regardless of the incoming string/object dtype.
            df[col] = df[col].astype(object).map(
                lambda v: np.nan
                if isinstance(v, str) and v.strip().lower() in tokens
                else v
            )
    return df


def _coerce_types(
    df: pd.DataFrame, config: CleaningConfig, report: CleaningReport
) -> pd.DataFrame:
    """Best-effort coercion of object columns to better dtypes.

    We only *commit* a coercion when it does not introduce new missing values
    beyond cells that were already missing. That rule prevents us from silently
    destroying data in a column that merely *looks* numeric.
    """
    if not config.infer_types:
        return df

    df = df.copy()
    forced_dt = {c.lower() for c in config.datetime_columns}

    for col in df.columns:
        if not _is_textual(df[col]):
            continue

        original = df[col].astype(object)
        already_missing = original.isna()

        # 1) Forced datetime columns take priority.
        if col in forced_dt:
            parsed = pd.to_datetime(original, errors="coerce")
            df[col] = parsed
            report.coerced_types[col] = "datetime64[ns]"
            continue

        # 2) Try numeric. Succeeds only if no *new* NaNs are created.
        numeric = pd.to_numeric(original, errors="coerce")
        if numeric.isna().equals(already_missing) and not numeric.isna().all():
            # Prefer a nullable integer dtype when every value is whole.
            non_null = numeric.dropna()
            if not non_null.empty and (non_null == non_null.round()).all():
                df[col] = numeric.astype("Int64")
                report.coerced_types[col] = "Int64"
            else:
                df[col] = numeric.astype("float64")
                report.coerced_types[col] = "float64"
            continue

        # 3) Try boolean for clean yes/no-style columns.
        bool_map = {
            "true": True, "false": False,
            "yes": True, "no": False,
            "y": True, "n": False,
            "1": True, "0": False,
            "t": True, "f": False,
        }
        lowered = original.map(
            lambda v: v.strip().lower() if isinstance(v, str) else v
        )
        distinct = set(lowered.dropna().unique())
        if distinct and distinct <= set(bool_map):
            df[col] = lowered.map(bool_map).astype("boolean")
            report.coerced_types[col] = "boolean"
            continue

        # 4) Try datetime as a last resort, but only if it parses the *whole*
        #    column. Pandas is happy to parse stray numbers as dates otherwise.
        #    Probing non-date columns emits a noisy "could not infer format"
        #    warning, which we suppress since a failed probe is expected here.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            parsed = pd.to_datetime(original, errors="coerce")
        if parsed.isna().equals(already_missing) and not parsed.isna().all():
            df[col] = parsed
            report.coerced_types[col] = "datetime64[ns]"
            continue

        # Otherwise: leave it as a string/object column.

    return df


def _drop_sparse_columns(
    df: pd.DataFrame, config: CleaningConfig, report: CleaningReport
) -> pd.DataFrame:
    """Drop columns that are mostly empty, per :attr:`drop_threshold`."""
    if config.drop_threshold is None or len(df) == 0:
        return df
    df = df.copy()
    to_drop: list[str] = []
    for col in df.columns:
        frac_missing = df[col].isna().mean()
        if frac_missing > config.drop_threshold:
            to_drop.append(col)
    if to_drop:
        df = df.drop(columns=to_drop)
        report.dropped_columns.extend(to_drop)
    return df


def _handle_missing(
    df: pd.DataFrame, config: CleaningConfig, report: CleaningReport
) -> pd.DataFrame:
    """Impute or drop missing values according to the chosen strategy."""
    strategy = config.missing_strategy
    if strategy == "keep":
        return df

    df = df.copy()

    if strategy == "drop":
        before = len(df)
        df = df.dropna(axis=0, how="any")
        report.rows_dropped_missing = before - len(df)
        return df

    # Imputation strategies: count cells we fill for the report.
    missing_mask = df.isna()
    report.cells_filled += int(missing_mask.to_numpy().sum())

    for col in df.columns:
        if not df[col].isna().any():
            continue
        series = df[col]
        if strategy == "constant":
            try:
                df[col] = series.fillna(config.fill_constant)
            except (TypeError, ValueError):
                # The constant isn't compatible with this column's dtype
                # (e.g. filling 0 into a boolean/datetime column). Fall back to
                # an object column so the fill always succeeds without crashing.
                df[col] = series.astype(object).fillna(config.fill_constant)
        elif strategy in ("mean", "median"):
            # Only impute numeric columns. We deliberately leave text/categorical
            # columns missing rather than fabricating a value: mode-imputing a
            # name or free-text note would invent data that was never there.
            if pd.api.types.is_numeric_dtype(series):
                value = series.mean() if strategy == "mean" else series.median()
                df[col] = series.fillna(value)
        elif strategy == "mode":
            mode = series.mode(dropna=True)
            if not mode.empty:
                df[col] = series.fillna(mode.iloc[0])

    # Recount cells that are *still* missing so the report is honest.
    report.cells_filled -= int(df.isna().to_numpy().sum())
    return df


def _drop_duplicates(
    df: pd.DataFrame, config: CleaningConfig, report: CleaningReport
) -> pd.DataFrame:
    """Remove duplicate rows, optionally keyed on a subset of columns."""
    if not config.drop_duplicates:
        return df
    before = len(df)
    subset = list(config.duplicate_subset) if config.duplicate_subset else None
    # Guard: ignore subset columns that don't exist after cleaning.
    if subset:
        subset = [c for c in subset if c in df.columns] or None
    df = df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)
    report.duplicates_removed = before - len(df)
    return df


def clean_dataframe(
    df: pd.DataFrame, config: CleaningConfig | None = None
) -> tuple[pd.DataFrame, CleaningReport]:
    """Clean ``df`` according to ``config`` and return ``(cleaned, report)``.

    The input DataFrame is never mutated; every step works on a copy.
    """
    config = config or CleaningConfig()
    report = CleaningReport()

    report.rows_before = len(df)
    report.columns_before = df.shape[1]

    # Pipeline. Order is significant — see the module docstring.
    df = _normalize_column_names(df, config, report)
    df = _strip_whitespace(df, config, report)
    df = _standardize_missing(df, config, report)

    # Capture missing counts *after* markers are standardised but *before*
    # we impute/drop, so "missing_before" reflects the true gaps in the data.
    report.missing_before = {c: int(df[c].isna().sum()) for c in df.columns}

    df = _coerce_types(df, config, report)
    df = _drop_sparse_columns(df, config, report)
    df = _handle_missing(df, config, report)
    df = _drop_duplicates(df, config, report)

    report.missing_after = {c: int(df[c].isna().sum()) for c in df.columns}
    report.rows_after = len(df)
    report.columns_after = df.shape[1]

    logger.info(
        "Cleaned %d->%d rows, %d->%d cols",
        report.rows_before, report.rows_after,
        report.columns_before, report.columns_after,
    )
    return df, report
