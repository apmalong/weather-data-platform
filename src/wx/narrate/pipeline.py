"""Narrate: daily weather narratives in bulk from marts.mart_narrative_input.

    pending   station-days in the last `days` whose (input_hash, model, prompt version) has no
              narrative yet: new days, or days whose facts NOAA revised
    batches   `batch_size` station-days per request, paced to `requests_per_minute`, capped at
              `max_requests_per_run`
    validate  every narrative against its facts (validate.py) before it's stored
    record    narratives.daily, narratives.validation, ops.llm_calls (tokens, latency, retries)

Re-running is cheap and safe: cached narratives are skipped, so a run cut short by the free tier's
daily quota resumes where it stopped.
"""
import hashlib
import json
import logging
import os
import time

from wx import ops
from wx.config import ROOT, Config
from wx.narrate import validate
from wx.narrate.providers import GeminiProvider, MockProvider, Provider, ProviderError, QuotaExhausted, StationDay

log = logging.getLogger(__name__)

DDL = """
create schema if not exists narratives;
create table if not exists narratives.daily (
    station_id varchar, obs_date date, input_hash varchar, provider varchar, model varchar,
    prompt_version varchar, narrative varchar, cited json, run_id varchar, generated_at timestamp);
create table if not exists narratives.validation (
    station_id varchar, obs_date date, input_hash varchar, model varchar, prompt_version varchar,
    passed boolean, failed_checks varchar, warnings varchar, checks json, validated_at timestamp);
create table if not exists ops.llm_calls (
    run_id varchar, call_no integer, provider varchar, model varchar, prompt_version varchar,
    station_days integer, returned integer, input_tokens integer, output_tokens integer, seconds double,
    attempts integer, waited_seconds double, status varchar, error varchar, notes varchar, called_at timestamp);
create or replace view narratives.latest as
    select n.*, v.passed, v.failed_checks, v.warnings
    from narratives.daily n
    left join narratives.validation v using (station_id, obs_date, input_hash, model, prompt_version)
    qualify row_number() over (partition by n.station_id, n.obs_date order by n.generated_at desc) = 1;
"""


def prompt(cfg: Config) -> tuple[str, str]:
    """The instructions and their version: file stem plus a content hash, so editing the prompt
    regenerates narratives instead of silently mixing versions."""
    path = cfg.narratives.prompt if cfg.narratives.prompt.is_absolute() else ROOT / cfg.narratives.prompt
    text = path.read_text(encoding="utf-8")
    return text, f"{path.stem}@{hashlib.sha256(text.encode()).hexdigest()[:8]}"


def make_provider(cfg: Config) -> Provider:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    choice = cfg.narratives.provider
    if choice == "gemini" and not key:
        raise ProviderError("narratives.provider is gemini but GEMINI_API_KEY isn't set")
    if choice == "mock" or (choice == "auto" and not key):
        if choice == "auto":
            log.warning("GEMINI_API_KEY isn't set: using the offline mock provider")
        return MockProvider()
    return GeminiProvider(key, cfg.narratives.models, cfg.narratives.temperature)


def pending(conn, cfg: Config, model: str, prompt_version: str, days: int) -> list[StationDay]:
    rows = conn.execute("""
        select i.station_id, i.city, i.province, i.station_name, i.obs_date::varchar, i.facts, i.input_hash
        from marts.mart_narrative_input i
        where i.obs_date > (select max(obs_date) from marts.mart_narrative_input m
                            where m.station_id = i.station_id) - ?::int
          and not exists (select 1 from narratives.daily n
                          where n.station_id = i.station_id and n.obs_date = i.obs_date
                            and n.input_hash = i.input_hash and n.model = ? and n.prompt_version = ?)
        order by i.obs_date desc, i.city""", [days, model, prompt_version]).fetchall()
    return [StationDay(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), r[6]) for r in rows]


def _store(conn, run_id: str, provider: Provider, model: str, prompt_version: str, day: StationDay,
           draft: dict) -> bool:
    checks = validate.validate(draft["narrative"], draft.get("cited") or [], day.facts, day.obs_date)
    ok = validate.passed(checks)
    conn.execute("insert into narratives.daily values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 [day.station_id, day.obs_date, day.input_hash, provider.name, model, prompt_version,
                  draft["narrative"], json.dumps(draft.get("cited") or []), run_id, ops.now()])
    conn.execute("insert into narratives.validation values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 [day.station_id, day.obs_date, day.input_hash, model, prompt_version, ok,
                  ", ".join(c.name for c in checks if not c.passed and c.severity == "error") or None,
                  ", ".join(c.name for c in checks if not c.passed and c.severity == "warn") or None,
                  json.dumps([c.__dict__ for c in checks]), ops.now()])
    return ok


def run(cfg: Config, provider: Provider | None = None, days: int | None = None) -> dict:
    instructions, prompt_version = prompt(cfg)
    provider = provider or make_provider(cfg)
    n = cfg.narratives
    conn = ops.connect(cfg.warehouse)
    conn.execute(DDL)
    summary = {"provider": provider.name, "prompt_version": prompt_version, "generated": 0, "passed": 0,
               "failed_validation": 0, "missing_from_response": 0, "requests": 0, "deferred": 0}
    try:
        with ops.run(conn, "narrate") as (run_id, details):
            todo = pending(conn, cfg, provider.model, prompt_version, days or n.days)
            summary["pending"] = len(todo)
            log.info("%d station-days need a narrative (%s, %s)", len(todo), provider.model, prompt_version)
            interval, last_start = 60.0 / n.requests_per_minute, 0.0
            for call_no, start in enumerate(range(0, len(todo), n.batch_size), 1):
                batch = todo[start:start + n.batch_size]
                if call_no > n.max_requests_per_run:
                    summary["deferred"] = len(todo) - start
                    log.warning("max_requests_per_run reached; %d station-days deferred to the next run",
                                summary["deferred"])
                    break
                if provider.name != "mock":
                    time.sleep(max(0.0, last_start + interval - time.time()))
                last_start = time.time()
                model = provider.model
                try:
                    call = provider.generate(batch, instructions)
                except QuotaExhausted as exc:
                    summary["deferred"] = len(todo) - start
                    _log_call(conn, run_id, call_no, provider, model, prompt_version, batch, None, last_start,
                              "quota_exhausted", str(exc))
                    log.warning("%s; %d station-days deferred to the next run", exc, summary["deferred"])
                    break
                except ProviderError as exc:
                    _log_call(conn, run_id, call_no, provider, model, prompt_version, batch, None, last_start,
                              "error", str(exc))
                    raise
                summary["requests"] += 1
                drafts = {(d.get("station_id"), d.get("date")): d for d in call.drafts}
                for day in batch:
                    draft = drafts.get((day.station_id, day.obs_date))
                    if not draft:
                        summary["missing_from_response"] += 1
                        continue
                    summary["generated"] += 1
                    ok = _store(conn, run_id, provider, call.model, prompt_version, day, draft)
                    summary["passed" if ok else "failed_validation"] += 1
                _log_call(conn, run_id, call_no, provider, call.model, prompt_version, batch, call, last_start, "ok")
            details.update(summary)
    finally:
        conn.close()
    return {"run_id": run_id, **summary}


def _log_call(conn, run_id, call_no, provider, model, prompt_version, batch, call, started, status, error=None):
    conn.execute("insert into ops.llm_calls values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 [run_id, call_no, provider.name, model, prompt_version, len(batch),
                  len(call.drafts) if call else 0, call.input_tokens if call else 0,
                  call.output_tokens if call else 0, time.time() - started, call.attempts if call else 1,
                  call.waited_seconds if call else 0, status, error, "; ".join(call.notes) if call else None,
                  ops.now()])
