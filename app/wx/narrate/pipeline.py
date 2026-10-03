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

import dataclasses
import hashlib
import json
import logging
import os
import time

from wx.config import ROOT, Config
from wx.narrate import validate
from wx.narrate.providers import GeminiProvider, MockProvider, Provider, ProviderError, QuotaExhausted, StationDay
from wx.observe import ops

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
alter table narratives.daily add column if not exists attempt integer default 1;
alter table narratives.validation add column if not exists attempt integer default 1;
create or replace view narratives.latest as
    select n.*, v.passed, v.failed_checks, v.warnings
    from narratives.daily n
    left join narratives.validation v
        on v.station_id = n.station_id and v.obs_date = n.obs_date and v.input_hash = n.input_hash
       and v.model = n.model and v.prompt_version = n.prompt_version and v.attempt = n.attempt
    qualify row_number() over (partition by n.station_id, n.obs_date order by n.generated_at desc) = 1;
"""

REPAIR = """

These recaps failed validation against their facts. Each station-day below includes your previous
recap and the problems found. Rewrite each one so it fixes every problem and still follows all of
the rules above; cite only usable facts, with the values exactly as given."""


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


def stale_stations(conn) -> dict[str, str]:
    """Stations with an element whose data stopped arriving (mart_data_quality.freshness = 'stale'):
    {station_id: city}. Their latest days would describe weather from weeks ago, so they aren't
    narrated until fresh data arrives. Empty when the mart doesn't exist yet."""
    exists = conn.execute("""select count(*) from information_schema.tables
                             where table_schema = 'marts' and table_name = 'mart_data_quality'""").fetchone()[0]
    if not exists:
        return {}
    return dict(conn.execute("""select distinct station_id, city from marts.mart_data_quality
                                where freshness = 'stale'""").fetchall())


def pending(conn, cfg: Config, model: str, prompt_version: str, days: int) -> list[StationDay]:
    rows = conn.execute(
        """
        select i.station_id, i.city, i.province, i.station_name, i.obs_date::varchar, i.facts, i.input_hash
        from marts.mart_narrative_input i
        where i.obs_date > (select max(obs_date) from marts.mart_narrative_input m
                            where m.station_id = i.station_id) - ?::int
          and not exists (select 1 from narratives.daily n
                          where n.station_id = i.station_id and n.obs_date = i.obs_date
                            and n.input_hash = i.input_hash and n.model = ? and n.prompt_version = ?)
        order by i.obs_date desc, i.city""",
        [days, model, prompt_version],
    ).fetchall()
    return [StationDay(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), r[6]) for r in rows]


def unrepaired(conn, cfg: Config, model: str, prompt_version: str, days: int) -> list[tuple]:
    """Stored narratives for current facts that failed on their first attempt and were never retried
    (an earlier run, or one whose quota ran out before the repair), ready for the repair pass."""
    rows = conn.execute(
        """
        select i.station_id, i.city, i.province, i.station_name, i.obs_date::varchar, i.facts, i.input_hash,
               l.narrative, l.cited
        from narratives.latest l
        join marts.mart_narrative_input i
          on i.station_id = l.station_id and i.obs_date = l.obs_date and i.input_hash = l.input_hash
        where not l.passed and l.attempt = 1 and l.model = ? and l.prompt_version = ?
          and i.obs_date > (select max(obs_date) from marts.mart_narrative_input m
                            where m.station_id = i.station_id) - ?::int""",
        [model, prompt_version, days],
    ).fetchall()
    failures = []
    for r in rows:
        day = StationDay(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), r[6])
        draft = {"narrative": r[7], "cited": json.loads(r[8])}
        checks = validate.validate(
            draft["narrative"],
            draft["cited"],
            day.facts,
            day.obs_date,
            day.city,
            [c.city for c in cfg.stations.cities],
            cfg.narratives.intensity,
        )
        failures.append((day, draft, checks))
    return failures


@ops.atomic  # a narrative is never stored without its validation
def _store(
    conn,
    run_id: str,
    provider_name: str,
    model: str,
    prompt_version: str,
    day: StationDay,
    draft: dict,
    cfg: Config,
    attempt: int = 1,
) -> list[validate.Check]:
    checks = validate.validate(
        draft["narrative"],
        draft.get("cited") or [],
        day.facts,
        day.obs_date,
        day.city,
        [c.city for c in cfg.stations.cities],
        cfg.narratives.intensity,
    )
    conn.execute(
        """insert into narratives.daily (station_id, obs_date, input_hash, provider, model, prompt_version,
                        narrative, cited, run_id, generated_at, attempt) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            day.station_id,
            day.obs_date,
            day.input_hash,
            provider_name,
            model,
            prompt_version,
            draft["narrative"],
            json.dumps(draft.get("cited") or []),
            run_id,
            ops.now(),
            attempt,
        ],
    )
    conn.execute(
        """insert into narratives.validation (station_id, obs_date, input_hash, model, prompt_version, passed,
                        failed_checks, warnings, checks, validated_at, attempt)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            day.station_id,
            day.obs_date,
            day.input_hash,
            model,
            prompt_version,
            validate.passed(checks),
            ", ".join(c.name for c in checks if not c.passed and c.severity == "error") or None,
            ", ".join(c.name for c in checks if not c.passed and c.severity == "warn") or None,
            json.dumps([c.__dict__ for c in checks]),
            ops.now(),
            attempt,
        ],
    )
    return checks


class _Stop(Exception):
    """No more requests this run (daily quota or max_requests_per_run): keep what's done."""


def run(cfg: Config, provider: Provider | None = None, days: int | None = None) -> dict:
    instructions, prompt_version = prompt(cfg)
    provider = provider or make_provider(cfg)
    n = cfg.narratives
    conn = ops.connect(cfg.warehouse)
    conn.execute(DDL)
    summary = {
        "provider": provider.name,
        "prompt_version": prompt_version,
        "generated": 0,
        "passed": 0,
        "failed_validation": 0,
        "repaired": 0,
        "missing_from_response": 0,
        "requests": 0,
        "deferred": 0,
        "no_data": 0,
    }
    pacing = {"interval": 60.0 / n.requests_per_minute, "last_start": 0.0}

    def request(run_id: str, batch: list[StationDay], text: str):
        """One paced, logged request. Raises _Stop when no more requests may be made this run."""
        if summary["requests"] >= n.max_requests_per_run:
            raise _Stop("max_requests_per_run reached")
        if provider.name != "mock":
            time.sleep(max(0.0, pacing["last_start"] + pacing["interval"] - time.time()))
        pacing["last_start"] = started = time.time()
        model = provider.model
        try:
            call = provider.generate(batch, text)
        except QuotaExhausted as exc:
            _log_call(
                conn,
                run_id,
                summary["requests"] + 1,
                provider,
                model,
                prompt_version,
                batch,
                None,
                started,
                "quota_exhausted",
                str(exc),
            )
            raise _Stop(str(exc)) from exc
        except ProviderError as exc:
            _log_call(
                conn,
                run_id,
                summary["requests"] + 1,
                provider,
                model,
                prompt_version,
                batch,
                None,
                started,
                "error",
                str(exc),
            )
            raise
        summary["requests"] += 1
        _log_call(conn, run_id, summary["requests"], provider, call.model, prompt_version, batch, call, started, "ok")
        return call

    try:
        with ops.run(conn, "narrate") as (run_id, details):
            todo = pending(conn, cfg, provider.model, prompt_version, days or n.days)
            stale = stale_stations(conn)
            if stale:
                skipped = [d for d in todo if d.station_id in stale]
                todo = [d for d in todo if d.station_id not in stale]
                summary["skipped_stale"] = sorted(stale.values())
                log.warning(
                    "not narrating %s: data is stale (older than quality.freshness_error_days); "
                    "%d station-days skipped",
                    ", ".join(sorted(stale.values())),
                    len(skipped),
                )
            summary["pending"] = len(todo)
            log.info("%d station-days need a narrative (%s, %s)", len(todo), provider.model, prompt_version)
            # Nothing usable to describe: write a fixed sentence rather than invite the model to invent one.
            for day in [d for d in todo if validate.nothing_to_report(d.facts)]:
                draft = {
                    "narrative": f"No temperature or precipitation readings were available for {day.city} "
                    f"on {day.obs_date}.",
                    "cited": [],
                }
                checks = _store(conn, run_id, "rule", provider.model, prompt_version, day, draft, cfg)
                summary["no_data"] += 1
                summary["generated"] += 1
                summary["passed" if validate.passed(checks) else "failed_validation"] += 1
            todo = [d for d in todo if not validate.nothing_to_report(d.facts)]

            failures = [
                f
                for f in unrepaired(conn, cfg, provider.model, prompt_version, days or n.days)
                if f[0].station_id not in stale
            ]
            carried = summary["carried_over"] = len(failures)
            if carried:
                log.info("%d narratives from earlier runs failed validation and get their repair attempt", carried)
            try:
                for start in range(0, len(todo), n.batch_size):
                    batch = todo[start : start + n.batch_size]
                    try:
                        call = request(run_id, batch, instructions)
                    except _Stop as stop:
                        summary["deferred"] = len(todo) - start
                        log.warning("%s; %d station-days deferred to the next run", stop, summary["deferred"])
                        raise
                    drafts = {(d.get("station_id"), d.get("date")): d for d in call.drafts}
                    for day in batch:
                        draft = drafts.get((day.station_id, day.obs_date))
                        if not draft:
                            summary["missing_from_response"] += 1
                            continue
                        summary["generated"] += 1
                        checks = _store(conn, run_id, provider.name, call.model, prompt_version, day, draft, cfg)
                        if validate.passed(checks):
                            summary["passed"] += 1
                        else:
                            failures.append((day, draft, checks))

                # One repair attempt: each failure goes back with its previous recap and its problems.
                for start in range(0, len(failures) if n.repair_attempts else 0, n.batch_size):
                    chunk = failures[start : start + n.batch_size]
                    batch = [
                        dataclasses.replace(
                            day,
                            feedback={
                                "previous_narrative": draft["narrative"],
                                "previous_cited": draft.get("cited") or [],
                                "problems": [
                                    f"{c.name}: {c.detail}" for c in checks if not c.passed and c.severity == "error"
                                ],
                            },
                        )
                        for day, draft, checks in chunk
                    ]
                    call = request(run_id, batch, instructions + REPAIR)
                    drafts = {(d.get("station_id"), d.get("date")): d for d in call.drafts}
                    for day, _, _ in chunk:
                        draft = drafts.get((day.station_id, day.obs_date))
                        if draft and validate.passed(
                            _store(conn, run_id, provider.name, call.model, prompt_version, day, draft, cfg, attempt=2)
                        ):
                            summary["repaired"] += 1
                    log.info("repair: %d of %d fixed", summary["repaired"], len(failures))
            except _Stop:
                pass
            summary["passed"] += summary["repaired"]
            summary["failed_validation"] += len(failures) - summary["repaired"]
            details.update(summary)
    finally:
        conn.close()
    return {"run_id": run_id, **summary}


def _log_call(conn, run_id, call_no, provider, model, prompt_version, batch, call, started, status, error=None):
    conn.execute(
        "insert into ops.llm_calls values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            run_id,
            call_no,
            provider.name,
            model,
            prompt_version,
            len(batch),
            len(call.drafts) if call else 0,
            call.input_tokens if call else 0,
            call.output_tokens if call else 0,
            time.time() - started,
            call.attempts if call else 1,
            call.waited_seconds if call else 0,
            status,
            error,
            "; ".join(call.notes) if call else None,
            ops.now(),
        ],
    )
