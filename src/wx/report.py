"""Results report: one self-contained HTML page with the weather data, data quality, NOAA's
changes, narratives with their validation, prompt evaluation and pipeline operations.

    wx report                     # writes data/report.html; open it in a browser
    wx report --out site/index.html

The data is embedded as JSON and rendered with React from a CDN, so there's nothing to install or
serve: graders open one file. Read-only against the warehouse.
"""
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from wx import health, ops
from wx.config import Config

TEMPLATE = Path(__file__).with_name("report_template.html")


def _rows(conn, sql: str, params=None) -> list[dict]:
    cursor = conn.execute(sql, params or [])
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _has(conn, schema: str, table: str) -> bool:
    return bool(conn.execute("select count(*) from information_schema.tables where table_schema = ? and "
                             "table_name = ?", [schema, table]).fetchone()[0])


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def collect(cfg: Config) -> dict:
    report = health.build(cfg)
    conn = ops.connect_read(cfg.warehouse)
    try:
        data = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "health": {"status": report.status, "errors": report.errors, "warnings": report.warnings},
            "runs": _rows(conn, """
                select command, status, started_at, round(epoch(finished_at - started_at)) as seconds, error
                from ops.runs qualify row_number() over (partition by command order by started_at desc) = 1
                order by started_at"""),
            "window": _rows(conn, "select start_date, end_date from config.window")[0],
            "stations": _rows(conn, """
                select s.city, s.province, s.station_id, s.station_name, s.latitude, s.longitude, s.elevation_m,
                       s.wmo_id, s.elements_reported,
                       r.candidates, r.rejected_airport, r.rejected_coverage, r.ranked_lower
                from marts.dim_station s
                left join (
                    select city, count(*) as candidates,
                           count(*) filter (where reason like 'name doesn''t match%') as rejected_airport,
                           count(*) filter (where reason like 'reports %') as rejected_coverage,
                           count(*) filter (where reason like 'ranked lower%') as ranked_lower
                    from ops.station_resolution
                    where run_id = (select max(run_id) from ops.station_resolution) group by city) r using (city)
                order by s.city"""),
            "elements": _rows(conn, """select element, label, display_unit, unit, is_core, absent_means_zero,
                                              lower_bound, upper_bound from marts.dim_element
                                       order by not is_core, element"""),
            "daily": _rows(conn, """
                select d.city, d.obs_date as date, d.tmax, d.tmin, d.tavg, d.prcp, d.prcp_status,
                       d.snow * e_snow.display_factor as snow, d.snow_status,
                       d.snwd * e_snwd.display_factor as snwd, d.snwd_status,
                       d.wsfg * e_wsfg.display_factor as wsfg, d.wsfg_status, d.wdfg,
                       d.tmax_status, d.tmin_status, d.missing_elements, d.quarantined_elements
                from marts.mart_station_daily d
                cross join (select display_factor from marts.dim_element where element = 'SNOW') e_snow
                cross join (select display_factor from marts.dim_element where element = 'SNWD') e_snwd
                cross join (select display_factor from marts.dim_element where element = 'WSFG') e_wsfg
                order by d.city, d.obs_date"""),
            "quality": _rows(conn, """select city, element, expected_days, valid_days, trace_days, missing_days,
                                             not_reported_days, qc_failed_days, out_of_bounds_days, completeness,
                                             last_usable_date, days_since_last, freshness
                                      from marts.mart_data_quality order by city, element"""),
            "changes": _rows(conn, """select run_id, changed_at, city, inserted, updated, deleted, value_revisions,
                                             flag_revisions, historical_changes, earliest_date_touched
                                      from marts.mart_source_changes order by changed_at desc, city limit 50"""),
        }
        if _has(conn, "narratives", "latest"):
            data["narratives"] = _rows(conn, """
                select s.city, n.obs_date as date, n.narrative, n.provider, n.model, n.prompt_version, n.passed,
                       n.failed_checks, n.warnings, n.cited, i.facts, v.checks
                from narratives.latest n
                join marts.dim_station s on s.station_id = n.station_id
                left join marts.mart_narrative_input i on i.station_id = n.station_id and i.obs_date = n.obs_date
                left join narratives.validation v
                    on v.station_id = n.station_id and v.obs_date = n.obs_date and v.input_hash = n.input_hash
                   and v.model = n.model and v.prompt_version = n.prompt_version
                order by n.obs_date desc, s.city""")
            data["llm_calls"] = _rows(conn, """select run_id, call_no, model, prompt_version, station_days, returned,
                                                      input_tokens, output_tokens, round(seconds, 1) as seconds,
                                                      attempts, status, error, notes, called_at
                                               from ops.llm_calls order by called_at desc limit 30""")
        if _has(conn, "ops", "eval_runs"):
            latest = _rows(conn, """select * from ops.eval_runs
                                    qualify row_number() over (partition by prompt_version, model
                                                               order by evaluated_at desc) = 1
                                    order by evaluated_at""")
            data["evals"] = [{**run, "results": _rows(conn, """
                select case_id, city, obs_date as date, narrative, passed, failed_checks, warnings, style_issues,
                       details from ops.eval_results where eval_id = ? order by rowid""", [run["eval_id"]])}
                for run in latest]
        if _has(conn, "ops", "dbt_runs"):
            invocation = conn.execute("select invocation_id from ops.dbt_runs order by started_at desc "
                                      "limit 1").fetchone()[0]
            data["dbt"] = _rows(conn, """select name, resource_type, status, round(execution_seconds, 2) as seconds,
                                                failures, message from ops.dbt_node_runs where invocation_id = ?
                                         order by resource_type, name""", [invocation])
        for key in ("narratives",):
            for row in data.get(key, []):
                for field in ("cited", "facts", "checks"):
                    if isinstance(row.get(field), str):
                        row[field] = json.loads(row[field])
        return data
    finally:
        conn.close()


def render(cfg: Config, out: Path | None = None) -> Path:
    data = collect(cfg)
    payload = json.dumps(data, default=_json_default, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    out = out or cfg.data_dir / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")
    return out
