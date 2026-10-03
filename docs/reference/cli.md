# CLI reference: `wx`

The pipeline's command line, installed by `uv sync` (`app/wx/cli.py`). Run as `uv run wx <command>`.
Every command reads `config/pipeline.yml` and loads `.env` if present (it never overrides variables
already set). Each run is recorded in `ops.runs`; a failure prints one line (`-v` adds the traceback)
and exits 1.

| Command | Stage | Does | Options |
|---|---|---|---|
| `wx ingest` | 1 | Downloads NOAA's files, resolves stations, loads `raw` and `config` ([reference](app/ingest.md)) | `--force`: reload files even if unchanged, and accept one that removes more than `max_deleted_pct` of a station's rows |
| `wx transform` | 2 | `dbt build`: models, tests, hooks ([reference](dbt/models-and-tests.md)) | `--full-refresh`: rebuild incremental models from raw · `--select <selection>`: any dbt selection |
| `wx narrate` | 3 | Writes and validates narratives for the latest days ([reference](llm/narratives.md)) | `--days N`: override `narratives.days` · `--provider auto\|gemini\|mock` |
| `wx eval` | 3 | Scores a prompt and model on `llm/evals/cases.yml` | `--prompt <file>`: default `narratives.prompt` · `--provider auto\|gemini\|mock` |
| `wx health` | all | Prints one status for the whole pipeline ([reference](app/observe.md)) | `--out <file>`: also write Markdown · `--strict`: exit 1 when the status is ERROR |
| `wx report` | all | Writes the results page | `--out <file>`: default `data/report.html` |
| `wx run` | 1–3 | `ingest`, `transform`, `narrate`, `report` in order; stops at the first failure | |
| `wx reset` | all | Removes what the pipeline built: the warehouse (downloads kept) | `--all`: also downloads and the report · `--narratives`: only the narrative cache · `--yes`: don't ask |

Global options, before the command:

| Option | Does |
|---|---|
| `-v`, `--verbose` | Debug logging and full tracebacks |
| `--explore` | Opens the warehouse read-only in DuckDB's web UI at http://localhost:4213; with a command (`wx --explore run`), after it finishes. Ctrl+C stops it; it holds the warehouse open, so stop it before other commands |

## Environment variables

| Variable | Default | Used for |
|---|---|---|
| `GEMINI_API_KEY` | unset | Gemini narratives; without it `provider: auto` uses the offline mock. Read from the environment or a git-ignored `.env` |
| `WX_CONFIG` | `config/pipeline.yml` | Another config file (experiments) |
| `WX_DATA_DIR` | `data/` | Where downloads, the warehouse and the report go |
| `WX_WAREHOUSE` | `<data dir>/warehouse.duckdb` | Another warehouse file (e.g. a copy to experiment on) |
