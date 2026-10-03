# Orchestration reference: Airflow

Code: `orchestration/` (`Dockerfile`, `docker-compose.yml`, `dags/weather_pipeline.py`). Optional:
everything also runs by hand with `wx`. How to start it: [run on a schedule](../../how-to/run-on-a-schedule.md).

## DAG `weather_pipeline`

| Setting | Value |
|---|---|
| Tasks | `ingest` → `transform` → `narrate` → `health`; each a `BashOperator` running the same `wx` command you'd run by hand |
| Schedule | `0 12 * * *` (12:00 UTC daily) |
| `catchup` | False; unpausing starts the most recent interval at once |
| `max_active_runs` | 1 (DuckDB allows one writer) |
| Retries | 2, 5 minutes apart with exponential backoff; `health` has none |
| Timeouts | ingest 20 min, transform 20 min, narrate 30 min |
| `health` | `wx health --strict --out /opt/wx/data/health_report.md`, trigger rule `all_done`: runs even after a failure, and fails the DAG run when the status is ERROR |

## Container

| | |
|---|---|
| Image | `apache/airflow:3.3.2-python3.12`, plus this project in its own virtualenv at `/opt/wx/.venv` (from `uv.lock`), so Airflow's dependencies and the pipeline's never conflict |
| Mode | `airflow standalone` (API server, scheduler, DAG processor, triggerer in one container); UI at http://localhost:8080, no login |
| Compose project | `weather-data-platform` (named explicitly, so it can't collide with another project's `orchestration/` folder) |
| Mounts | `app/` (read-only; editable install, so code changes need no rebuild), `config/` (read-only), `dbt/`, `llm/` (read-only), the DAG folder (read-only), `data/` |
| Environment | `GEMINI_API_KEY` from `.env` if present; `WX_DATA_DIR=/opt/wx/data` |

Results land in the repo's `data/` folder, the same as a manual run. While a run is going, nothing
else can open the warehouse; a task that finds it open fails with `WarehouseLocked` and retries.
