# Data Cleaning Report

## Overview

- **Rows:** 9 -> 7 (-2)
- **Columns:** 7 -> 7 (+0)
- **Duplicate rows removed:** 2
- **Rows dropped for missing values:** 0
- **Cells imputed:** 4

## Renamed columns

- `Customer ID ` -> `customer_id`
- ` Full Name ` -> `full_name`
- `Signup Date` -> `signup_date`
- `Age` -> `age`
- `Spend ($)` -> `spend`
- `Active?` -> `active`
- `Notes` -> `notes`

## Inferred types

- `customer_id` -> `Int64`
- `signup_date` -> `datetime64[ns]`
- `age` -> `Int64`
- `spend` -> `float64`
- `active` -> `boolean`

## Missing values per column

| Column | Before | After |
| --- | ---: | ---: |
| `full_name` | 1 | 1 |
| `signup_date` | 2 | 3 |
| `age` | 2 | 0 |
| `spend` | 2 | 0 |
| `notes` | 5 | 4 |
