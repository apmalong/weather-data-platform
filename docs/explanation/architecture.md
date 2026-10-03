# Architecture: why it's built this way

## The workflow, and the folders that follow it

The pipeline has three stages, and the repository is laid out to match:

| Stage | Code | What it runs |
|---|---|---|
| 1. Ingest: NOAA's files → `raw` | `app/wx/ingest/` | |
| 2. Transform: `raw` → `marts` | `app/wx/transform/` | `dbt/` |
| 3. Narrate: `marts` → narratives | `app/wx/narrate/` | `llm/` (prompts, evaluation cases) |
| Across stages: ledger, health, report | `app/wx/observe/` | |

`app/` is the code. `dbt/` and `llm/` are what it runs: artifacts that change more often than the
code around them, are reviewed differently (SQL, prompts), and each belong to one stage.
`config/pipeline.yml` is shared by all three, which is why it sits on its own.

## Python where the outside world is, dbt for everything in between

Python owns the parts that touch the outside world: downloading, reading NOAA's fixed-width files,
change detection, choosing stations from metadata, and calling an LLM. dbt owns every transformation
from raw to marts, with its tests. That split keeps the SQL declarative and testable, and keeps
network and file handling out of it.

The two meet in the warehouse: ingest publishes this run's decisions (stations, window, element rules,
thresholds) into the `config` schema, so dbt needs nothing but the warehouse to build.

## Layers

```
raw (as published, all text) → staging (typed) → intermediate (scope + assessment) → marts
```

Raw keeps NOAA's data exactly as published, with lineage columns, so every downstream value can be
traced back and any downstream step can be rebuilt. Staging types the text but never fails a cast: a
bad value becomes null and gets a status. Intermediate decides what's in scope and assesses every
value. Marts are what people and the narratives read.

## One file, one writer

Everything lands in one DuckDB file. It's free, needs no server, and the data is small (about 220,000
rows for five stations' full history), so a grader reproduces it with `uv sync` and one command. The
cost is that only one process can write at a time, which is why the Airflow DAG runs one task at a
time and why `wx --explore` must be closed before other commands. A client-server warehouse would
remove that limit; the dbt models would carry over with a profile change.

## Everything leaves a record

Every stage writes what it did to the `ops` schema: runs, downloads, loads, checks, station
decisions, dbt results, LLM calls, evaluations. `wx health` and the report read that ledger, so
"what happened and is it OK?" is answered from data, not logs.

Related: [CLI reference](../reference/cli.md), [incremental loading](incremental-and-idempotency.md),
[data quality](data-quality.md).
