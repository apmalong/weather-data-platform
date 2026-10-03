"""Daily weather pipeline: ingest -> transform -> narrate -> health.

Each task runs the same `wx` command you'd run by hand, so Airflow adds scheduling, retries and run
history without a second code path. NOAA publishes daily; unchanged files are skipped and cached
narratives aren't regenerated, so a run on a quiet day is cheap.

DuckDB allows one writer, so one run at a time and tasks in sequence.
"""

from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

WX = "/opt/wx/.venv/bin/wx"

with DAG(
    dag_id="weather_pipeline",
    schedule="0 12 * * *",  # NOAA's daily update lands around 06:00 UTC
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5), "retry_exponential_backoff": True},
    tags=["weather"],
) as dag:
    ingest = BashOperator(task_id="ingest", bash_command=f"{WX} ingest", execution_timeout=timedelta(minutes=20))
    transform = BashOperator(
        task_id="transform", bash_command=f"{WX} transform", execution_timeout=timedelta(minutes=20)
    )
    # A failed narrative request doesn't invalidate the data: retried, and the next run resumes.
    narrate = BashOperator(task_id="narrate", bash_command=f"{WX} narrate", execution_timeout=timedelta(minutes=30))
    # --strict: the DAG run fails visibly when the report's status is ERROR.
    health = BashOperator(
        task_id="health",
        bash_command=f"{WX} health --strict --out /opt/wx/data/health_report.md",
        retries=0,
        trigger_rule="all_done",
    )

    ingest >> transform >> narrate >> health
