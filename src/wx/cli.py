"""wx: the pipeline's command line.

wx ingest       download NOAA files, resolve stations, load raw
wx transform    dbt build: models and data-quality tests
wx narrate      daily narratives with Gemini (or the offline mock), validated against the data
wx eval         score a narrative prompt/model on the hard cases in evals/cases.yml
wx health       one report on every stage: runs, checks, dbt tests, data quality, narratives
wx report       one HTML page with the results: weather, data quality, narratives, evaluation, ops
wx run          ingest, transform, narrate, report
wx reset        start over: the warehouse (default), everything (--all) or narratives only
"""

import argparse
import logging
import os
import sys

from wx import config


def load_dotenv(path=config.ROOT / ".env") -> None:
    """KEY=value lines from .env into the environment, without overriding what's already set."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _ingest(args, cfg) -> None:
    from wx import ingest

    result = ingest.run(cfg, force=args.force)
    print(f"ingest {result['run_id']}: {result['stations']}")


def _transform(args, cfg) -> None:
    from wx import transform

    result = transform.run(cfg, full_refresh=args.full_refresh, select=args.select)
    print(f"transform {result['run_id']}: {result['statuses']}")


def _narrate(args, cfg) -> None:
    from wx.narrate import pipeline

    if getattr(args, "provider", None):
        cfg.narratives.provider = args.provider
    result = pipeline.run(cfg, days=getattr(args, "days", None))
    print(
        f"narrate {result['run_id']}: {result['generated']} generated ({result['passed']} passed validation, "
        f"{result['failed_validation']} failed) with {result['provider']} in {result['requests']} requests; "
        f"{result['deferred']} deferred"
    )


def _eval(args, cfg) -> None:
    from pathlib import Path

    from wx.narrate import evaluate

    if args.provider:
        cfg.narratives.provider = args.provider
    result = evaluate.run(cfg, Path(args.prompt) if args.prompt else None)
    for r in result["results"]:
        flags = ", ".join(r["failed"] + r["warnings"] + r["style"]) or "ok"
        if r["details"]:
            flags += f" ({r['details']})"
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['case']:<18} {flags}\n      {r['narrative']}")
    print(
        f"\neval {result['eval_id']} {result['prompt_version']} on {result['model']}: {result['passed']}/"
        f"{result['cases']} passed, {result['error_failures']} errors, {result['warnings']} warnings, "
        f"{result['style_issues']} style issues, {result['avg_chars']} chars avg, "
        f"{result['input_tokens']}+{result['output_tokens']} tokens"
    )


def _health(args, cfg) -> None:
    from pathlib import Path

    from wx import health

    report = health.build(cfg)
    text = report.markdown()
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    if args.strict and report.status == "ERROR":
        sys.exit(1)


def _report(args, cfg) -> None:
    from pathlib import Path

    from wx import report

    path = report.render(cfg, Path(args.out) if args.out else None)
    print(f"report written to {path.resolve()}")


def _reset(args, cfg) -> None:
    from wx import reset

    what = reset.describe(cfg, args.all, args.narratives)
    if not what:
        print("Nothing to reset.")
        return
    print(f"This removes:\n{what}" if not args.narratives else f"This removes {what}.")
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("Not removing anything: confirm with --yes when not running interactively.")
        try:
            answer = input("Continue? [y/N] ")
        except EOFError:  # no input after all (some shells report a terminal that isn't one)
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing removed.")
            return
    removed = reset.reset(cfg, everything=args.all, narratives=args.narratives)
    print(f"Removed {len(removed)} item(s). `wx run` rebuilds.")


def _explore(args, cfg) -> None:
    import time

    import duckdb

    if not cfg.warehouse.exists():
        sys.exit(f"No warehouse at {cfg.warehouse}: run `wx run` first.")
    # The UI keeps its own state through this connection, so the connection is in memory (writable)
    # and the warehouse is attached read-only: nothing can change it, and nothing is locked for long.
    conn = duckdb.connect()
    conn.execute(f"attach '{cfg.warehouse.as_posix()}' as warehouse (read_only)")
    conn.execute("use warehouse")
    conn.execute("call start_ui()")
    print(
        "DuckDB UI at http://localhost:4213 (warehouse attached read-only as `warehouse`).\n"
        "Press Ctrl+C to stop; stop it before running other wx commands."
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        conn.execute("call stop_ui_server()")
        conn.close()


def _run(args, cfg) -> None:
    args.force = False
    args.full_refresh = False
    args.select = None
    _ingest(args, cfg)
    _transform(args, cfg)
    _narrate(args, cfg)
    args.out = None
    _report(args, cfg)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wx", description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--explore",
        action="store_true",
        help="browse the warehouse in DuckDB's web UI (read-only); with a command, once it finishes",
    )
    commands = parser.add_subparsers(dest="command")
    ingest = commands.add_parser("ingest", help="download NOAA files, resolve stations, load raw")
    ingest.add_argument("--force", action="store_true", help="reload files even if unchanged")
    transform = commands.add_parser("transform", help="dbt build: models and data-quality tests")
    transform.add_argument("--full-refresh", action="store_true", help="rebuild incremental models from raw")
    transform.add_argument("--select", help="dbt node selection, e.g. marts")
    narrate = commands.add_parser("narrate", help="daily narratives, validated against the data")
    narrate.add_argument("--days", type=int, help="override narratives.days")
    narrate.add_argument("--provider", choices=["auto", "gemini", "mock"], help="override narratives.provider")
    evaluation = commands.add_parser("eval", help="score a prompt/model on evals/cases.yml")
    evaluation.add_argument("--prompt", help="prompt file to evaluate (default: narratives.prompt)")
    evaluation.add_argument("--provider", choices=["auto", "gemini", "mock"])
    health = commands.add_parser("health", help="report on every stage from the ops ledger and marts")
    health.add_argument("--out", help="also write the report to this Markdown file")
    health.add_argument("--strict", action="store_true", help="exit 1 when the status is ERROR")
    rep = commands.add_parser("report", help="write the results as one HTML page")
    rep.add_argument("--out", help="output file (default: data/report.html)")
    commands.add_parser("run", help="ingest, transform, narrate, report")
    reset_cmd = commands.add_parser("reset", help="remove what the pipeline built, to start over")
    scope = reset_cmd.add_mutually_exclusive_group()
    scope.add_argument("--all", action="store_true", help="also the downloaded NOAA files and the report")
    scope.add_argument("--narratives", action="store_true", help="only the narrative cache")
    reset_cmd.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args(argv)
    if not args.command and not args.explore:
        parser.error("a command or --explore is required")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    load_dotenv()
    cfg = config.load()
    try:
        commands_by_name = {
            "ingest": _ingest,
            "transform": _transform,
            "narrate": _narrate,
            "eval": _eval,
            "health": _health,
            "report": _report,
            "run": _run,
            "reset": _reset,
        }
        if args.command:
            commands_by_name[args.command](args, cfg)
        if args.explore:
            _explore(args, cfg)
    except Exception as exc:  # one clear line for operators; the traceback is in -v and ops.runs
        logging.getLogger("wx").error("%s failed: %s", args.command or "explore", exc, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
