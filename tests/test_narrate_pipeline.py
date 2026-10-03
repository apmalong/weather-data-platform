import json

import duckdb
import pytest

from wx import config
from wx.narrate import pipeline
from wx.narrate.providers import MockProvider

FACTS = [{"element": "TMAX", "label": "Maximum temperature", "value": 21.4, "unit": "degrees C", "status": "valid"},
         {"element": "TMIN", "label": "Minimum temperature", "value": 15.3, "unit": "degrees C", "status": "valid"},
         {"element": "PRCP", "label": "Precipitation", "value": 2.0, "unit": "mm", "status": "valid"}]


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("WX_WAREHOUSE", str(tmp_path / "wh.duckdb"))
    cfg = config.load()
    cfg.narratives.batch_size = 2
    conn = duckdb.connect(str(cfg.warehouse))
    conn.execute("create schema marts")
    conn.execute("""create table marts.mart_narrative_input (station_id varchar, city varchar, province varchar,
                    station_name varchar, obs_date date, facts json, input_hash varchar)""")
    for day in range(20, 30):
        conn.execute("insert into marts.mart_narrative_input values ('CAN06158731', 'Toronto', 'ON', "
                     "'TORONTO INTL A', ?, ?, ?)", [f"2026-09-{day}", json.dumps(FACTS), f"h{day}"])
    conn.close()
    return cfg


def test_generates_validates_and_logs(cfg):
    result = pipeline.run(cfg, provider=MockProvider(), days=3)
    assert (result["generated"], result["passed"], result["requests"]) == (3, 3, 2)
    conn = duckdb.connect(str(cfg.warehouse), read_only=True)
    assert conn.execute("select count(*) from narratives.latest where passed").fetchone()[0] == 3
    assert conn.execute("select sum(station_days) from ops.llm_calls").fetchone()[0] == 3


def test_rerun_uses_the_cache_and_revised_facts_regenerate(cfg):
    pipeline.run(cfg, provider=MockProvider(), days=3)
    assert pipeline.run(cfg, provider=MockProvider(), days=3)["generated"] == 0
    conn = duckdb.connect(str(cfg.warehouse))
    conn.execute("update marts.mart_narrative_input set input_hash = 'revised' where obs_date = '2026-09-29'")
    conn.close()
    assert pipeline.run(cfg, provider=MockProvider(), days=3)["generated"] == 1


def test_request_cap_defers_the_rest(cfg):
    cfg.narratives.max_requests_per_run = 1
    result = pipeline.run(cfg, provider=MockProvider(), days=5)
    assert (result["generated"], result["deferred"]) == (2, 3)


def test_days_with_nothing_to_report_skip_the_model(cfg):
    empty = [dict(f, status="missing", value=None) for f in FACTS]
    conn = duckdb.connect(str(cfg.warehouse))
    conn.execute("update marts.mart_narrative_input set facts = ?, input_hash = 'empty' where obs_date = '2026-09-29'",
                 [json.dumps(empty)])
    conn.close()
    result = pipeline.run(cfg, provider=MockProvider(), days=1)
    assert (result["no_data"], result["requests"], result["passed"]) == (1, 0, 1)
    conn = duckdb.connect(str(cfg.warehouse), read_only=True)
    assert conn.execute("select provider from narratives.daily").fetchone() == ("rule",)


def test_stale_stations_are_not_narrated(cfg):
    """A station whose data stopped arriving would get narratives about weeks-old weather."""
    conn = duckdb.connect(str(cfg.warehouse))
    conn.execute("create table marts.mart_data_quality (station_id varchar, city varchar, element varchar, "
                 "freshness varchar)")
    conn.execute("insert into marts.mart_data_quality values ('CAN06158731', 'Toronto', 'TMAX', 'stale'), "
                 "('CAN06158731', 'Toronto', 'SNWD', 'not_applicable')")
    conn.close()
    result = pipeline.run(cfg, provider=MockProvider(), days=3)
    assert (result["generated"], result["requests"], result["skipped_stale"]) == (0, 0, ["Toronto"])


def test_lagging_stations_are_still_narrated(cfg):
    conn = duckdb.connect(str(cfg.warehouse))
    conn.execute("create table marts.mart_data_quality (station_id varchar, city varchar, element varchar, "
                 "freshness varchar)")
    conn.execute("insert into marts.mart_data_quality values ('CAN06158731', 'Toronto', 'TMAX', 'lagging')")
    conn.close()
    result = pipeline.run(cfg, provider=MockProvider(), days=3)
    assert result["generated"] == 3 and "skipped_stale" not in result
