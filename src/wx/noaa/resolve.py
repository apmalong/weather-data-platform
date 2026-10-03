"""Resolve each configured city to a station using NOAA's metadata, not hard-coded IDs.

For each city, candidates are stations in raw.stations whose ID starts with the city's country,
whose state is the city's province (or US state) and whose name starts with the city. Then:

1. airport: of the candidates whose name matches selection.airport_name_pattern (Environment
   Canada's "<NAME> A", NOAA's US "<NAME> AP"), the city's airport is the one that matches
   selection.preferred_name_pattern (international airports), then covers more of the required
   elements in the window, then has the most recent data, then a WMO ID, then more elements, then
   the lowest ID.
2. station: the station at that airport that reports every required element across the whole
   window: the airport's own station if it does, otherwise the nearest one within
   selection.max_distance_km. Newer Canadian airport stations often report temperature but not
   precipitation, which a climate station a few hundred metres away does ("WINNIPEG A CS",
   "REGINA RCS"). Ties go to more elements, then the lowest ID, so the result never depends on
   row order.

A pinned station_id skips the search but must exist and report every required element. Every
candidate and the reason it was or wasn't chosen goes to ops.station_resolution.
"""

import re
from dataclasses import dataclass
from datetime import date

from wx import ops
from wx.config import City, Config


class ResolutionError(RuntimeError):
    pass


@dataclass
class Station:
    city: str
    province: str
    station_id: str
    name: str


_COLUMNS = [
    "id",
    "name",
    "wmo_id",
    "latitude",
    "longitude",
    "elements",
    "required_covered",
    "first_year",
    "last_year",
    "distance_km",
]


def _stations(
    conn, cfg: Config, start: date, end: date, where: str, params: list, distance: str = "null"
) -> list[dict]:
    """Stations matching `where`, with how many required elements each reports across the window."""
    rows = conn.execute(
        f"""
        select s.id, s.name, nullif(trim(s.wmo_id), ''), s.latitude::double, s.longitude::double,
               count(distinct i.element),
               count(distinct i.element) filter (where i.element in (select unnest(?::varchar[]))
                   and i.first_year::int <= ? and i.last_year::int >= ?),
               min(i.first_year::int), max(i.last_year::int), {distance}
        from raw.stations s left join raw.inventory i on i.id = s.id
        where {where}
        group by all""",
        [cfg.stations.selection.required_elements, start.year, end.year, *params],
    ).fetchall()
    return [dict(zip(_COLUMNS, r, strict=True)) for r in rows]


def _nearby(conn, cfg: Config, country: str, anchor: dict, start: date, end: date) -> list[dict]:
    """Every station in the country within max_distance_km of the airport, nearest first."""
    km = cfg.stations.selection.max_distance_km
    haversine = """round(6371 * 2 * asin(sqrt(pow(sin(radians(s.latitude::double - $lat) / 2), 2)
                   + cos(radians($lat)) * cos(radians(s.latitude::double))
                   * pow(sin(radians(s.longitude::double - $lon) / 2), 2))), 1)"""
    distance = haversine.replace("$lat", str(anchor["latitude"])).replace("$lon", str(anchor["longitude"]))
    rows = _stations(conn, cfg, start, end, f"s.id like ? || '%' and {distance} <= ?", [country, km], distance)
    return sorted(rows, key=lambda c: c["distance_km"])


def resolve_city(conn, run_id: str, cfg: Config, city: City, start: date, end: date) -> Station:
    selection = cfg.stations.selection
    required = len(selection.required_elements)
    country = city.country or cfg.stations.country
    window = f"across {start.year}-{end.year}"
    log: dict[str, tuple[dict, bool, int | None, str]] = {}

    if city.station_id:
        pinned = _stations(conn, cfg, start, end, "s.id = ?", [city.station_id])
        if pinned and pinned[0]["required_covered"] == required:
            _log(conn, run_id, city, pinned[0], True, 1, "selected: pinned in config")
            return Station(city.city, city.province, city.station_id, pinned[0]["name"])
        for c in pinned:
            _log(
                conn,
                run_id,
                city,
                c,
                False,
                None,
                f"reports {c['required_covered']} of {required} required " f"elements {window}",
            )
        raise ResolutionError(
            f"{city.city}, {city.province} (pinned {city.station_id}): the station isn't in the "
            f"metadata or doesn't report {', '.join(selection.required_elements)} {window}"
        )

    candidates = _stations(
        conn,
        cfg,
        start,
        end,
        "s.id like ? || '%' and s.state = ? and s.name like ? || '%'",
        [country, city.province, city.prefix],
    )
    airports = [c for c in candidates if re.search(selection.airport_name_pattern, c["name"] or "")]
    for c in candidates:
        if c not in airports:
            log[c["id"]] = (c, False, None, f"name doesn't match airport pattern {selection.airport_name_pattern!r}")
    airports.sort(
        key=lambda c: (
            not re.search(selection.preferred_name_pattern, c["name"]),
            -c["required_covered"],
            -(c["last_year"] or 0),
            not c["wmo_id"],
            -c["elements"],
            c["id"],
        )
    )
    if not airports:
        _write(conn, run_id, city, log)
        raise ResolutionError(
            f"{city.city}, {city.province}: no station named like an airport "
            f"({selection.airport_name_pattern!r}) in the metadata; set name_prefix or pin a "
            f"station_id. See ops.station_resolution for run {run_id}"
        )
    anchor = airports[0]
    for c in airports[1:]:
        log[c["id"]] = (c, False, None, f"ranked lower than the city's airport, {anchor['name']}")

    nearby = _nearby(conn, cfg, country, anchor, start, end)
    usable = [c for c in nearby if c["required_covered"] == required]
    usable.sort(key=lambda c: (c["distance_km"], -c["elements"], c["id"]))
    for c in nearby:
        if c not in usable:
            log[c["id"]] = (
                c,
                False,
                None,
                f"reports {c['required_covered']} of {required} required elements " f"{window}",
            )
    for position, c in enumerate(usable, 1):
        if position == 1:
            reason = (
                "selected: the airport's own station"
                if c["id"] == anchor["id"]
                else f"selected: {c['distance_km']} km from {anchor['name']}, which reports "
                f"{anchor['required_covered']} of {required} required elements {window}"
            )
        else:
            reason = f"ranked lower: {c['distance_km']} km from {anchor['name']}"
        log[c["id"]] = (c, position == 1, position, reason)
    _write(conn, run_id, city, log)
    if not usable:
        raise ResolutionError(
            f"{city.city}, {city.province}: no station within {selection.max_distance_km} km of "
            f"{anchor['name']} reports {', '.join(selection.required_elements)} {window}; "
            f"see ops.station_resolution for run {run_id}"
        )
    best = usable[0]
    return Station(city.city, city.province, best["id"], best["name"])


def _write(conn, run_id: str, city: City, log: dict) -> None:
    for c, selected, rank, reason in log.values():
        _log(conn, run_id, city, c, selected, rank, reason)


def _log(conn, run_id, city: City, c: dict, selected: bool, rank, reason: str) -> None:
    conn.execute(
        "insert into ops.station_resolution values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [run_id, city.city, city.province, c["id"], c["name"], selected, rank, reason, ops.now()],
    )


def resolve(conn, run_id: str, cfg: Config, start: date, end: date) -> list[Station]:
    stations = [resolve_city(conn, run_id, cfg, city, start, end) for city in cfg.stations.cities]
    duplicates = {s.station_id for s in stations if sum(t.station_id == s.station_id for t in stations) > 1}
    if duplicates:
        raise ResolutionError(f"several cities resolved to the same station: {sorted(duplicates)}")
    return stations
