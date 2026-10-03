# Documentation

Organised with [Diátaxis](https://diataxis.fr): four kinds of page, each answering a different need.
Live results from a fresh run: the [results report](https://apmalong.github.io/weather-data-platform/report/)
and [dbt docs](https://apmalong.github.io/weather-data-platform/dbt/), and that run's warehouse to
[query in the browser](https://apmalong.github.io/weather-data-platform/query/). The repository's own [README](https://github.com/apmalong/weather-data-platform#readme) is the entry point: setup, architecture, design decisions
and tradeoffs.

| If you want to… | Read |
|---|---|
| Learn the pipeline by running it | [Tutorial](#tutorial) |
| Get a specific task done | [How-to guides](#how-to-guides) |
| Look up a command, setting, table or rule | [Reference](#reference) |
| Understand why it's built this way | [Explanation](#explanation) |

## Tutorial

- [Getting started](tutorials/getting-started.md): run the pipeline, read the report, query the
  warehouse, and add a sixth city by configuration.

## How-to guides

- [Add a city](how-to/add-a-city.md)
- [Change element rules](how-to/change-element-rules.md): bounds, missing vs. nothing to report, display units
- [Change the narrative prompt](how-to/change-the-prompt.md): version, evaluate, switch
- [Investigate data issues](how-to/investigate-data-issues.md)
- [Run on a schedule with Airflow](how-to/run-on-a-schedule.md)
- [Run the tests and style checks](how-to/run-checks.md)
- [Reset and rebuild](how-to/reset-and-rebuild.md)

## Reference

Grouped like the repository: what's in each folder, and the things that cut across them.

| Folder | Reference |
|---|---|
| `config/` | [Configuration](reference/configuration.md): every key in `pipeline.yml` |
| `app/` | [CLI](reference/cli.md): every `wx` command, option and environment variable |
| `app/wx/ingest/` | [Ingest stage](reference/app/ingest.md): steps, errors, tests |
| `app/wx/observe/` | [Observe](reference/app/observe.md): ops ledger, health rules, report tabs, audit views, reset; [example health report](reference/app/health-report-example.md) |
| `dbt/` | [Models and tests](reference/dbt/models-and-tests.md): every model's grain, purpose and tests; hooks |
| `llm/` and `app/wx/narrate/` | [Narrative stage](reference/llm/narratives.md): prompts, validation checks, providers, evaluation cases |
| `orchestration/` | [Airflow](reference/orchestration/airflow.md): the DAG and the container |
| The warehouse | [Metadata columns](reference/warehouse/metadata-columns.md): lineage, change, quality and run columns in every schema |
| NOAA's data | [NOAA conventions](reference/noaa/conventions.md): units and conversions, special encodings, the mapping to Environment Canada's API |

## Explanation

- [Architecture](explanation/architecture.md): the workflow, the folders, the layers, one warehouse file
- [Station selection](explanation/station-selection.md): cities rather than IDs, and the two-step rule
- [Data quality](explanation/data-quality.md): quarantine vs. tests, absent vs. missing, freshness
- [Incremental loading and idempotency](explanation/incremental-and-idempotency.md)
- [Narratives](explanation/narratives.md): facts, citations, validation, evaluation, repair
- [NOAA and Environment Canada](explanation/noaa-and-environment-canada.md): where the data comes from, its lag, and how the two compare
- [Code style and naming](explanation/code-style.md)
