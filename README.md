# datacleaner — a defensive CSV cleaning CLI

> **AI Engineer Roadmap — Project 0.1**
> *Teaches: pandas, NumPy, defensive coding, argparse.*
> *Done when: you can clean an unfamiliar dataset end to end without Googling pandas syntax every two minutes.*

`datacleaner` takes a messy CSV — missing values, inconsistent types, duplicate
rows, ragged whitespace, a dozen different ways of writing "missing" — and
produces a **clean CSV plus a structured summary report** of everything it did
and why.

It is built to be *honest*: every transformation is recorded, and it never
fabricates data it can't justify (e.g. it won't mode-impute a free-text name).

---

## Why this design

| Principle | How it shows up in the code |
| --- | --- |
| **Pure core, thin shell** | All cleaning lives in `clean_dataframe()` which does no I/O. The CLI only parses args and reads/writes files. This makes the logic trivially unit-testable and reusable in notebooks. |
| **Defensive coercion** | A column is only converted to a new type if the conversion introduces **no new missing values**. A column that merely *looks* numeric is left untouched rather than silently corrupted. |
| **Observable** | Every run returns a `CleaningReport` (rows/cols before & after, renamed columns, inferred types, per-column missing counts, duplicates removed, cells imputed). |
| **No silent data invention** | `mean`/`median` imputation only touches numeric columns; text/categorical columns are left missing rather than filled with a fake mode. |
| **Version-robust** | Works across the `object` → `StringDtype` change in modern pandas via a single `_is_textual()` helper. |

---

## Installation

Requires Python 3.10+.

```bash
# from the project root
python -m venv .venv
source .venv/bin/activate         # Windows: .\.venv\Scripts\activate
pip install -e ".[dev]"           # installs the package + pytest
```

This registers a `datacleaner` console command.

## Usage

```bash
datacleaner clean INPUT.csv [options]
```

Common examples:

```bash
# Clean with sensible defaults; prints a Markdown summary to stderr,
# writes INPUT.clean.csv next to the input.
datacleaner clean sample_data/messy.csv

# Impute missing numbers with the column median, force-parse a date column,
# and save a JSON report.
datacleaner clean sample_data/messy.csv \
    -o cleaned.csv \
    --report report.json \
    --missing median \
    --datetime-cols signup_date

# Drop any row with a missing value, and drop columns that are >90% empty.
datacleaner clean sample_data/messy.csv --missing drop --drop-threshold 0.9
```

### Options

| Flag | Description |
| --- | --- |
| `-o, --output PATH` | Output CSV path (default `<input>.clean.csv`). |
| `--report PATH` | Report path. `.json` → JSON, anything else → Markdown. Omit to print to stderr. |
| `--missing {keep,drop,mean,median,mode,constant}` | Missing-value strategy (default `keep`). |
| `--fill-constant VALUE` | Value used with `--missing constant`. |
| `--drop-threshold FLOAT` | Drop columns whose missing fraction exceeds this (0–1). |
| `--datetime-cols COL ...` | Columns to force-parse as datetimes. |
| `--dup-subset COL ...` | Columns that define a duplicate (default: whole row). |
| `--no-normalize-columns` | Keep original column names. |
| `--no-infer-types` | Skip numeric/datetime/boolean coercion. |
| `--no-drop-duplicates` | Keep duplicate rows. |
| `-v, --verbose` | Verbose logging. |

You can also run it as a module: `python -m datacleaner clean ...`.

---

## What the pipeline does (in order)

1. **Normalise column names** — `"Customer ID " → "customer_id"`, de-duplicated.
2. **Strip whitespace** from every string cell.
3. **Standardise missing markers** — `""`, `NA`, `n/a`, `null`, `-`, `?`,
   `unknown`, … all become real `NaN`.
4. **Infer & coerce types** — numeric (`Int64`/`float64`), `boolean`
   (yes/no/true/false/1/0), and datetime — only when safe.
5. **Drop sparse columns** (optional, via `--drop-threshold`).
6. **Handle missing values** — `keep` / `drop` / `mean` / `median` / `mode` /
   `constant`.
7. **Drop duplicate rows** (optionally keyed on a column subset).

Order matters and is explained in the module docstring of `cleaner.py` — e.g.
missing markers are standardised *before* type inference so a column of
`["1", "2", "NA"]` can still become numeric.

## Example output

Running on the included `sample_data/messy.csv` (9 messy rows) produces a 7-row
clean CSV and this report:

```
## Overview
- Rows: 9 -> 7 (-2)
- Columns: 7 -> 7 (+0)
- Duplicate rows removed: 2
- Cells imputed: 4

## Inferred types
- customer_id -> Int64
- signup_date -> datetime64[ns]
- age         -> Int64
- spend       -> float64
- active      -> boolean
```

---

## Project layout

```
project-0.1-data-cleaning-cli/
├── src/datacleaner/
│   ├── __init__.py      # public API
│   ├── __main__.py      # `python -m datacleaner`
│   ├── cli.py           # argparse + file I/O (the thin shell)
│   ├── cleaner.py       # the pure cleaning pipeline (the core)
│   └── report.py        # JSON / Markdown rendering of a report
├── tests/
│   ├── test_cleaner.py  # unit tests for each pipeline step
│   └── test_cli.py      # end-to-end CLI tests
├── sample_data/messy.csv
├── pyproject.toml
└── requirements.txt
```

## Running the tests

```bash
pytest -q          # 20 tests covering each step + the CLI
```

## License

MIT.
