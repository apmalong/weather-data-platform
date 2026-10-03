import subprocess
import sys

import pytest

from wx.observe import ops


def test_connect_creates_the_warehouse_folder(tmp_path):
    """data/ is git-ignored, so on a fresh clone it doesn't exist yet."""
    path = tmp_path / "not" / "there" / "warehouse.duckdb"
    ops.connect(path).close()
    assert path.exists()


def test_failed_run_is_recorded(tmp_path):
    conn = ops.connect(tmp_path / "wh.duckdb")
    try:
        with ops.run(conn, "ingest") as (run_id, details):
            details["stage"] = "download"
            raise RuntimeError("NOAA unreachable")
    except RuntimeError:
        pass
    status, error = conn.execute("select status, error from ops.runs").fetchone()
    assert status == "failed" and error == "RuntimeError: NOAA unreachable"


def test_read_connection_coexists_with_a_writer_in_the_same_process(tmp_path):
    path = tmp_path / "wh.duckdb"
    writer = ops.connect(path)  # like dbt's connection during `wx run`
    reader = ops.connect_read(path)
    assert reader.execute("select count(*) from ops.runs").fetchone() == (0,)
    reader.close()
    writer.close()


def test_a_warehouse_open_elsewhere_says_so(tmp_path):
    """Another process holding the file (wx --explore, the DuckDB CLI) gets a message saying what to do."""
    path = tmp_path / "wh.duckdb"
    ops.connect(path).close()
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import duckdb, sys; c = duckdb.connect(r'{path}'); " "print('ready', flush=True); sys.stdin.read()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        with pytest.raises(ops.WarehouseLocked, match="open in another process"):
            ops.connect(path)
    finally:
        holder.communicate("")
