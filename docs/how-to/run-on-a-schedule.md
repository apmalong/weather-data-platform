# How to run the pipeline on a schedule (Airflow)

Needs Docker, and about 1.3 GB of memory while running.

1. Close anything holding the warehouse: `wx --explore`, a DuckDB CLI or UI. Airflow's tasks can't
   open it otherwise.

2. Build and start Airflow:

   ```powershell
   docker compose -f orchestration/docker-compose.yml up -d --build
   ```

3. Open http://localhost:8080 (no login). Find `weather_pipeline` and switch it on. It runs at once
   for the latest interval, then daily at 12:00 UTC. Use the play button to trigger an extra run.

4. Follow a run in the Grid view; click a task for its log. Results land in `data/` as with a manual
   run, and `data/health_report.md` is rewritten by the last task.

5. Stop it when you're done:

   ```powershell
   docker compose -f orchestration/docker-compose.yml down
   ```

With a `.env` containing `GEMINI_API_KEY`, the narrate task uses Gemini; without one, the mock.

The DAG's settings (tasks, retries, timeouts): [Airflow reference](../reference/orchestration/airflow.md).
