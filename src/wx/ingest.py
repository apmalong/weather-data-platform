"""Ingest: download NOAA's reference files and the selected stations' observations, load them into
raw, and publish the run's configuration for dbt.

    reference files -> raw.stations/inventory/countries/states/documents/element_catalog
    resolve cities  -> config.selected_stations (+ ops.station_resolution)
    station files   -> raw.observations (+ raw.observation_changes)
    pipeline.yml    -> config.elements, config.window

dbt reads only the warehouse, so `dbt build` on its own sees the same scope as `wx run`.
"""
import logging
from datetime import date

from wx import ops
from wx.config import Config
from wx.noaa import fetch, formats, load, resolve

log = logging.getLogger(__name__)


class LayoutChanged(RuntimeError):
    pass


def _check_layouts(conn, run_id: str, readme: str) -> None:
    """Stop before parsing anything if NOAA's documented column layouts no longer match ours."""
    documented = formats.readme_layouts(readme)
    for dataset, columns in formats.FIXED_WIDTH.items():
        ours = [(c.start, c.end) for c in columns]
        theirs = [(start, end) for _, start, end in documented.get(dataset, [])]
        if not ops.check(conn, run_id, "ingest", "readme_layout_matches", dataset, ours == theirs, theirs, ours):
            raise LayoutChanged(f"readme.txt documents a different layout for {dataset}: {theirs}")


def _reference(conn, run_id: str, cfg: Config, force: bool) -> None:
    base = cfg.source.base_url.rstrip("/")
    files = cfg.source.reference_files
    # The readme first: it defines the layouts the other files are parsed with.
    for name, filename in sorted(files.items(), key=lambda item: item[0] != "readme"):
        got = fetch.download(conn, run_id, f"{base}/{filename}", cfg.data_dir / "raw" / "reference" / filename)
        if name == "readme":
            _check_layouts(conn, run_id, got.path.read_text(encoding="utf-8"))
        if not (got.changed or force or not _loaded(conn, name)):
            log.info("%s unchanged, skipped", filename)
            continue
        if name in ("readme", "status"):
            load.load_text(conn, run_id, name, got.path, got.sha256)
            if name == "readme":
                count = load.load_element_catalog(conn, run_id, got.path.read_text(encoding="utf-8"))
                log.info("element catalog: %d elements from readme", count)
        else:
            rows = load.load_fixed_width(conn, run_id, name, got.path, got.sha256)
            log.info("%s: %d rows", filename, rows)


def _loaded(conn, dataset: str) -> bool:
    return bool(conn.execute("select count(*) from ops.loads where dataset = ?", [dataset]).fetchone()[0])


def _publish_config(conn, cfg: Config, stations: list[resolve.Station], start: date, end: date, run_id: str) -> None:
    conn.execute("create schema if not exists config")
    conn.execute("create or replace table config.selected_stations (city varchar, province varchar, "
                 "station_id varchar, station_name varchar, run_id varchar)")
    conn.executemany("insert into config.selected_stations values (?, ?, ?, ?, ?)",
                     [[s.city, s.province, s.station_id, s.name, run_id] for s in stations])
    conn.execute("create or replace table config.window (start_date date, end_date date, run_id varchar)")
    conn.execute("insert into config.window values (?, ?, ?)", [start, end, run_id])
    q = cfg.quality
    conn.execute("create or replace table config.quality (freshness_warn_days integer, freshness_error_days integer, "
                 "volume_change_warn_pct double)")
    conn.execute("insert into config.quality values (?, ?, ?)",
                 [q.freshness_warn_days, q.freshness_error_days, q.volume_change_warn_pct])
    e = cfg.elements
    codes = sorted(set(e.exclude) | set(e.absent_means_zero) | set(e.bounds) | set(e.display))
    conn.execute("create or replace table config.elements (element varchar, excluded boolean, "
                 "absent_means_zero boolean, lower_bound double, upper_bound double, display_unit varchar, "
                 "display_factor double)")
    conn.executemany("insert into config.elements values (?, ?, ?, ?, ?, ?, ?)",
                     [[c, c in e.exclude, c in e.absent_means_zero, *(e.bounds.get(c) or (None, None)),
                       e.display[c].unit if c in e.display else None,
                       e.display[c].factor if c in e.display else None] for c in codes])


def run(cfg: Config, force: bool = False, today: date | None = None) -> dict:
    start, end = cfg.window.bounds(today)
    conn = ops.connect(cfg.warehouse)
    load.ensure_schema(conn)
    try:
        with ops.run(conn, "ingest") as (run_id, details):
            _reference(conn, run_id, cfg, force)
            stations = resolve.resolve(conn, run_id, cfg, start, end)
            for s in stations:
                log.info("%s -> %s (%s)", s.city, s.station_id, s.name)
            base = cfg.source.base_url.rstrip("/")
            for s in stations:
                got = fetch.download(conn, run_id, f"{base}/by_station/{s.station_id}.csv.gz",
                                     cfg.data_dir / "raw" / "by_station" / f"{s.station_id}.csv.gz")
                loaded = conn.execute("select count(*) from raw.observations where station_id = ?",
                                      [s.station_id]).fetchone()[0]
                if got.changed or force or not loaded:
                    counts = load.load_observations(conn, run_id, s.station_id, got.path, got.sha256)
                    log.info("%s: %s", s.station_id, counts)
                    details[s.station_id] = counts
                else:
                    log.info("%s unchanged, skipped", s.station_id)
            _publish_config(conn, cfg, stations, start, end, run_id)
            details["window"] = [str(start), str(end)]
            details["stations"] = {s.city: s.station_id for s in stations}
        return {"run_id": run_id, **details}
    finally:
        conn.close()
