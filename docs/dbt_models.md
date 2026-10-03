# dbt models and tests

The dbt project (`dbt/`) turns what `wx ingest` loaded into raw and config tables into the marts that
the narratives and the report read. `wx transform` runs `dbt build`: 19 models, 69 data tests, 2 unit
tests and 4 end-of-build hooks (94 nodes). Every column that carries lineage, change or quality
information is described in [metadata_columns.md](metadata_columns.md); the same descriptions are
in the warehouse as column comments.

## Layers

| Layer | Schema | Built as | Job |
|---|---|---|---|
| Sources | `raw`, `config` | Loaded by `wx ingest` | NOAA's files as published (all text), and what ingest decided for this run |
| Staging | `staging` | Views | Type the raw text with `try_cast`, so a bad value becomes null and is flagged downstream instead of failing the build; keep the original text beside it |
| Intermediate | `intermediate` | Views | Scope (which stations and elements) and assessment (a status for every value) |
| Marts | `marts` | Tables; the fact table is incremental | What people and the narratives read |

Model names follow dbt Labs' convention: `stg_<source>__<entity>`, `int_<entity>__<what was done>`,
and `fct_`, `dim_`, `mart_` for marts.

## Models

| Model | Built as | One row per | Purpose | Tests |
|---|---|---|---|---|
| **Staging** | | | | |
| `stg_ghcnd__observations` | view | station × date × element (full history) | Typed observations; text originals kept | not null (date, value); accepted values (NOAA's mflag and qflag codes); element exists in the catalog (warn) |
| `stg_ghcnd__stations` | view | station | Typed station metadata; ID split into country, network and number; elevation `-999.9` → null | unique, not null (ID); latitude and longitude in range |
| `stg_ghcnd__inventory` | view | station × element | Years each station reported each element | unique (station, element); not null (years) |
| `stg_ghcnd__elements` | view | element | The readme's element catalog with unit and scale | unique, not null (element); not null (scale) |
| `stg_ghcnd__countries` | view | country | Country names | (tested on the source) |
| `stg_ghcnd__states` | view | state/province | State names | (tested on the source) |
| `stg_config__run_scope` | view | one row | The window and quality thresholds for this run | exactly one row |
| **Intermediate** | | | | |
| `int_stations__selected` | view | configured city | The station resolved for each city, with its metadata | unique, not null (city, station); not null (country) |
| `int_elements__in_scope` | view | element | Elements the stations report in the window ∩ the readme catalog − exclusions, with their rules from config and a `policy_hash` | unique, not null (element); not null (unit) |
| `int_station_elements__reported` | view | station × element | Years each selected station reports each in-scope element | unique (station, element) |
| `int_observations__assessed` | view | station × date × element | Scaled values with a status: valid, trace, qc_failed, out_of_bounds, inconsistent, unparseable | unique (station, date, element); accepted values (status); **unit test**: an inverted TMAX/TMIN is quarantined, not fatal |
| **Marts** | | | | |
| `fct_observations` | incremental | station × date × element (full history) | Every assessed observation; reprocessed only where NOAA changed something, a rule changed or a station was added; removals kept as tombstones | unique (station, date, element); not null (date); accepted values (status); TMAX ≥ TMIN among usable values (error); TAVG within TMIN–TMAX (warn) |
| `fct_station_day_element` | table | station × day × element in the window | The grid: every expected day is a row, gaps included, with missing / not_reported / not_expected | unique (station, day, element); accepted values (status); **unit test**: snow depth during a snow event is missing, not 0 |
| `mart_station_daily` | table | station × day | One value and status column per element (generated from the elements in scope), plus missing and quarantined lists | unique (station, day) |
| `mart_data_quality` | table | station × element | Completeness, counts per status, latest usable date, freshness | unique (station, element); accepted values (freshness); completeness ≥ 0.9 (warn); **stations fresh** (error) |
| `mart_source_changes` | table | ingest run × station | What NOAA inserted, revised or removed, and how much touched history | none |
| `mart_narrative_input` | table | station × day | The fact sheet (JSON) the narrative model sees, in display units, with compass points; `input_hash` | unique (station, day); not null (input_hash) |
| `dim_station` | table | station | The selected stations with their metadata and elements reported | unique, not null (city, station); city matches config; every configured city has a station |
| `dim_element` | table | element | The elements in scope with labels and rules | unique, not null (element) |

The sources are tested too: unique, not-null keys on every raw table, one row per
station/date/element in `raw.observations`, and every selected station exists in NOAA's metadata.

## The tests

| Kind | Count | What it guards |
|---|---|---|
| `not_null` | 28 | Keys and required columns are present |
| `unique` | 14 | Single-column keys |
| `unique_combination` | 10 | Multi-column keys (the grain of each table) |
| `accepted_values` | 6 | Statuses, freshness labels and NOAA flag codes are known values |
| Singular (custom SQL in `dbt/tests/`) | 4 | TMAX ≥ TMIN; TAVG within range; stations fresh; every city has a station |
| `relationships` | 3 | Selected stations exist in the metadata; cities match config; elements exist in the catalog |
| `within_bounds` | 3 | Latitude, longitude and completeness ranges |
| `single_row` | 1 | The run scope has one row |
| Unit tests | 2 | Snow depth during snow events; inverted TMAX/TMIN |

The generic tests `unique_combination`, `within_bounds` and `single_row` are macros in
`dbt/macros/tests.sql`, so the project needs no dbt packages.

**Source errors are quarantined; tests guard the pipeline.** A bad value from NOAA never fails a
test: it's set aside with a status upstream (`int_observations__assessed`) and counted. The
error-severity tests check what the pipeline guarantees after that, so a failure means a bug in our
code. Judgement calls (TAVG slightly outside its range, completeness below 90%) are warnings. The
one exception by design is freshness: a stale station fails the build, as an alert. It rolls nothing
back, because `mart_data_quality` has nothing downstream.

When a test fails, its failing rows are stored in the `audit` schema (one table per test), and
`audit.all_failures` lists them all in one view. `audit.data_issues` adds quarantined values,
rejected lines and NOAA revisions.

## Hooks

Four macros run at the end of every build (`on-run-end` in `dbt_project.yml`):

| Hook | Writes |
|---|---|
| `record_run_results` | Every invocation and node result to `ops.dbt_runs` / `ops.dbt_node_runs` |
| `persist_source_docs` | Source table and column descriptions as warehouse comments (dbt's `persist_docs` covers models) |
| `audit_failures_view` | `audit.all_failures` |
| `data_issues_view` | `audit.data_issues` |

## Running it

```powershell
uv run wx transform                     # dbt build: models, tests, hooks
uv run wx transform --full-refresh      # rebuild the incremental fact from raw
uv run wx transform --select marts      # any dbt selection
cd dbt; uv run dbt docs generate --profiles-dir .; uv run dbt docs serve --profiles-dir .   # browse lineage and docs
```

`wx transform` reads config that `wx ingest` publishes, so after editing `config/pipeline.yml` run
`wx ingest` first (or `wx run`).
