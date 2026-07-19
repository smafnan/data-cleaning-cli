"""Unit tests for the cleaning pipeline.

These tests pin down the *behavioural contract* of the cleaner: each one targets
a single guarantee (type coercion, missing handling, duplicates, etc.) so a
failure points straight at the broken step.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from datacleaner import CleaningConfig, clean_dataframe


def test_normalizes_column_names():
    df = pd.DataFrame({"First Name ": [1], "E-mail!": [2]})
    cleaned, report = clean_dataframe(df, CleaningConfig())
    assert list(cleaned.columns) == ["first_name", "e_mail"]
    assert report.renamed_columns == {"First Name ": "first_name", "E-mail!": "e_mail"}


def test_duplicate_normalized_names_are_made_unique():
    df = pd.DataFrame([[1, 2]], columns=["A", "a"])
    cleaned, _ = clean_dataframe(df, CleaningConfig())
    assert len(set(cleaned.columns)) == 2  # no collision


def test_standardizes_missing_tokens():
    df = pd.DataFrame({"x": ["1", "NA", "n/a", "", "4"]})
    cleaned, report = clean_dataframe(
        df, CleaningConfig(drop_duplicates=False)
    )
    # "NA"/"n/a"/"" became NaN, leaving 2 valid numeric values.
    assert report.missing_before["x"] == 3
    assert cleaned["x"].isna().sum() == 3


def test_infers_integer_column():
    df = pd.DataFrame({"age": ["10", "20", "30"]})
    cleaned, report = clean_dataframe(df, CleaningConfig(drop_duplicates=False))
    assert report.coerced_types["age"] == "Int64"
    assert cleaned["age"].tolist() == [10, 20, 30]


def test_infers_float_column():
    df = pd.DataFrame({"price": ["1.5", "2.0", "3.25"]})
    cleaned, report = clean_dataframe(df, CleaningConfig(drop_duplicates=False))
    assert report.coerced_types["price"] == "float64"


def test_does_not_coerce_mixed_column():
    # "abc" cannot become numeric, so the column stays object and is untouched.
    df = pd.DataFrame({"code": ["1", "2", "abc"]})
    cleaned, report = clean_dataframe(df, CleaningConfig(drop_duplicates=False))
    assert "code" not in report.coerced_types
    assert cleaned["code"].tolist() == ["1", "2", "abc"]


def test_infers_boolean_column():
    df = pd.DataFrame({"active": ["yes", "no", "YES", "No"]})
    cleaned, report = clean_dataframe(df, CleaningConfig(drop_duplicates=False))
    assert report.coerced_types["active"] == "boolean"
    assert cleaned["active"].tolist() == [True, False, True, False]


def test_forced_datetime_column():
    df = pd.DataFrame({"d": ["2021-01-01", "2021-02-15"]})
    cfg = CleaningConfig(datetime_columns=("d",), drop_duplicates=False)
    cleaned, report = clean_dataframe(df, cfg)
    assert report.coerced_types["d"] == "datetime64[ns]"
    assert pd.api.types.is_datetime64_any_dtype(cleaned["d"])


def test_forced_datetime_column_preserves_existing_missing_values():
    # A forced datetime column that already had a gap should still coerce
    # cleanly when every non-missing value parses under one format.
    df = pd.DataFrame({"d": ["2021-01-01", "", "2021-03-03"]})
    cfg = CleaningConfig(datetime_columns=("d",), drop_duplicates=False)
    cleaned, report = clean_dataframe(df, cfg)
    assert report.coerced_types["d"] == "datetime64[ns]"
    assert cleaned["d"].isna().sum() == 1


def test_forced_datetime_coercion_guards_against_new_missing_values():
    # "15-05-2021" cannot be parsed under the format pandas infers from the
    # first value ("2021-03-01"), so naive coercion would silently turn it
    # into NaT -> a *new* missing value. The guard must refuse the coercion,
    # mirroring the numeric path's "no new NaNs" rule, instead of losing data.
    df = pd.DataFrame({"d": ["2021-03-01", "15-05-2021"]})
    cfg = CleaningConfig(datetime_columns=("d",), drop_duplicates=False)
    cleaned, report = clean_dataframe(df, cfg)
    assert "d" not in report.coerced_types
    assert cleaned["d"].tolist() == ["2021-03-01", "15-05-2021"]
    assert cleaned["d"].isna().sum() == 0
    # missing_before/missing_after must agree: no new NaNs were introduced.
    assert report.missing_before["d"] == report.missing_after["d"] == 0


def test_drops_duplicate_rows():
    df = pd.DataFrame({"a": ["1", "1", "2"], "b": ["x", "x", "y"]})
    cleaned, report = clean_dataframe(df, CleaningConfig())
    assert report.duplicates_removed == 1
    assert len(cleaned) == 2


def test_duplicate_subset_keys_on_one_column():
    df = pd.DataFrame({"id": ["1", "1", "2"], "note": ["a", "b", "c"]})
    cfg = CleaningConfig(duplicate_subset=("id",))
    cleaned, report = clean_dataframe(df, cfg)
    assert report.duplicates_removed == 1
    assert cleaned["id"].tolist() == [1, 2]


def test_missing_strategy_drop():
    df = pd.DataFrame({"x": ["1", "", "3"]})
    cfg = CleaningConfig(missing_strategy="drop", drop_duplicates=False)
    cleaned, report = clean_dataframe(df, cfg)
    assert report.rows_dropped_missing == 1
    assert len(cleaned) == 2


def test_missing_strategy_median():
    df = pd.DataFrame({"x": ["1", "", "3"]})
    cfg = CleaningConfig(missing_strategy="median", drop_duplicates=False)
    cleaned, report = clean_dataframe(df, cfg)
    assert cleaned["x"].isna().sum() == 0
    assert cleaned["x"].tolist() == [1.0, 2.0, 3.0]  # median of {1,3} = 2
    assert report.cells_filled == 1


def test_missing_strategy_constant():
    df = pd.DataFrame({"name": ["a", "", "c"]})
    cfg = CleaningConfig(
        missing_strategy="constant", fill_constant="UNKNOWN", drop_duplicates=False
    )
    cleaned, _ = clean_dataframe(df, cfg)
    assert cleaned["name"].tolist() == ["a", "UNKNOWN", "c"]


def test_drop_threshold_removes_sparse_column():
    df = pd.DataFrame({
        "keep": ["1", "2", "3", "4"],
        "sparse": ["", "", "", "9"],  # 75% missing
    })
    cfg = CleaningConfig(drop_threshold=0.5, drop_duplicates=False)
    cleaned, report = clean_dataframe(df, cfg)
    assert "sparse" in report.dropped_columns
    assert "sparse" not in cleaned.columns


def test_input_dataframe_not_mutated():
    df = pd.DataFrame({"A": ["1", "1"]})
    original = df.copy()
    clean_dataframe(df, CleaningConfig())
    pd.testing.assert_frame_equal(df, original)


def test_empty_dataframe_is_safe():
    df = pd.DataFrame()
    cleaned, report = clean_dataframe(df, CleaningConfig())
    assert cleaned.empty
    assert report.rows_after == 0


def test_full_pipeline_end_to_end():
    """A messy frame exercising every step at once."""
    df = pd.DataFrame({
        " ID ": ["1", "1", "2", "3"],
        "Active?": ["yes", "yes", "no", "n/a"],
        "Score": ["10", "10", "", "30"],
    })
    cfg = CleaningConfig(missing_strategy="constant", fill_constant=0)
    cleaned, report = clean_dataframe(df, cfg)
    assert list(cleaned.columns) == ["id", "active", "score"]
    assert report.duplicates_removed == 1  # the repeated id=1 row
    assert cleaned["id"].dtype == "Int64"
    assert cleaned["score"].isna().sum() == 0  # filled by constant
