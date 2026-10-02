"""wx: the pipeline's command line.

    wx ingest       download NOAA files, resolve stations, load raw
    wx transform    dbt build (models and tests)
    wx run          everything, in order
"""
import argparse
import logging
import sys

from wx import config


def _ingest(args, cfg) -> None:
    from wx import ingest
    result = ingest.run(cfg, force=args.force)
    print(f"ingest run {result['run_id']}: {result['stations']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wx", description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="download NOAA files, resolve stations, load raw")
    ingest.add_argument("--force", action="store_true", help="reload files even if unchanged")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    cfg = config.load()
    {"ingest": _ingest}[args.command](args, cfg)


if __name__ == "__main__":
    main()
