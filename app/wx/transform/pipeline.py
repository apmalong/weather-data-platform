"""Transform: `dbt build` (models and tests) against the warehouse, recorded in ops.runs.

dbt's own results go to ops.dbt_runs / ops.dbt_node_runs through the project's on-run-end hook,
tagged with this run's id (WX_RUN_ID). The ops connection is closed while dbt runs because DuckDB
allows one writer.
"""

import json
import os
import uuid

from dbt.cli.main import dbtRunner

from wx.config import ROOT, Config
from wx.observe import ops

DBT_DIR = ROOT / "dbt"


class TransformFailed(RuntimeError):
    pass


def _record(cfg: Config, run_id: str, status: str | None = None, details: dict | None = None, error=None) -> None:
    conn = ops.connect(cfg.warehouse)
    try:
        if status is None:
            conn.execute(
                "insert into ops.runs (run_id, command, started_at, status) values (?, 'transform', ?, " "'running')",
                [run_id, ops.now()],
            )
        else:
            conn.execute(
                "update ops.runs set finished_at = ?, status = ?, error = ?, details = ? where run_id = ?",
                [ops.now(), status, error, json.dumps(details or {}), run_id],
            )
    finally:
        conn.close()


def run(cfg: Config, full_refresh: bool = False, select: str | None = None) -> dict:
    run_id = f"{ops.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    _record(cfg, run_id)
    os.environ["WX_WAREHOUSE"] = str(cfg.warehouse.resolve())
    os.environ["WX_RUN_ID"] = run_id
    os.environ.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
    args = ["build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    if full_refresh:
        args.append("--full-refresh")
    if select:
        args += ["--select", select]
    result = dbtRunner().invoke(args)
    statuses: dict[str, int] = {}
    for node in result.result or []:
        status = str(node.status)
        statuses[status] = statuses.get(status, 0) + 1
    details = {"statuses": statuses, "full_refresh": full_refresh}
    if not result.success:
        error = str(result.exception) if result.exception else f"dbt build failed: {statuses}"
        _record(cfg, run_id, "failed", details, error[:1000])
        raise TransformFailed(error)
    _record(cfg, run_id, "success", details)
    return {"run_id": run_id, **details}
