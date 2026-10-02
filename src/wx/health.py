"""Health report: one view of every stage, from the ops ledger and the marts.

    wx health                         # print the report
    wx health --out docs/health.md    # also write it as Markdown
    wx health --strict                # exit 1 when the status is ERROR

Status is ERROR when the latest run of a stage failed, a dbt error-severity test failed, a station
is stale or a narrative failed validation; WARN for warnings (lagging data, volume swings, dbt
warnings, rejected rows, narratives deferred by the free tier's quota).
"""
import json
from dataclasses import dataclass, field

import duckdb

from wx.config import Config


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def h(self, title: str) -> None:
        self.lines += ["", f"## {title}", ""]

    def table(self, header: list[str], rows: list) -> None:
        if not rows:
            self.lines.append("_none_")
            return
        self.lines.append("| " + " | ".join(header) + " |")
        self.lines.append("|" + "---|" * len(header))
        for row in rows:
            self.lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")

    @property
    def status(self) -> str:
        return "ERROR" if self.errors else "WARN" if self.warnings else "OK"

    def markdown(self) -> str:
        head = ["# Pipeline health", "", f"**Status: {self.status}**"]
        head += [f"- error: {e}" for e in self.errors] + [f"- warning: {w}" for w in self.warnings]
        return "\n".join(head + self.lines) + "\n"


def _has(conn, schema: str, table: str) -> bool:
    return bool(conn.execute("select count(*) from information_schema.tables where table_schema = ? and "
                             "table_name = ?", [schema, table]).fetchone()[0])


def build(cfg: Config) -> Report:
    r = Report()
    conn = duckdb.connect(str(cfg.warehouse), read_only=True)
    try:
        _runs(conn, r)
        _ingest(conn, r, cfg)
        _transform(conn, r)
        _quality(conn, r)
        _narratives(conn, r)
    finally:
        conn.close()
    return r


def _runs(conn, r: Report) -> None:
    r.h("Latest run of each stage")
    rows = conn.execute("""
        select command, status, strftime(started_at, '%Y-%m-%d %H:%M:%S'),
               round(epoch(finished_at - started_at)) as seconds, error
        from ops.runs qualify row_number() over (partition by command order by started_at desc) = 1
        order by started_at""").fetchall()
    r.table(["stage", "status", "started (UTC)", "seconds", "error"], rows)
    for command, status, *_, error in rows:
        if status == "failed":
            r.errors.append(f"latest {command} failed: {error}")


def _ingest(conn, r: Report, cfg: Config) -> None:
    run_id = conn.execute("select max(run_id) from ops.runs where command = 'ingest'").fetchone()[0]
    r.h(f"Ingest ({run_id})")
    downloads = conn.execute("""select count(*), count(*) filter (where changed),
                                       count(*) filter (where error is not null), round(sum(bytes) / 1e6, 1)
                                from ops.downloads where run_id = ?""", [run_id]).fetchone()
    r.lines.append(f"{downloads[0]} files downloaded, {downloads[1]} changed since the last run, "
                   f"{downloads[2]} failed, {downloads[3]} MB.")
    r.lines.append("")
    r.table(["city", "station", "candidates considered", "why it won"], conn.execute("""
        select city, station_id || ' ' || station_name, count(*) over (partition by city), reason
        from ops.station_resolution where run_id = ?
        qualify selected""", [run_id]).fetchall())
    failed = conn.execute("""select stage, check_name, subject, severity, observed, expected from ops.checks
                             where run_id = ? and not passed""", [run_id]).fetchall()
    for stage, name, subject, severity, observed, expected in failed:
        (r.errors if severity == "error" else r.warnings).append(
            f"{stage} check {name} on {subject}: observed {observed}, expected {expected}")
    # Volume: rows in each station's file versus its previous load.
    swings = conn.execute("""
        with loads as (
            select source_file, rows_read, loaded_at,
                   lag(rows_read) over (partition by source_file order by loaded_at) as previous
            from ops.loads where dataset = 'observations')
        select source_file, previous, rows_read, round(100.0 * (rows_read - previous) / previous, 1) as pct
        from loads where previous is not null
        qualify row_number() over (partition by source_file order by loaded_at desc) = 1""").fetchall()
    for source_file, previous, rows, pct in swings:
        if abs(pct) > cfg.quality.volume_change_warn_pct:
            r.warnings.append(f"{source_file}: {previous} -> {rows} rows ({pct:+}%) since its previous load")
    if _has(conn, "marts", "mart_source_changes"):
        r.lines += ["", "What NOAA changed in the most recent load that changed anything (revisions and "
                        "removals of past dates count as historical):", ""]
        r.table(["run", "city", "inserted", "updated", "deleted", "historical"], conn.execute("""
            select run_id, city, inserted, updated, deleted, historical_changes from marts.mart_source_changes
            qualify run_id = max(run_id) over () order by city""").fetchall())


def _transform(conn, r: Report) -> None:
    if not _has(conn, "ops", "dbt_runs"):
        return
    invocation, wx_run = conn.execute("select invocation_id, wx_run_id from ops.dbt_runs "
                                      "order by started_at desc limit 1").fetchone()
    r.h(f"Transform: dbt build ({wx_run})")
    counts = conn.execute("""select resource_type, status, count(*) from ops.dbt_node_runs where invocation_id = ?
                             group by all order by 1, 2""", [invocation]).fetchall()
    r.lines.append(", ".join(f"{n} {t} {s}" for t, s, n in counts) + ".")
    problems = conn.execute("""select name, status, failures, message from ops.dbt_node_runs
                               where invocation_id = ? and status in ('error', 'fail', 'warn')""",
                            [invocation]).fetchall()
    if problems:
        r.lines.append("")
        r.table(["node", "status", "failing rows", "message"], problems)
    for name, status, failures, _ in problems:
        (r.warnings if status == "warn" else r.errors).append(f"dbt {status}: {name} ({failures} rows)")


def _quality(conn, r: Report) -> None:
    if not _has(conn, "marts", "mart_data_quality"):
        return
    r.h("Data quality over the window")
    rows = conn.execute("""
        select city,
               min(completeness) filter (where expected_days > 0) as worst_completeness,
               arg_min(element, completeness) filter (where expected_days > 0) as worst_element,
               sum(missing_days) as missing, sum(trace_days) as trace,
               sum(qc_failed_days + out_of_bounds_days + unparseable_days) as quarantined,
               max(last_usable_date) filter (where freshness <> 'not_applicable') as latest,
               case when bool_or(freshness = 'stale') then 'stale' when bool_or(freshness = 'lagging') then 'lagging'
                    else 'fresh' end as freshness
        from marts.mart_data_quality group by city order by city""").fetchall()
    r.table(["city", "worst completeness", "element", "missing days", "trace days", "quarantined", "latest",
             "freshness"], rows)
    for city, *_, freshness in rows:
        if freshness == "stale":
            r.errors.append(f"{city} is stale")
        elif freshness == "lagging":
            r.warnings.append(f"{city} is lagging")


def _narratives(conn, r: Report) -> None:
    if not _has(conn, "narratives", "latest"):
        return
    run_id = conn.execute("select max(run_id) from ops.runs where command = 'narrate'").fetchone()[0]
    r.h(f"Narratives ({run_id})")
    calls = conn.execute("""select count(*), sum(station_days), sum(input_tokens), sum(output_tokens),
                                   round(avg(seconds), 1), sum(attempts) - count(*), string_agg(distinct model, ', '),
                                   count(*) filter (where status <> 'ok')
                            from ops.llm_calls where run_id = ?""", [run_id]).fetchone()
    r.lines.append(f"Latest run: {calls[0]} requests for {calls[1] or 0} station-days on {calls[6]}, "
                   f"{calls[2] or 0}+{calls[3] or 0} tokens, {calls[4]} s per request, {calls[5] or 0} retries, "
                   f"{calls[7]} failed requests.")
    details = conn.execute("select details from ops.runs where run_id = ?", [run_id]).fetchone()[0] or "{}"
    deferred = json.loads(details).get("deferred", 0)
    if deferred:
        r.warnings.append(f"{deferred} station-days deferred (request cap or daily quota); the next run resumes")
    stats = conn.execute("""select count(*), count(*) filter (where passed), min(obs_date), max(obs_date),
                                   string_agg(distinct provider || ' ' || model, ', ')
                            from narratives.latest""").fetchone()
    r.lines.append(f"Current narratives: {stats[0]} station-days from {stats[2]} to {stats[3]} ({stats[4]}), "
                   f"{stats[1]} passed validation.")
    failed = conn.execute("""select s.city, n.obs_date, n.failed_checks, left(n.narrative, 120)
                             from narratives.latest n join marts.dim_station s using (station_id)
                             where not n.passed order by n.obs_date desc limit 10""").fetchall()
    if failed:
        r.lines.append("")
        r.table(["city", "date", "failed checks", "narrative"], failed)
        r.errors.append(f"{stats[0] - stats[1]} current narratives failed validation")
    if _has(conn, "ops", "eval_runs"):
        r.lines += ["", "Evaluation on evals/cases.yml, latest run per prompt version:", ""]
        r.table(["prompt", "model", "passed", "style issues", "avg chars", "when (UTC)"], conn.execute("""
            select prompt_version, model, passed || '/' || cases, style_issues, avg_chars,
                   strftime(evaluated_at, '%Y-%m-%d %H:%M')
            from ops.eval_runs
            qualify row_number() over (partition by prompt_version, model order by evaluated_at desc) = 1
            order by evaluated_at""").fetchall())
