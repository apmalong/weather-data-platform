"""NOAA GHCN-Daily file formats, taken from readme.txt.

The fixed-width layouts below are the column tables in readme.txt sections IV-VII (1-based,
inclusive). app/tests/test_formats.py re-reads those tables from the downloaded readme and fails if
NOAA ever changes a layout, so the copy here can't silently drift.

The element catalog (code, description, unit, scale) is parsed from the readme's ELEMENT section,
so element handling is driven by NOAA's own documentation rather than a hand-written list.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    name: str
    start: int  # 1-based, inclusive, as in the readme
    end: int


FIXED_WIDTH: dict[str, list[Column]] = {
    "stations": [  # readme IV
        Column("id", 1, 11),
        Column("latitude", 13, 20),
        Column("longitude", 22, 30),
        Column("elevation", 32, 37),
        Column("state", 39, 40),
        Column("name", 42, 71),
        Column("gsn_flag", 73, 75),
        Column("hcn_crn_flag", 77, 79),
        Column("wmo_id", 81, 85),
    ],
    "countries": [Column("code", 1, 2), Column("name", 4, 64)],  # readme V
    "states": [Column("code", 1, 2), Column("name", 4, 50)],  # readme VI
    "inventory": [  # readme VII
        Column("id", 1, 11),
        Column("latitude", 13, 20),
        Column("longitude", 22, 30),
        Column("element", 32, 35),
        Column("first_year", 37, 40),
        Column("last_year", 42, 45),
    ],
}

# by_station/*.csv.gz: no header row (readme-by_station.txt).
OBSERVATION_COLUMNS = ["station_id", "obs_date", "element", "value", "mflag", "qflag", "sflag", "obs_time"]

README_SECTIONS = {"stations": "IV", "countries": "V", "states": "VI", "inventory": "VII"}


def readme_layouts(readme: str) -> dict[str, list[tuple[str, int, int]]]:
    """The column tables as written in readme.txt: {dataset: [(variable, start, end), ...]}."""
    layouts = {}
    for dataset, numeral in README_SECTIONS.items():
        section = re.search(rf"^{numeral}\. FORMAT OF.*?(?=^[IVX]+\. )", readme, re.M | re.S)
        rows = re.findall(r"^([A-Z][A-Z/ ]*?)\s+(\d+)-\s*(\d+)\s+\w+\s*$", section.group(0), re.M)
        layouts[dataset] = [(name.strip(), int(start), int(end)) for name, start, end in rows]
    return layouts


@dataclass(frozen=True)
class Element:
    code: str  # may be a pattern such as WT** or SN*#
    description: str
    unit: str | None  # unit after scaling, e.g. "degrees C"
    scale: float  # multiply the raw integer by this to get `unit`
    core: bool


_ELEMENT = re.compile(r"^\s{4,}([A-Z0-9*#]{4}) = (.*)$")


def _unit(description: str) -> tuple[str | None, float]:
    """'Maximum temperature (tenths of degrees C)' -> ('degrees C', 0.1)."""
    match = re.search(r"\(([^()]*)\)", description)
    if not match:
        return None, 1.0
    text = match.group(1).split(";")[0].strip()
    if text.startswith("tenths of "):
        return text.removeprefix("tenths of ").strip(), 0.1
    if text.endswith("* 10"):
        return text.removesuffix("* 10").strip(), 0.1
    return text, 1.0


def element_catalog(readme: str) -> list[Element]:
    """Every element defined in the readme's ELEMENT section, with its unit and scale."""
    lines = readme.expandtabs(8).splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("ELEMENT    is the element type"))
    end = next(i for i, line in enumerate(lines[start:], start) if line.startswith("MFLAG"))
    elements, current, core = [], None, False
    for line in lines[start:end]:
        if "core elements" in line:
            core = True
        elif "other elements" in line:
            core = False
        match = _ELEMENT.match(line)
        if match:
            current = [match.group(1), match.group(2).strip(), core]
            elements.append(current)
        elif current and line.strip() and len(line) - len(line.lstrip()) > 11:
            current[1] += " " + line.strip()  # wrapped description
        else:
            current = None
    catalog = []
    for code, description, is_core in elements:
        unit, scale = _unit(description)
        catalog.append(Element(code, " ".join(description.split()), unit, scale, is_core))
    return catalog
