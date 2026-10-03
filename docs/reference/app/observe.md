# Observe reference: ops ledger, health, report, audit, reset

Code: `app/wx/observe/` (`ops.py`, `health.py`, `report.py` with `report_template.html`, `reset.py`).
These work across every stage. Column-by-column definitions:
[metadata columns](../warehouse/metadata-columns.md).

## Ops ledger (`ops` schema)

Every stage records what it did. Written by the stage itself (`ops.run()`, `ops.check()`), except the
dbt tables, which a dbt `on-run-end` hook writes.

| Table | One row per | Written by |
|---|---|---|
| `ops.runs` | `wx` command run: status `running` → `success` / `failed`, error, JSON summary | every command |
| `ops.downloads` | file fetched: HTTP status, bytes, SHA-256, `changed` | ingest |
| `ops.loads` | file loaded: rows read, rejected, inserted, updated, deleted | ingest |
| `ops.checks` | check outside dbt: `passed`, `observed`, `expected`, severity | ingest |
| `ops.station_resolution` | candidate station per city: selected, rank, reason | ingest |
| `ops.dbt_runs`, `ops.dbt_node_runs` | dbt build, and model or test within it | transform (hook) |
| `ops.llm_calls` | Gemini request: tokens, latency, attempts, waits, status | narrate |
| `ops.eval_runs`, `ops.eval_results` | `wx eval` run, and case within it | eval |

`ops.atomic` runs a multi-statement write in one transaction; `ops.connect` raises `WarehouseLocked`
when another process holds the warehouse.

## Health (`wx health`)

One status for the whole pipeline, with the reasons and a section per stage.
[Example](health-report-example.md).

| Status | When |
|---|---|
| ERROR | The latest run of a stage failed; a station file was refused for removing more than `max_deleted_pct` of its rows; a dbt error-severity test failed; a station is stale; a current narrative failed validation |
| WARN | Lagging data; a station file's row count swung more than `volume_change_warn_pct`; a dbt warning; rejected rows; narratives deferred by the request cap or quota |
| OK | Neither |

`--strict` exits 1 on ERROR (the Airflow DAG's last task uses it). `--out <file>` also writes Markdown.

## Report (`wx report`)

One self-contained HTML file (`data/report.html`): the data is embedded as JSON and rendered with
React from a CDN, so there's nothing to install or serve, but it needs internet to render. Light and
dark mode. Elements appear by their readme labels, not NOAA's codes.

| Tab | Shows |
|---|---|
| Overview | Health status, latest run of each stage, the stations and why they won |
| Weather | Per city, 30 days to the whole window: temperature, precipitation, snowfall, peak gusts with direction (hover); or as a table |
| Data quality | Completeness heat map, the status of every expected day, what NOAA changed |
| Narratives | Each narrative with the facts it was written from and its validation checks |
| Evaluation | Prompt versions compared case by case |
| Operations | dbt node results and LLM calls |

## Audit views (`audit` schema)

Rebuilt by dbt `on-run-end` hooks after every build.

| View | Shows |
|---|---|
| `audit.<test name>` | One table per data test: its failing rows (dbt `store_failures`); empty means it passed |
| `audit.all_failures` | Every failing test row: `test_name`, `tested`, `severity`, `failing_row` (JSON). Only tests the project defines now |
| `audit.data_issues` | Everything wrong with the data: `issue_type` (`quarantined`, `rejected_row`, `revised_by_noaa`, `test_failure`), `severity`, `station_id`, `city`, `obs_date`, `element`, `value`, `reason`, `found_in`, `detected_at` |

## Reset (`wx reset`)

| Command | Removes |
|---|---|
| `wx reset` | The warehouse file (raw, marts, narratives, ops history); downloads are kept |
| `wx reset --all` | Also `data/raw/` (downloads), `data/report.html`, `data/health_report.md` |
| `wx reset --narratives` | Only the `narratives` schema (the narrative cache) |

Only files the pipeline creates are removed, never the whole data folder. Asks first unless `--yes`;
refuses with a clear message if the warehouse is in use.
