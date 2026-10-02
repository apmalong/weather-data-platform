# Weather data platform

A local pipeline that ingests NOAA GHCN-Daily weather data for the airports of Canada's five largest
metropolitan areas, transforms it with dbt on DuckDB, and writes daily weather narratives with
Gemini, each one validated against the data it describes.

Stations and elements are chosen from NOAA's own metadata, not hard-coded: adding a sixth city is
one line of configuration. Data quality is measured at every layer, bad values are quarantined
rather than silently dropped, and every stage records what it did in an `ops` ledger that one
command turns into a health report.

[![ci](https://github.com/apmalong/weather-data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/apmalong/weather-data-platform/actions/workflows/ci.yml)
CI runs the whole pipeline against live NOAA data on every push, from a clean checkout.

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.12 for
you) and an internet connection. No database server, no Docker, no API key required.

```bash
git clone https://github.com/apmalong/weather-data-platform.git
cd weather-data-platform
uv sync                      # Python 3.12 + locked dependencies
cp .env.example .env         # optional: add GEMINI_API_KEY (free, no billing: aistudio.google.com/apikey)
uv run wx run                # ingest -> dbt build (models + tests) -> narratives -> report: ~1 min (~3 with Gemini)
```

Then open **`data/report.html`** in a browser: the weather, data quality, narratives with their
validation, prompt evaluation and pipeline operations on one page. `uv run wx health` prints the
same health summary in the terminal.

Without `GEMINI_API_KEY`, narratives come from an offline mock provider with the same interface,
so every stage runs end to end; with a key, the same command uses Gemini.

| Command | What it does |
|---|---|
| `wx ingest` | Downloads NOAA's reference files, resolves each configured city to a station from the metadata, downloads and loads its observations (skipping unchanged files) |
| `wx transform` | `dbt build`: 20 models across staging, intermediate and marts, plus 69 data tests. `--full-refresh` rebuilds from raw |
| `wx narrate` | Daily narratives for the last 14 days, in batches, validated against the data; cached, so reruns only do new or revised days |
| `wx eval` | Scores a narrative prompt and model on hard cases (`evals/cases.yml`): `--prompt prompts/narrative_v1.md` |
| `wx health` | One report: runs, checks, dbt tests, data quality, NOAA's revisions, narratives, evaluation. `--strict` exits 1 on errors |
| `wx report` | Writes `data/report.html`: one self-contained page, data embedded, nothing to install or serve |
| `wx run` | `ingest`, `transform`, `narrate`, `report` |

Everything lands in one DuckDB file, `data/warehouse.duckdb`. Open it with the DuckDB CLI or any
SQL client, for example:

```sql
select city, obs_date, tmax, tmin, prcp, prcp_status, snow, wsfg from marts.mart_station_daily
order by obs_date desc, city limit 10;

select city, obs_date, narrative, passed from narratives.latest join marts.dim_station using (station_id)
order by obs_date desc limit 10;
```

To run it on a schedule instead, see [Orchestration](#orchestration-optional).

## Architecture

```mermaid
flowchart LR
  cfg["config/pipeline.yml<br/>cities, window, element policy,<br/>quality thresholds, narratives"]
  noaa[("NOAA GHCN-Daily<br/>stations, inventory, countries,<br/>states, readme, status<br/>+ by_station/*.csv.gz")]
  subgraph ingest["wx ingest (Python)"]
    fetch["download + fingerprint<br/>(skip unchanged)"]
    parse["fixed-width at the readme's<br/>positions; element catalog<br/>parsed from the readme"]
    resolve["resolve cities to stations<br/>from stations + inventory"]
    merge["merge observations,<br/>row-level change log"]
  end
  subgraph wh["DuckDB: data/warehouse.duckdb"]
    raw["raw.*<br/>as published"]
    conf["config.*<br/>this run's scope"]
    stg["staging.*<br/>typed"]
    int["intermediate.*<br/>scope + assessment"]
    marts["marts.*<br/>facts, dims, daily,<br/>quality, changes"]
    narr["narratives.*"]
    ops["ops.*<br/>runs, downloads, loads, checks,<br/>dbt results, LLM calls, evals"]
  end
  llm["Gemini (or offline mock)"]
  cfg --> ingest
  noaa --> fetch --> parse --> raw
  parse --> resolve --> merge --> raw
  resolve --> conf
  raw --> stg --> int --> marts
  conf --> int
  marts -->|"wx narrate:<br/>batched, cached"| llm -->|"validated against<br/>the facts"| narr
  ingest -.-> ops
  marts -.->|"dbt on-run-end"| ops
  narr -.-> ops
  ops -->|"wx health"| report["health report"]
```

| Layer | Models | Purpose |
|---|---|---|
| `raw` | observations (+ change log), stations, inventory, countries, states, element catalog, documents | NOAA's files as published, all text, with lineage |
| `config` | selected_stations, window, elements, quality | This run's scope, published by ingest, so dbt needs nothing but the warehouse |
| `staging` | `stg_ghcnd__*`, `stg_config__run_scope` | Typed and parsed; nothing fails a cast, it fails a test |
| `intermediate` | selected stations, elements in scope, station-element coverage, assessed observations | Scope from the metadata; every value scaled and given a quality status |
| `marts` | `fct_observations` (incremental), `fct_station_day_element`, `mart_station_daily`, `mart_data_quality`, `mart_source_changes`, `mart_narrative_input`, `dim_station`, `dim_element` | What people and the narratives use |

## Design decisions

### Stations come from the metadata

`config/pipeline.yml` lists cities, not station IDs:

```yaml
cities:
  - {city: Toronto, province: 'ON'}
  - {city: Montreal, province: 'QC'}
  ...
```

For each city, `wx ingest` searches `ghcnd-stations.txt` for stations in that province whose name
starts with the city, then applies four rules:

1. **An airport:** the name matches `' A$'`, Environment Canada's convention for airport stations.
   That excludes, for example, `CALGARY INT'L CS`, a climate station.
2. **Covers the window:** `ghcnd-inventory.txt` shows TMAX, TMIN and PRCP reported across the
   configured window. That excludes retired airports (Toronto Buttonville, the old Mirabel) and
   current Montréal-Mirabel, which reports no precipitation.
3. **Prefer the international airport** when several remain (Calgary International over Springbank),
   then a WMO ID, more elements, the longer record.
4. **Every candidate and the reason it won or lost** is recorded in `ops.station_resolution`.

This resolves exactly the five airports in the brief. Adding a sixth city is one line,
`- {city: Edmonton, province: 'AB'}`, and nothing else changes: the station, its elements, the dbt
models, the data tests and the narratives all follow (`tests/test_resolve.py` covers this). A city
can also pin `station_id`, which must still pass the rules.

**NOAA changed the station IDs the day before this brief arrived.** GHCN-Daily v3.35 (October 1,
2026) renamed every Environment Canada station from network code `0` to `N`, so Toronto Pearson is
now `CAN06158731`, not `CA006158731` as listed in the brief, and reloaded their full histories.
The old `CA0…` files are still on the server but are absent from the metadata, stopped updating on
April 28, 2024 (when Environment Canada's feed to NOAA broke), and report gusts in other units than
the readme specifies (km/h and tens of degrees). Resolving from the metadata naturally selects the
current files:

| City | Brief's file (stale) | Resolved from the metadata |
|---|---|---|
| Toronto | `CA006158731` (ends 2024-04-28) | `CAN06158731` (to 2026-09-29) |
| Montréal | `CA007025251` (ends 2024-04-28) | `CAN07025251` |
| Vancouver | `CA001108395` (ends 2025-08-24) | `CAN01108395` |
| Calgary | `CA003031092` (ends 2024-04-28) | `CAN03031092` |
| Ottawa | `CA006106001` (ends 2024-04-28) | `CAN06106001` |

### Elements come from the inventory and the readme

No element list is hard-coded. The elements in scope are those the selected stations report in the
inventory during the window, intersected with the elements the readme defines. The readme's element
section is parsed into a catalog with each element's unit and scale (`Maximum temperature (tenths of
degrees C)` gives scale 0.1, unit °C; `Snowfall (mm)` gives scale 1), so values are converted
correctly without per-element code. These stations report TMAX, TMIN, TAVG, PRCP, SNOW, SNWD, WDFG
and WSFG; not AWND, which the brief lists as common. A station that starts reporting a new element,
or a new city that reports different ones, adds columns to `mart_station_daily` automatically: the
pivot is generated from the warehouse at build time.

The fixed-width layouts are also checked against the readme: before parsing anything, ingest reads
the column tables in the downloaded readme and stops if NOAA has changed a layout.

### Data quality: detect, quarantine, measure, surface

| Layer | What is checked |
|---|---|
| Download | HTTP status, non-empty, gzip integrity, content fingerprint |
| Load | Readme layouts unchanged; rows parse; rows belong to the file's station; no duplicate station/date/element |
| Staging | Dates and values parse; quality and measurement flags are codes the readme defines; coordinates in range |
| Intermediate | Each value gets a status: `valid`, `trace`, `qc_failed` (NOAA's quality flag set), `out_of_bounds` (outside physical bounds in config), `unparseable` |
| Marts | Every station × day × element in the window gets a status, so gaps are countable rows; TMAX ≥ TMIN; TAVG within [TMIN, TMAX]; completeness; freshness per station |
| Narratives | Every narrative validated against its facts (below) |

Nothing is dropped silently: a value that fails a check stays in `fct_observations` with the reason.

**Absent doesn't always mean missing.** Environment Canada only reports a peak gust above about
31 km/h, and snow depth only when there is snow. Treating those absences as missing data would make
the completeness report wrong and the narratives say false things ("no wind data"). In config,
`absent_means_zero: [WDFG, WSFG, SNWD]` makes them `not_reported` ("nothing to report") instead of
`missing`. The freshness test found this the hard way: snow depth looked five months stale in
September. Freshness is now judged only on elements that are reported every day.

**Trace amounts** (`mflag T`) are stored as 0 but keep their status, so a narrative says "a trace
of rain", never "no rain".

### Incremental by change, not by date

NOAA revises past values, adds quality flags later, and backfills gaps: v3.35 reloaded 17 months of
Canadian data at once. Loading only "dates after the last load" would silently miss all of that.

- **Files:** every download is fingerprinted (SHA-256). An unchanged file isn't parsed again.
  NOAA's `Last-Modified` header can't be used for this: the frozen `CA0…` files show yesterday's date.
- **Rows:** a changed file is merged row by row. New, changed and vanished rows are applied and
  logged in `raw.observation_changes`; `mart_source_changes` counts NOAA's revisions per run.
- **dbt:** `fct_observations` is incremental and reprocesses only rows NOAA changed (from the change
  log, removals as tombstones), rows of an element whose policy changed in config (bounds, scale,
  absent rule), and stations or elements newly in scope. Verified on a copy of the warehouse: four
  simulated NOAA changes rewrote exactly four rows; changing TMAX's upper bound rewrote only TMAX's
  rows. `--full-refresh` is needed only when model SQL itself changes.
- **Narratives:** cached by a fingerprint of their input facts, the model and the prompt version, so
  a narrative is regenerated only when its facts change.

### Narratives

`wx narrate` reads `marts.mart_narrative_input`, one fact sheet per station-day built only from the
marts: each fact has a label, a value in display units (gusts in km/h, snow in cm, set in config)
and its status. Requests carry 10 station-days at a time, and Gemini returns structured JSON: the
narrative plus every figure it used and which element it came from.

- **The connector:**
  - **Key:** read only from the environment or a git-ignored `.env`; never logged.
  - **Models:** tried in configured order. A model retired for the key falls through to the next
    (`gemini-2.5-flash` was already retired for new keys while this was built).
  - **Free-tier limits:** they're per project, shown only in AI Studio and liable to change, so the
    connector paces requests, waits the delay the API asks for on a per-minute 429, and on an
    exhausted daily quota moves to the next model and then stops cleanly. The cache means the next
    run resumes where it stopped.
  - **Graders' keys:** the same code path runs with any key. Without one it uses the mock.
- **Validation** (the bonus "compare narratives against source data"), on every narrative before it's stored:

  | Check | Fails when |
  |---|---|
  | `cited_values_match` | a figure the model says it used doesn't match the fact it names |
  | `cited_only_usable` | it cites a value that failed quality checks or wasn't reported |
  | `numbers_grounded` | any number in the text doesn't match a usable fact (rounding allowed) |
  | `no_invented_topics` | it mentions things it wasn't given: forecasts, humidity, cloud, records… |
  | `no_false_gaps` | it calls a reading missing when the reading was usable |

  Plus warnings for unmentioned temperatures, unacknowledged gaps and length.

- **Evaluation:** `wx eval` runs a prompt on 11 hard cases from the real data (missing temperatures,
  trace rain, a 107 km/h gust, 46 cm of snow in Toronto, quarantined snow values, −28.5 °C, 118 mm of
  rain, a calm day, a trace of snow in Montréal in June) and stores the results for comparison.
  It drove the current prompt:

  | Prompt | Factual checks | Style issues | Length |
  |---|---|---|---|
  | `narrative_v1` | 11/11 (but once called present precipitation "missing"; see below) | 18 ("degrees C", "58.0 km/h", template phrasing) | 156 chars |
  | `narrative_v2` (current) | 11/11 | 0 | 126 chars |

  Evaluation also found a gap in validation itself: v1 once wrote "temperatures and precipitation
  were missing" when precipitation was a valid 0 mm, and no check caught it. That's why
  `no_false_gaps` exists. It also shows the limits of a prompt: on one run v2 left out that
  Vancouver's temperatures were missing, which `acknowledges_gaps` flags as a warning.

### Observability

Every stage writes to the `ops` schema: `runs`, `downloads`, `loads`, `checks`,
`station_resolution`, `dbt_runs` and `dbt_node_runs` (from a dbt `on-run-end` hook), `llm_calls`
(tokens, latency, retries, model) and `eval_runs`/`eval_results`. `wx health` turns them into one
report with an overall status, the reasons for it, and per-stage detail. See
[docs/health_report.md](docs/health_report.md) for an example.

`wx report` puts it all on one page for people: an overview with the health status; the weather per
city (temperature, precipitation and snowfall over 30 days to the whole window, gaps shown as gaps,
or as a table); completeness per city and element and what NOAA changed; every narrative beside the
facts it was written from and its validation checks; prompt versions compared case by case; and dbt
results and LLM calls. It's one HTML file with the data embedded (React from a CDN, no build step),
in light and dark mode. CI publishes it and the health report as artifacts on every run.

## Orchestration (optional)

```bash
docker compose -f orchestration/docker-compose.yml up -d --build    # Airflow standalone
```

Open http://localhost:8080 and trigger `weather_pipeline`: ingest → transform → narrate → health,
daily at 12:00 UTC, one run at a time (DuckDB has one writer). Each task runs the same `wx` command,
so Airflow adds scheduling, retries and history without a second code path. The repo is mounted, so
results land in `./data` as with a manual run.

## Tradeoffs

- **One DuckDB file, one writer.** Simple and free, and the dataset is small (220,000 rows for five
  stations' full history), but stages run in sequence and a long query blocks the pipeline. A
  warehouse such as BigQuery or Postgres removes that limit.
- **Raw keeps full history; the window applies downstream.** Changing the window never needs a
  reload or a full refresh. It costs a little storage.
- **Station selection relies on Environment Canada's naming convention** (`… A` for airports).
  It's documented and tested, and `station_id` pins a station where the convention doesn't hold.
  NOAA truncates names to 30 characters, which can hide the suffix
  (`MONTREAL/PIERRE ELLIOTT TRUDEA`); those entries happen to be retired here.
- **Narratives cover the last 14 days by default,** about 7 requests. Two years for five stations is
  about 365 requests, which may exceed a free-tier key's daily quota; the cache makes that a
  multi-day backfill rather than a failure.
- **The mock provider is deliberately plain.** It proves the pipeline and its validation run end to
  end without a key; it isn't meant to read well.
- **Validation checks facts, not prose.** Style is measured by evaluation, not enforced in production.

## With more time

- **Orchestration:** one Airflow task per dbt model (Astronomer Cosmos) and dbt source freshness
  against the ops ledger.
- **Observability:** feed `ops` into a dashboard and alerts (Grafana, or Elementary for dbt)
  instead of a report; OpenTelemetry traces for LLM calls.
- **Narratives:** a model-graded score for tone and clarity in evaluation (costs quota, so off by
  default); a second-pass "repair" when validation fails; per-city monthly summaries.
- **Data:** cross-check a sample against Environment Canada's API, which would have caught the old
  files' gust units automatically; NOAA's change history (`status.txt`) surfaced in the health report.
- **Scale:** partition `fct_observations` by year; move to a client-server warehouse for parallel stages.

## Repository layout

```
config/pipeline.yml       the only file to edit for scope, policy and narrative settings
src/wx/                   ingest, transform, narrate, eval, health, CLI
src/wx/noaa/              file formats (from the readme), downloads, loading, station resolution
dbt/                      staging -> intermediate -> marts, tests, macros (no packages to install)
prompts/                  narrative prompts, versioned
evals/cases.yml           the evaluation set
orchestration/            optional Airflow (Dockerfile, compose, DAG)
tests/                    unit and integration tests (pytest)
docs/                     example health report
src/wx/report_template.html   the results page (React via CDN, data embedded by `wx report`)
```
