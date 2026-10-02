from wx import ops


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
