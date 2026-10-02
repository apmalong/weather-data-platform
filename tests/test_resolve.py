from datetime import date

import pytest

from wx import config
from wx.config import City
from wx.noaa.resolve import ResolutionError, resolve, resolve_city

START, END = date(2024, 10, 1), date(2026, 9, 30)
CORE = ["TMAX", "TMIN", "PRCP"]


@pytest.fixture
def metadata(conn):
    """A slice of ghcnd-stations/inventory with the cases that make selection non-trivial."""
    stations = [  # id, state, name, wmo
        ("CAN03031092", "AB", "CALGARY INTL A", "71877"),
        ("CAN03031109", "AB", "CALGARY SPRINGBANK A", "73126"),   # also an airport with full coverage
        ("CAN03031094", "AB", "CALGARY INT'L CS", "71393"),       # climate station, not an airport
        ("CAN03031093", "AB", "CALGARY INT'L A", "71877"),        # retired 2012
        ("CAN07025251", "QC", "MONTREAL INTL A", "71627"),
        ("CAN07034900", "QC", "MONTREAL MIRABEL INTL A", None),   # no precipitation
        ("CAN06158731", "ON", "TORONTO INTL A", "71624"),
        ("CAN06106001", "ON", "OTTAWA INTL A", "71628"),
        ("CAN01108395", "BC", "VANCOUVER INTL A", "71892"),
    ]
    current = ["CAN03031092", "CAN03031109", "CAN03031094", "CAN07025251", "CAN06158731", "CAN06106001", "CAN01108395"]
    inventory = [(sid, el, 2013, 2026) for sid in current for el in CORE]
    inventory += [("CAN03031092", "SNOW", 2013, 2026), ("CAN03031093", "TMAX", 1881, 2012),
                  ("CAN03031093", "TMIN", 1881, 2012), ("CAN03031093", "PRCP", 1881, 2012),
                  ("CAN07034900", "TMAX", 2018, 2026), ("CAN07034900", "TMIN", 2018, 2026)]
    conn.execute("create table raw.stations (id varchar, state varchar, name varchar, wmo_id varchar)")
    conn.executemany("insert into raw.stations values (?, ?, ?, ?)", stations)
    conn.execute("create table raw.inventory (id varchar, element varchar, first_year varchar, last_year varchar)")
    conn.executemany("insert into raw.inventory values (?, ?, ?, ?)",
                     [(sid, el, str(first), str(last)) for sid, el, first, last in inventory])
    return conn


@pytest.fixture
def cfg():
    return config.load()


def test_prefers_the_international_airport(metadata, cfg):
    station = resolve_city(metadata, "r1", cfg, City(city="Calgary", province="AB"), START, END)
    assert station.station_id == "CAN03031092"
    reasons = dict(metadata.execute("select station_id, reason from ops.station_resolution").fetchall())
    assert reasons["CAN03031109"] == "ranked lower than the selected station"
    assert "airport pattern" in reasons["CAN03031094"]
    assert reasons["CAN03031093"].startswith("reports 0 of 3 required elements")


def test_rejects_an_airport_missing_a_required_element(metadata, cfg):
    station = resolve_city(metadata, "r1", cfg, City(city="Montréal", province="QC"), START, END)
    assert station.station_id == "CAN07025251"
    reason = metadata.execute("select reason from ops.station_resolution where station_id = 'CAN07034900'").fetchone()
    assert reason[0].startswith("reports 2 of 3 required elements")


def test_pinned_station_must_still_pass_the_rules(metadata, cfg):
    pinned = City(city="Calgary", province="AB", station_id="CAN03031109")
    assert resolve_city(metadata, "r1", cfg, pinned, START, END).station_id == "CAN03031109"
    retired = City(city="Calgary", province="AB", station_id="CAN03031093")
    with pytest.raises(ResolutionError, match="pinned CAN03031093"):
        resolve_city(metadata, "r1", cfg, retired, START, END)


def test_brief_ids_are_not_in_current_metadata(metadata, cfg):
    stale = City(city="Toronto", province="ON", station_id="CA006158731")  # the brief's pre-v3.35 ID
    with pytest.raises(ResolutionError):
        resolve_city(metadata, "r1", cfg, stale, START, END)


def test_a_new_city_is_configuration_only(metadata, cfg):
    cfg.stations.cities.append(City(city="Edmonton", province="AB"))
    metadata.execute("insert into raw.stations values ('CAN03012209', 'AB', 'EDMONTON INTL A', '71123')")
    metadata.executemany("insert into raw.inventory values ('CAN03012209', ?, '2010', '2026')", [[e] for e in CORE])
    stations = resolve(metadata, "r1", cfg, START, END)
    assert {s.city: s.station_id for s in stations}["Edmonton"] == "CAN03012209"


def test_unknown_city_fails_loudly(metadata, cfg):
    with pytest.raises(ResolutionError, match="Halifax"):
        resolve_city(metadata, "r1", cfg, City(city="Halifax", province="NS"), START, END)
