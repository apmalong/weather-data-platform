"""wx: the pipeline's command line.

    wx ingest       download NOAA files, resolve stations, load raw
    wx transform    dbt build: models and data-quality tests
    wx narrate      daily narratives with Gemini (or the offline mock), validated against the data
    wx eval         score a narrative prompt/model on the hard cases in evals/cases.yml
    wx health       one report on every stage: runs, checks, dbt tests, data quality, narratives
    wx report       one HTML page with the results: weather, data quality, narratives, evaluation, ops
    wx run          ingest, transform, narrate, report
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
    print(f"narrate {result['run_id']}: {result['generated']} generated ({result['passed']} passed validation, "
          f"{result['failed_validation']} failed) with {result['provider']} in {result['requests']} requests; "
          f"{result['deferred']} deferred")


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
    print(f"\neval {result['eval_id']} {result['prompt_version']} on {result['model']}: {result['passed']}/"
          f"{result['cases']} passed, {result['error_failures']} errors, {result['warnings']} warnings, "
          f"{result['style_issues']} style issues, {result['avg_chars']} chars avg, "
          f"{result['input_tokens']}+{result['output_tokens']} tokens")


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
    commands = parser.add_subparsers(dest="command", required=True)
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
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    load_dotenv()
    cfg = config.load()
    try:
        commands_by_name = {"ingest": _ingest, "transform": _transform, "narrate": _narrate, "eval": _eval,
                            "health": _health, "report": _report, "run": _run}
        commands_by_name[args.command](args, cfg)
    except Exception as exc:  # one clear line for operators; the traceback is in -v and ops.runs
        logging.getLogger("wx").error("%s failed: %s", args.command, exc, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
