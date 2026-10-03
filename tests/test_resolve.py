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
    stations = [  # id, state, name, wmo, latitude, longitude
        ("CAN03031092", "AB", "CALGARY INTL A", "71877", 51.1225, -114.0133),
        ("CAN03031109", "AB", "CALGARY SPRINGBANK A", "73126", 51.1033, -114.3744),  # airport, full coverage
        ("CAN03031094", "AB", "CALGARY INT'L CS", "71393", 51.1086, -113.9775),  # climate station nearby
        ("CAN03031093", "AB", "CALGARY INT'L A", "71877", 51.1139, -114.0203),  # retired 2012
        ("CAN07025251", "QC", "MONTREAL INTL A", "71627", 45.4706, -73.7408),
        ("CAN07034900", "QC", "MONTREAL MIRABEL INTL A", None, 45.6667, -74.0333),  # no precipitation
        ("CAN06158731", "ON", "TORONTO INTL A", "71624", 43.6772, -79.6306),
        ("CAN06106001", "ON", "OTTAWA INTL A", "71628", 45.3225, -75.6692),
        ("CAN01108395", "BC", "VANCOUVER INTL A", "71892", 49.1950, -123.1817),
    ]
    current = ["CAN03031092", "CAN03031109", "CAN03031094", "CAN07025251", "CAN06158731", "CAN06106001", "CAN01108395"]
    inventory = [(sid, el, 2013, 2026) for sid in current for el in CORE]
    inventory += [
        ("CAN03031092", "SNOW", 2013, 2026),
        ("CAN03031093", "TMAX", 1881, 2012),
        ("CAN03031093", "TMIN", 1881, 2012),
        ("CAN03031093", "PRCP", 1881, 2012),
        ("CAN07034900", "TMAX", 2018, 2026),
        ("CAN07034900", "TMIN", 2018, 2026),
    ]
    conn.execute(
        "create table raw.stations (id varchar, state varchar, name varchar, wmo_id varchar, "
        "latitude varchar, longitude varchar)"
    )
    conn.executemany(
        "insert into raw.stations values (?, ?, ?, ?, ?, ?)", [(*s[:4], str(s[4]), str(s[5])) for s in stations]
    )
    conn.execute("create table raw.inventory (id varchar, element varchar, first_year varchar, last_year varchar)")
    conn.executemany(
        "insert into raw.inventory values (?, ?, ?, ?)",
        [(sid, el, str(first), str(last)) for sid, el, first, last in inventory],
    )
    return conn


@pytest.fixture
def cfg():
    return config.load()


def test_prefers_the_international_airport(metadata, cfg):
    station = resolve_city(metadata, "r1", cfg, City(city="Calgary", province="AB"), START, END)
    assert station.station_id == "CAN03031092"
    reasons = dict(metadata.execute("select station_id, reason from ops.station_resolution").fetchall())
    assert reasons["CAN03031092"] == "selected: the airport's own station"
    assert reasons["CAN03031109"] == "ranked lower than the city's airport, CALGARY INTL A"
    assert reasons["CAN03031094"].startswith("ranked lower: ")  # qualifies too, but farther away
    assert reasons["CAN03031093"].startswith("reports 0 of 3 required elements")


def test_the_airport_with_full_coverage_outranks_one_without(metadata, cfg):
    # Both are international airports; Mirabel reports no precipitation, so Trudeau is the city's airport.
    station = resolve_city(metadata, "r1", cfg, City(city="Montréal", province="QC"), START, END)
    assert station.station_id == "CAN07025251"
    reason = metadata.execute("select reason from ops.station_resolution where station_id = 'CAN07034900'").fetchone()
    assert reason[0] == "ranked lower than the city's airport, MONTREAL INTL A"


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
    metadata.execute(
        "insert into raw.stations values ('CAN03012209', 'AB', 'EDMONTON INTL A', '71123', " "'53.3097', '-113.5797')"
    )
    metadata.executemany("insert into raw.inventory values ('CAN03012209', ?, '2010', '2026')", [[e] for e in CORE])
    stations = resolve(metadata, "r1", cfg, START, END)
    assert {s.city: s.station_id for s in stations}["Edmonton"] == "CAN03012209"


def test_a_full_tie_goes_to_the_lowest_station_id(metadata, cfg):
    # Identical on every ranking rule; inserted highest ID first so row order would pick it.
    for sid in ("CAN05099999", "CAN05000001"):
        metadata.execute(
            "insert into raw.stations values (?, 'MB', 'WINNIPEG INTL A', '71852', '49.91', '-97.24')", [sid]
        )
        metadata.executemany("insert into raw.inventory values (?, ?, '2010', '2026')", [[sid, e] for e in CORE])
    station = resolve_city(metadata, "r1", cfg, City(city="Winnipeg", province="MB"), START, END)
    assert station.station_id == "CAN05000001"


def test_uses_the_climate_station_beside_an_airport_without_precipitation(metadata, cfg):
    # Newer Environment Canada airport stations often report temperature only; the climate station
    # a kilometre away reports all three. A full-coverage station 8 km away is out of range.
    metadata.executemany(
        "insert into raw.stations values (?, 'MB', ?, ?, ?, ?)",
        [
            ("CAN05023227", "WINNIPEG INTL A", "71852", "49.9100", "-97.2400"),
            ("CAN0502S001", "WINNIPEG A CS", None, "49.9167", "-97.2333"),
            ("CAN05023262", "WINNIPEG THE FORKS", None, "49.8883", "-97.1300"),
        ],
    )
    metadata.executemany(
        "insert into raw.inventory values (?, ?, '2012', '2026')",
        [["CAN05023227", "TMAX"], ["CAN05023227", "TMIN"]]
        + [[sid, e] for sid in ("CAN0502S001", "CAN05023262") for e in CORE],
    )
    station = resolve_city(metadata, "r1", cfg, City(city="Winnipeg", province="MB"), START, END)
    assert station.station_id == "CAN0502S001"
    reason = metadata.execute("select reason from ops.station_resolution where selected").fetchone()[0]
    assert reason.startswith("selected: 0.9 km from WINNIPEG INTL A, which reports 2 of 3 required elements")
    forks = metadata.execute("select reason from ops.station_resolution where station_id = 'CAN05023262'")
    assert forks.fetchone()[0].startswith("name doesn't match")  # full coverage, but 8 km away: not near the airport


def test_a_us_city_needs_only_its_country(metadata, cfg):
    metadata.executemany(
        "insert into raw.stations values (?, 'IL', ?, ?, ?, ?)",
        [
            ("USW00094846", "CHICAGO OHARE INTL AP", "72530", "41.9950", "-87.9336"),
            ("USW00014819", "CHICAGO MIDWAY AP", "72534", "41.7861", "-87.7522"),
        ],
    )
    metadata.executemany(
        "insert into raw.inventory values (?, ?, '1958', '2026')",
        [[sid, e] for sid in ("USW00094846", "USW00014819") for e in CORE],
    )
    chicago = City(city="Chicago", province="IL", country="US")
    assert resolve_city(metadata, "r1", cfg, chicago, START, END).station_id == "USW00094846"


@pytest.mark.parametrize("international", ["HOUSTON INTERCONTINENTAL AP", "HOUSTON HARTSFIELD-JACKSON INT"])
def test_international_airport_names_noaa_spells_differently(metadata, cfg, international):
    # "INTERCONTINENTAL", and names cut off at NOAA's 30 characters, still count as international.
    metadata.executemany(
        "insert into raw.stations values (?, 'TX', ?, null, ?, ?)",
        [
            ("USW00012918", "HOUSTON WILLIAM P HOBBY AP", "29.6381", "-95.2819"),
            ("USW00012960", international, "29.9800", "-95.3600"),
        ],
    )
    metadata.executemany(
        "insert into raw.inventory values (?, ?, '1969', '2026')",
        [[sid, e] for sid in ("USW00012918", "USW00012960") for e in CORE],
    )
    houston = City(city="Houston", province="TX", country="US")
    assert resolve_city(metadata, "r1", cfg, houston, START, END).station_id == "USW00012960"


def test_a_city_without_an_airport_name_fails_loudly(metadata, cfg):
    # Pearson is named TORONTO INTL A, so Mississauga needs a pin or a name_prefix.
    metadata.execute("insert into raw.stations values ('CAN06155555', 'ON', 'MISSISSAUGA', null, '43.6', '-79.6')")
    with pytest.raises(ResolutionError, match="no station named like an airport"):
        resolve_city(metadata, "r1", cfg, City(city="Mississauga", province="ON"), START, END)


def test_unknown_city_fails_loudly(metadata, cfg):
    with pytest.raises(ResolutionError, match="Halifax"):
        resolve_city(metadata, "r1", cfg, City(city="Halifax", province="NS"), START, END)
