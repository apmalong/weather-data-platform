import duckdb
import pytest

from wx import config, reset


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("WX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("WX_WAREHOUSE", raising=False)
    cfg = config.load()
    (cfg.data_dir / "raw" / "by_station").mkdir(parents=True)
    (cfg.data_dir / "raw" / "by_station" / "CAN06158731.csv.gz").write_bytes(b"x")
    (cfg.data_dir / "report.html").write_text("x")
    (cfg.data_dir / "notes.txt").write_text("not ours")
    conn = duckdb.connect(str(cfg.warehouse))
    conn.execute("create schema narratives; create table narratives.daily (x int);"
                 "create schema marts; create table marts.keep (x int)")
    conn.close()
    return cfg


def test_default_removes_the_warehouse_and_keeps_downloads(cfg):
    reset.reset(cfg)
    assert not cfg.warehouse.exists()
    assert (cfg.data_dir / "raw" / "by_station" / "CAN06158731.csv.gz").exists()


def test_all_removes_only_what_the_pipeline_creates(cfg):
    reset.reset(cfg, everything=True)
    assert not cfg.warehouse.exists() and not (cfg.data_dir / "raw").exists()
    assert not (cfg.data_dir / "report.html").exists()
    assert (cfg.data_dir / "notes.txt").exists()  # someone else's file stays


def test_narratives_only_drops_the_cache(cfg):
    assert reset.reset(cfg, narratives=True) == ["narratives schema"]
    conn = duckdb.connect(str(cfg.warehouse), read_only=True)
    schemas = {r[0] for r in conn.execute("select schema_name from information_schema.schemata").fetchall()}
    assert "narratives" not in schemas and "marts" in schemas


def test_nothing_to_reset_is_reported(cfg):
    reset.reset(cfg, everything=True)
    assert reset.describe(cfg, everything=True, narratives=False) == ""
