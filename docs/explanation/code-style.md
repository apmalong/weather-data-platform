# Code style and naming

Consistent style makes code review about behaviour, not formatting, and CI enforces it so it stays
consistent. Commands: [run the checks](../how-to/run-checks.md).

## Python

Formatted by [black](https://black.readthedocs.io) and linted by ruff, both at 120 characters
(`pyproject.toml`). black owns layout; ruff catches real problems (unused imports, import order, likely
bugs) and doesn't format.

## SQL: Matt Mazur's style guide

The dbt SQL follows [Matt Mazur's SQL style guide](https://github.com/mattm/sql-style-guide), checked by
sqlfluff (`.sqlfluff`): lowercase keywords, trailing commas, one column per line, `inner join` written
out, explicit `as` for aliases, the earlier table first in a join condition, `!=`, single quotes, CTEs
rather than subqueries, and columns qualified whenever there's a join.

Where the guide asks for judgement rather than a rule:

| Guideline | How it's applied |
|---|---|
| Avoid table aliases, except for long names | dbt refs are long, so aliases are used, but as words (`observations`, `stations`), never letters; sqlfluff rejects aliases under 3 characters |
| Meaningful CTE names | By hand (`latest_observation`, `new_station_elements`, `inverted_days`) |
| Explicit boolean conditions (`is_usable = true`) | By hand; no linter rule covers it |
| End with `select * from` the last CTE | Not adopted: models end with their final select, which keeps short models short |
| Columns that are SQL keywords (`value`, `label`) | Kept: they're part of the tables' interface to the report and the narratives |

Jinja blocks (`{% if is_incremental() %}`) don't add an indentation level. The macros in `dbt/macros/`
are mostly Jinja and aren't linted, and neither is SQL inside Python strings.

## Naming

| Thing | Convention | Example |
|---|---|---|
| Staging models | `stg_<source>__<entity>` | `stg_ghcnd__observations` |
| Intermediate models | `int_<entity>__<what was done>` | `int_observations__assessed` |
| Marts | `fct_`, `dim_`, `mart_` | `fct_observations`, `dim_station` |
| Booleans | `is_`, `has_` | `is_usable`, `has_row` |
| Dates and timestamps | `_date`, `_at` | `obs_date`, `changed_at` |
| Lineage columns in raw | leading underscore | `_row_hash`, `_run_id` |
| Stage entry points | `pipeline.py` with `run()` | `wx/ingest/pipeline.py` |

The double underscore separates the parts of a dbt model name: where data came from or what it is,
and what was done to it. A second source would slot in as `stg_eccc__observations` with no clash.
