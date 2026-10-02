"""The ops ledger: every stage records what it did in the warehouse's `ops` schema, so a run can be
explained after the fact and health checks have history to compare against (`wx health`, `wx report`).
"""
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import duckdb

DDL = """
create schema if not exists ops;
create table if not exists ops.runs (
    run_id varchar primary key, command varchar, started_at timestamp, finished_at timestamp,
    status varchar, error varchar, details json);
create table if not exists ops.downloads (
    run_id varchar, url varchar, path varchar, http_status integer, bytes bigint, sha256 varchar,
    changed boolean, seconds double, error varchar, downloaded_at timestamp);
create table if not exists ops.loads (
    run_id varchar, dataset varchar, source_file varchar, sha256 varchar, rows_read bigint,
    rows_rejected bigint, rows_inserted bigint, rows_updated bigint, rows_deleted bigint,
    seconds double, loaded_at timestamp);
create table if not exists ops.station_resolution (
    run_id varchar, city varchar, province varchar, station_id varchar, station_name varchar,
    selected boolean, rank integer, reason varchar, resolved_at timestamp);
create table if not exists ops.checks (
    run_id varchar, stage varchar, check_name varchar, subject varchar, severity varchar,
    passed boolean, observed varchar, expected varchar, checked_at timestamp);
"""


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # the warehouse stores naive UTC


class WarehouseLocked(RuntimeError):
    pass


# How another process's lock on the file reads, by platform: DuckDB's own lock (Linux, macOS),
# Windows' sharing violation, and a Windows lock seen through a Docker bind mount.
_LOCKED = ("could not set lock", "being used by another process", "permission denied")


def connect(path) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)  # data/ is git-ignored: absent on a fresh clone
    try:
        conn = duckdb.connect(str(path))
    except duckdb.IOException as exc:
        if any(text in str(exc).lower() for text in _LOCKED):
            raise WarehouseLocked(f"{path} is open in another process (DuckDB allows one writer): stop "
                                  f"`wx --explore`, a DuckDB UI or CLI, or another pipeline run, then retry. "
                                  f"DuckDB said: {str(exc).splitlines()[0]}") from exc
        raise
    conn.execute("set TimeZone = 'UTC'")
    conn.execute(DDL)
    return conn


def connect_read(path) -> duckdb.DuckDBPyConnection:
    """Read-only access for reports. Within one process DuckDB refuses a read-only connection to a
    file another connection already holds read-write (dbt's, after `wx run`), so fall back to that."""
    try:
        return duckdb.connect(str(path), read_only=True)
    except duckdb.ConnectionException:
        return duckdb.connect(str(path))


@contextmanager
def run(conn: duckdb.DuckDBPyConnection, command: str):
    """Record a pipeline run; yields its id and a dict for details to store with it."""
    run_id = f"{now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    details: dict = {}
    conn.execute("insert into ops.runs (run_id, command, started_at, status) values (?, ?, ?, 'running')",
                 [run_id, command, now()])
    try:
        yield run_id, details
    except BaseException as exc:
        conn.execute("update ops.runs set finished_at = ?, status = 'failed', error = ?, details = ? where run_id = ?",
                     [now(), f"{type(exc).__name__}: {exc}"[:1000], json.dumps(details, default=str), run_id])
        raise
    conn.execute("update ops.runs set finished_at = ?, status = 'success', details = ? where run_id = ?",
                 [now(), json.dumps(details, default=str), run_id])


def check(conn, run_id: str, stage: str, name: str, subject: str, passed: bool, observed, expected,
          severity: str = "error") -> bool:
    """Record one data-quality check result; returns whether it passed."""
    conn.execute("insert into ops.checks values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 [run_id, stage, name, subject, severity, passed, str(observed), str(expected), now()])
    return passed
