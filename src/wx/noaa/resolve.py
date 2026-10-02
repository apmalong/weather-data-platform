"""Resolve each configured city to a station using NOAA's metadata, not hard-coded IDs.

For each city, candidates are stations in raw.stations whose ID starts with the configured
country, whose state is the city's province and whose name starts with the city. Then:

1. airport: the name matches selection.airport_name_pattern (Environment Canada's "<NAME> A"),
2. coverage: raw.inventory shows every required element reported across the whole window,
3. rank: prefer selection.preferred_name_pattern (international airports), then a WMO ID, then
   more elements, then the longer record.

A pinned station_id skips the search but must still pass rules 1-2's metadata checks. Every
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


def _candidates(conn, cfg: Config, city: City, start: date, end: date) -> list[dict]:
    required = cfg.stations.selection.required_elements
    rows = conn.execute("""
        select s.id, s.name, s.wmo_id,
               count(distinct i.element) as elements,
               count(distinct i.element) filter (where i.element in (select unnest(?::varchar[]))
                   and i.first_year::int <= ? and i.last_year::int >= ?) as required_covered,
               min(i.first_year::int) as first_year, max(i.last_year::int) as last_year
        from raw.stations s left join raw.inventory i on i.id = s.id
        where s.id like ? || '%' and s.state = ? and (s.name like ? || '%' or s.id = ?)
        group by all""", [required, start.year, end.year, cfg.stations.country, city.province,
                          city.prefix, city.station_id or ""]).fetchall()
    return [dict(zip(["id", "name", "wmo_id", "elements", "required_covered", "first_year", "last_year"], r,
                     strict=True)) for r in rows]


def resolve_city(conn, run_id: str, cfg: Config, city: City, start: date, end: date) -> Station:
    selection = cfg.stations.selection
    required = len(selection.required_elements)
    candidates = _candidates(conn, cfg, city, start, end)
    ranked, rejected = [], []
    for c in candidates:
        if city.station_id and c["id"] != city.station_id:
            rejected.append((c, "not the pinned station_id"))
        elif not re.search(selection.airport_name_pattern, c["name"] or ""):
            rejected.append((c, f"name doesn't match airport pattern {selection.airport_name_pattern!r}"))
        elif c["required_covered"] < required:
            rejected.append((c, f"reports {c['required_covered']} of {required} required elements "
                                f"across {start.year}-{end.year}"))
        else:
            ranked.append(c)
    ranked.sort(key=lambda c: (not re.search(selection.preferred_name_pattern, c["name"]), not c["wmo_id"],
                               -c["elements"], c["first_year"] or 9999))
    for position, c in enumerate(ranked, 1):
        reason = "selected" if position == 1 else "ranked lower than the selected station"
        _log(conn, run_id, city, c, position == 1, position, reason)
    for c, reason in rejected:
        _log(conn, run_id, city, c, False, None, reason)
    if not ranked:
        pinned = f" (pinned {city.station_id})" if city.station_id else ""
        raise ResolutionError(f"{city.city}, {city.province}{pinned}: no station in the metadata passes the "
                              f"selection rules; see ops.station_resolution for run {run_id}")
    best = ranked[0]
    return Station(city.city, city.province, best["id"], best["name"])


def _log(conn, run_id, city: City, c: dict, selected: bool, rank, reason: str) -> None:
    conn.execute("insert into ops.station_resolution values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 [run_id, city.city, city.province, c["id"], c["name"], selected, rank, reason, ops.now()])


def resolve(conn, run_id: str, cfg: Config, start: date, end: date) -> list[Station]:
    stations = [resolve_city(conn, run_id, cfg, city, start, end) for city in cfg.stations.cities]
    duplicates = {s.station_id for s in stations if sum(t.station_id == s.station_id for t in stations) > 1}
    if duplicates:
        raise ResolutionError(f"several cities resolved to the same station: {sorted(duplicates)}")
    return stations
