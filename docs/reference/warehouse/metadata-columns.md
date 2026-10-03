# Warehouse reference: metadata columns

The warehouse (`data/warehouse.duckdb`) holds weather values and also the columns that say where
each value came from, when it last changed, whether it can be used, and what produced it. This page
explains each of those columns. Weather values themselves (`tmax`, `prcp`, …) are described in the
dbt models.

All timestamps are UTC, stored without a time zone.

For the columns dbt builds or reads (`raw`, `config`, `staging`, `intermediate`, `marts`), the
definitions live in dbt: one doc block each in `dbt/models/_docs.md`, referenced from the models'
YAML. `dbt docs generate` shows them with lineage and tests, and every build writes them to the
warehouse as table and column comments, so `describe` and `wx --explore` show them too:

```sql
select table_name, column_name, comment from duckdb_columns()
where schema_name = 'marts' and comment is not null;
```

This page is the overview across all schemas, including the ones Python writes (`ops`,
`narratives`), which dbt doesn't describe.

## Run IDs: which run did this

Every `wx` command gets a run ID such as `20261002T211033-bfaf4e`: the UTC start time plus six
random hex characters. That ID ties a row anywhere in the warehouse to a row in `ops.runs`.

| Column | Where | Meaning |
|---|---|---|
| `_run_id` | every `raw` table | The ingest run that last wrote the row. |
| `run_id` | `ops.*`, `config.*`, `raw.observation_changes`, `narratives.daily`, `marts.mart_source_changes` | The run that wrote the row. |
| `raw_run_id` | `stg_ghcnd__observations` → `fct_observations` | `_run_id` carried from raw, so a fact row leads back to the ingest that last changed it. |
| `invocation_id` | `ops.dbt_runs`, `ops.dbt_node_runs` | dbt's own ID for one `dbt build`. |
| `wx_run_id` | `ops.dbt_runs` | The `wx transform` run that started that dbt build. It connects dbt's ID to ours. |
| `eval_id` | `ops.eval_runs`, `ops.eval_results` | One `wx eval` run. |

## Raw lineage and change detection

The `raw` schema keeps NOAA's data as published, as text, and adds these columns.

| Column | Where | Meaning |
|---|---|---|
| `_source_file` | `raw.observations`, `raw.stations`, `raw.inventory`, `raw.countries`, `raw.states` | The NOAA file the row was read from, such as `CAN06158731.csv.gz`. |
| `_sha256` | reference tables, `raw.documents` | The SHA-256 of the file when it was loaded. NOAA's `Last-Modified` header isn't reliable, so this fingerprint decides whether a file changed. Unchanged files are skipped. |
| `_loaded_at` | reference tables, `raw.documents`, `raw.element_catalog` | When the snapshot was loaded. Reference files are replaced as a whole when they change. |
| `_row_hash` | `raw.observations` | `md5` of the value and its four flags (`value\|mflag\|qflag\|sflag\|obs_time`). Comparing hashes on each load finds revised rows without comparing every column. |
| `_first_loaded_at` | `raw.observations` | When this station, date and element first appeared. It never changes, even when NOAA revises the value. |
| `_last_changed_at` | `raw.observations` | When NOAA last changed the value or its flags. The incremental model reads this as `raw_changed_at` and uses it as its watermark. |
| `change` | `raw.observation_changes` | `insert`, `update` or `delete`: one row for every difference found between loads. |
| `old_value`, `new_value`, `old_flags`, `new_flags` | `raw.observation_changes` | The value and flags (`mflag\|qflag\|sflag\|obs_time`) before and after. `marts.mart_source_changes` summarises these per run and city. |
| `changed_at` | `raw.observation_changes`, `mart_source_changes` | When the change was detected. |
| `line_number`, `line`, `reason` | `raw.rejected_rows` | A row that couldn't be loaded, kept rather than only counted: the line as published (rebuilt from its columns for rows the reader did parse), its line number when the reader rejected it, and why: the parser's error (`MISSING COLUMNS: …`), `row for another station (…)` or `duplicate of … (another row was kept)`. |

## NOAA's own flags

These come from NOAA, one set per observation. The meanings are from section III of `readme.txt`;
the counts are from the five selected stations.

| Column | Meaning | Codes seen here |
|---|---|---|
| `mflag` | Measurement flag: how the value was measured. | `T` trace (6,485 rows), `H` highest or lowest hourly temperature (13,395), `D` total of four six-hour readings (1,654), blank (most) |
| `qflag` | Quality flag. Blank means it passed NOAA's checks; anything else is a failed check. | `I` internal consistency (44), `O` climatological outlier (5), `G` gap (1), `M` megaconsistency (1) |
| `sflag` | Source flag: where NOAA got the value. | `C` Environment Canada, `S` Global Summary of the Day |
| `obs_time` | Time of observation (HHMM), where the source gives one. | Never set for these stations. |

How the pipeline uses them: `qflag` set → `qc_failed`; `mflag = 'T'` → `trace` (value 0, `is_trace`).
The flags are kept on every fact row, so any status can be traced back to the flag behind it.

## Quality columns on facts

| Column | Where | Meaning |
|---|---|---|
| `raw_value` | `int_observations__assessed` → facts | NOAA's integer before scaling (tenths of °C or mm), kept so a scaled value can be checked against the source. |
| `quality_status` | `fct_observations` | `valid`, `trace`, `qc_failed`, `out_of_bounds`, `inconsistent` (TMAX below TMIN that day; both set aside), `unparseable` or `removed_at_source`. See the README's data cleaning section. |
| `status` | `fct_station_day_element` | `quality_status`, plus three statuses for days with no row at all: `missing`, `not_reported` and `not_expected`. Snow depth is `missing` rather than `not_reported` while snow is evidently on the ground (`persistent` in config). |
| `is_usable` | `fct_observations` | True for `valid` and `trace`. Downstream models and narratives use only these values. |
| `is_trace` | facts | A trace amount: stored as 0, reported as "a trace". |
| `is_expected` | `fct_station_day_element` | The inventory says the station reports this element in this year. It separates `missing` (expected, absent) from `not_expected`. |
| `is_deleted` | `fct_observations` | A tombstone: NOAA removed the row. It stays, with status `removed_at_source`, so the removal shows downstream instead of the row silently disappearing. |
| `dbt_loaded_at` | `fct_observations` | When the incremental model last wrote the row. Rows untouched by a build keep their old time. |

## Keys that decide what gets reprocessed

Two hashes let the pipeline redo only what changed, not everything on every run.

| Column | Where | Meaning |
|---|---|---|
| `policy_hash` | `int_elements__in_scope` → `fct_observations` | `md5` of an element's processing rules: scale, `absent_means_zero`, lower and upper bound. When a rule changes in `config/pipeline.yml`, the hash changes, and the next build rewrites only that element's rows. |
| `input_hash` | `mart_narrative_input`, `narratives.*` | `md5` of a station-day's fact sheet, the exact JSON the model sees. A narrative is regenerated only when this changes (a NOAA revision or a rule change), never just because the pipeline ran again. |
| `prompt_version` | `narratives.*`, `ops.llm_calls`, `ops.eval_runs` | The prompt file name plus the first 8 characters of its SHA-256, such as `narrative_v3@1a2b3c4d`. Editing the prompt without renaming it still counts as a new version. |
| `model` | `narratives.*`, `ops.llm_calls` | The model that answered, such as `gemini-3.5-flash-lite` (`mock-template-v1` for the offline mock). |

A cached narrative is reused when `(station_id, obs_date, input_hash, model, prompt_version)` all
match.

## Narrative attempts and validation

| Column | Where | Meaning |
|---|---|---|
| `attempt` | `narratives.daily`, `narratives.validation` | `1` for the first narrative, `2` for the repair after a failed validation. Both are kept. `narratives.latest` shows the latest attempt for each station-day. |
| `cited` | `narratives.daily` | The values the model says it used, returned as structured output. Validation checks them against the facts. |
| `passed`, `failed_checks`, `warnings`, `checks` | `narratives.validation`, `narratives.latest` | The validation result. `checks` holds every check's outcome; `failed_checks` lists only the errors. |
| `provider` | `narratives.daily` | `gemini` or `mock`, or `rule` for the fixed sentence written without a model call when a day has no usable temperature or precipitation. |
| `generated_at`, `validated_at` | `narratives.*` | When the narrative was written, and when it was validated. |

## Run scope published by ingest

Each ingest writes what it decided into the `config` schema, so dbt reads decisions rather than
re-deriving them.

| Table | Columns |
|---|---|
| `config.selected_stations` | `city`, `province`, `station_id`, `station_name`: the result of station resolution. |
| `config.window` | `start_date`, `end_date`: the dates covered downstream of raw. |
| `config.elements` | `excluded`, `absent_means_zero`, `lower_bound`, `upper_bound`, `display_unit`, `display_factor`: the element rules from config. |
| `config.quality` | `freshness_warn_days`, `freshness_error_days`, `volume_change_warn_pct`. |

## Station and element metadata from NOAA

| Column | Where | Meaning |
|---|---|---|
| `network_code` | `stg_ghcnd__stations` | The third character of the station ID (readme section IV). `N`: data from a national meteorological service, Environment Canada here, since v3.35; `1`: CoCoRaHS volunteers; `W`: US WBAN stations, mostly airports; `C`: US Cooperative Network; `0`: unspecified (the old Canadian IDs). |
| `is_gsn` | `stg_ghcnd__stations` | Part of the GCOS Surface Network. |
| `hcn_crn_flag` | `stg_ghcnd__stations` | US Historical or Climate Reference Network membership; blank in Canada. |
| `wmo_id` | stations | The World Meteorological Organization number; one of the station ranking rules. |
| `first_year`, `last_year` | `raw.inventory` | The years a station reported an element. Station selection and `is_expected` both use them. |
| `scale` | `raw.element_catalog`, elements | The multiplier from NOAA's integer to the unit, parsed from the readme ("tenths of" → 0.1). |
| `is_core` | elements | One of NOAA's five core elements (PRCP, SNOW, SNWD, TMAX, TMIN). |
| `is_exact_code` | `stg_ghcnd__elements` | False for readme entries that describe a family of codes (`SN*#`, `WT**`), which can't match an observation directly. |

## The ops ledger

The `ops` schema records what every stage did. `wx health` and the report read it.

| Table | One row per | Key columns |
|---|---|---|
| `ops.runs` | `wx` command | `command`, `status` (`running`, `success`, `failed`), `started_at`, `finished_at`, `error`, and `details` (JSON summary) |
| `ops.downloads` | file fetched | `url`, `http_status`, `bytes`, `sha256`, `changed` (the fingerprint differs from the last download), `error` |
| `ops.loads` | file loaded | `dataset`, `rows_read`, `rows_rejected` (unparseable, another station's rows or duplicates), `rows_inserted`, `rows_updated`, `rows_deleted` |
| `ops.checks` | check run outside dbt | `stage`, `check_name`, `subject`, `severity` (`error` or `warn`), `passed`, `observed`, `expected` |
| `ops.station_resolution` | candidate station per city | `selected`, `rank` (among stations that qualify), `reason` |
| `ops.dbt_runs`, `ops.dbt_node_runs` | dbt build, and model or test within it | `status`, `execution_seconds`, `rows_affected`, `failures` (rows a test found), `message` |
| `ops.llm_calls` | Gemini request | `station_days` (sent), `returned`, `input_tokens`, `output_tokens`, `attempts`, `waited_seconds` (rate-limit waits), `status`, `notes` |
| `ops.eval_runs`, `ops.eval_results` | `wx eval` run, and case within it | `cases`, `passed`, `error_failures`, `style_issues`, `avg_chars`; per case `details` (each check's evidence) |

## The `audit` schema

dbt stores the failing rows of each data test in a table here, named after the test (for example
`audit.assert_tmax_not_below_tmin`). An empty table means the test passed. Each build replaces these
tables, so they show the latest build only.

`audit.all_failures` is a view over all of them, rebuilt by an `on-run-end` hook after every build:

| Column | Meaning |
|---|---|
| `test_name` | The dbt test. |
| `tested` | The model or source it tests. |
| `severity` | `error` (fails the build) or `warn` (reported only). |
| `failing_row` | The failing row as JSON. Each test's table has its own columns, so JSON is the common shape. |

It covers only the tests the project defines now, so a renamed or removed test's leftover table
can't show stale failures. Empty means every test passed.

`audit.data_issues`, rebuilt by the next hook, lists every data problem from wherever it's kept, one
row per issue: `issue_type` (`quarantined`, `rejected_row`, `revised_by_noaa`, `test_failure`),
`severity` (`info` for issues the pipeline already handles, `warn`, `error`), `station_id`, `city`,
`obs_date`, `element`, `value`, `reason`, `found_in` (the table to look in for detail) and
`detected_at`.
