"""Evaluate a narrative prompt and model on the fixed cases in evals/cases.yml.

Validation (validate.py) checks every production narrative; evaluation measures a prompt or model
change *before* it ships, on cases chosen because they're hard. Each case runs through the
provider with the prompt under test (no cache), is scored with the same validation checks plus
style checks, and the run is stored in ops.eval_runs / ops.eval_results for comparison:

    wx eval                                  # current prompt and provider
    wx eval --prompt prompts/narrative_v2.md # a candidate prompt
"""

import json
import re
import uuid
from pathlib import Path

import yaml

from wx import ops
from wx.config import ROOT, Config
from wx.narrate import pipeline, validate
from wx.narrate.providers import Provider, StationDay

CASES = ROOT / "evals" / "cases.yml"

DDL = """
create table if not exists ops.eval_runs (
    eval_id varchar, prompt_version varchar, provider varchar, model varchar, cases integer, passed integer,
    error_failures integer, warnings integer, style_issues integer, avg_chars double, input_tokens integer,
    output_tokens integer, evaluated_at timestamp);
create table if not exists ops.eval_results (
    eval_id varchar, case_id varchar, city varchar, obs_date date, narrative varchar, passed boolean,
    failed_checks varchar, warnings varchar, style_issues varchar);
alter table ops.eval_results add column if not exists cited json;
alter table ops.eval_results add column if not exists details varchar;
"""

# Style, scored in evaluation only: production validation is about truth, not taste.
STYLE = {
    "units_as_symbols": (re.compile(r"degrees? C\b|degrees Celsius", re.I), "write °C, not 'degrees C'"),
    "no_trailing_zero": (re.compile(r"\b\d+\.0\b"), "round 58.0 to 58"),
    "no_template_phrasing": (re.compile(r"\b(maximum|minimum) temperature of\b", re.I), "say 'a high of'"),
}


def load_cases(path: Path = CASES) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]


def _days(conn, cases: list[dict]) -> dict[str, StationDay]:
    days = {}
    for case in cases:
        row = conn.execute(
            """select station_id, city, province, station_name, obs_date::varchar, facts, input_hash
                              from marts.mart_narrative_input where city = ? and obs_date = ?""",
            [case["city"], str(case["date"])],
        ).fetchone()
        if row is None:
            raise LookupError(
                f"eval case {case['id']}: no {case['city']} {case['date']} in mart_narrative_input "
                f"(outside the window?)"
            )
        days[case["id"]] = StationDay(row[0], row[1], row[2], row[3], row[4], json.loads(row[5]), row[6])
    return days


def run(cfg: Config, prompt_path: Path | None = None, provider: Provider | None = None) -> dict:
    if prompt_path:
        cfg.narratives.prompt = prompt_path
    instructions, prompt_version = pipeline.prompt(cfg)
    provider = provider or pipeline.make_provider(cfg)
    cases = load_cases()
    conn = ops.connect(cfg.warehouse)
    conn.execute(DDL)
    try:
        days = _days(conn, cases)
        call = provider.generate(list(days.values()), instructions)
        drafts = {(d.get("station_id"), d.get("date")): d for d in call.drafts}
        eval_id = f"{ops.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        results = []
        for case in cases:
            day = days[case["id"]]
            draft = drafts.get((day.station_id, day.obs_date)) or {"narrative": "", "cited": []}
            checks = validate.validate(
                draft["narrative"],
                draft.get("cited") or [],
                day.facts,
                day.obs_date,
                day.city,
                [c.city for c in cfg.stations.cities],
                cfg.narratives.intensity,
            )
            style = [name for name, (pattern, _) in STYLE.items() if pattern.search(draft["narrative"])]
            details = "; ".join(f"{c.name}: {c.detail}" for c in checks if not c.passed and c.detail)
            result = {
                "case": case["id"],
                "city": day.city,
                "date": day.obs_date,
                "narrative": draft["narrative"],
                "details": details,
                "passed": bool(draft["narrative"]) and validate.passed(checks),
                "failed": [c.name for c in checks if not c.passed and c.severity == "error"],
                "warnings": [c.name for c in checks if not c.passed and c.severity == "warn"],
                "style": style,
            }
            results.append(result)
            conn.execute(
                "insert into ops.eval_results values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    eval_id,
                    case["id"],
                    day.city,
                    day.obs_date,
                    result["narrative"],
                    result["passed"],
                    ", ".join(result["failed"]) or None,
                    ", ".join(result["warnings"]) or None,
                    ", ".join(style) or None,
                    json.dumps(draft.get("cited") or []),
                    details or None,
                ],
            )
        summary = {
            "eval_id": eval_id,
            "prompt_version": prompt_version,
            "provider": provider.name,
            "model": call.model,
            "cases": len(results),
            "passed": sum(r["passed"] for r in results),
            "error_failures": sum(len(r["failed"]) for r in results),
            "warnings": sum(len(r["warnings"]) for r in results),
            "style_issues": sum(len(r["style"]) for r in results),
            "avg_chars": round(sum(len(r["narrative"]) for r in results) / len(results), 1),
            "input_tokens": call.input_tokens,
            "output_tokens": call.output_tokens,
        }
        conn.execute(
            "insert into ops.eval_runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [*summary.values(), ops.now()]
        )
        return {**summary, "results": results}
    finally:
        conn.close()
