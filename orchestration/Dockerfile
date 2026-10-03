# Airflow plus this project in its own virtualenv at /opt/wx/.venv, so Airflow's dependencies and the
# pipeline's (dbt, duckdb, google-genai) never conflict. The source is bind-mounted at /opt/wx at run
# time; only the environment is baked in, from the lockfile.
FROM apache/airflow:3.3.2-python3.12

USER root
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
RUN mkdir -p /opt/wx && chown airflow: /opt/wx
USER airflow

WORKDIR /opt/wx
COPY --chown=airflow pyproject.toml uv.lock README.md ./
COPY --chown=airflow app ./app
ENV UV_PROJECT_ENVIRONMENT=/opt/wx/.venv UV_LINK_MODE=copy
RUN uv sync --locked --no-dev
WORKDIR /opt/airflow
