"""wx: the pipeline's command line.

    wx ingest       download NOAA files, resolve stations, load raw
    wx transform    dbt build: models and data-quality tests
    wx run          ingest, then transform
"""
import argparse
import logging
import sys

from wx import config


def _ingest(args, cfg) -> None:
    from wx import ingest
    result = ingest.run(cfg, force=args.force)
    print(f"ingest {result['run_id']}: {result['stations']}")


def _transform(args, cfg) -> None:
    from wx import transform
    result = transform.run(cfg, full_refresh=args.full_refresh, select=args.select)
    print(f"transform {result['run_id']}: {result['statuses']}")


def _run(args, cfg) -> None:
    args.force = False
    args.full_refresh = False
    args.select = None
    _ingest(args, cfg)
    _transform(args, cfg)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wx", description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="download NOAA files, resolve stations, load raw")
    ingest.add_argument("--force", action="store_true", help="reload files even if unchanged")
    transform = commands.add_parser("transform", help="dbt build: models and data-quality tests")
    transform.add_argument("--full-refresh", action="store_true", help="rebuild incremental models from raw")
    transform.add_argument("--select", help="dbt node selection, e.g. marts")
    commands.add_parser("run", help="ingest, then transform")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    cfg = config.load()
    try:
        {"ingest": _ingest, "transform": _transform, "run": _run}[args.command](args, cfg)
    except Exception as exc:  # one clear line for operators; the traceback is in -v and ops.runs
        logging.getLogger("wx").error("%s failed: %s", args.command, exc, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
