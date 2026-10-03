"""Validate a narrative against the facts it was written from (the bonus "compare LLM narratives
against source data"). Pure functions, shared by the pipeline and the eval harness.

Errors fail the narrative; warnings are recorded but don't.
  cited_values_match     every number the model says it used matches the fact it names
  cited_only_usable      it cites no fact whose status makes the value unusable
  numbers_grounded       every number in the text matches some usable fact (rounding allowed)
  high_low_attribution   "a high of N °C" matches TMAX and "a low of N °C" matches TMIN
  compass_matches        any wind direction named is the compass point given in the facts
  no_false_zero          "dry", "no rain", "no snow" only when the value really was zero
  no_false_gaps          it doesn't call a reading missing or unavailable when it was usable
  no_invented_topics     nothing it wasn't given: forecasts, humidity, cloud, hail, sleet...
  names_own_city         it names no other city (error); warn if it doesn't name its own
  intensity_supported    warn: "heavy rain", "bitterly cold"... only past config thresholds
  mentions_temperatures  warn: high and low were usable but not both mentioned
  acknowledges_gaps      warn: a temperature or precipitation reading was missing but not mentioned
  length                 warn: 1-3 sentences, at most 450 characters
"""

import re
from dataclasses import dataclass

USABLE = {"valid", "trace"}
UNAVAILABLE = {"missing", "qc_failed", "out_of_bounds", "inconsistent", "unparseable"}

# Topics and weather types the facts never contain; mentioning them means the model made it up.
INVENTED = re.compile(
    r"\b(forecast|tomorrow|humid\w*|cloud\w*|sunny|sunshine|fog\w*|visibility|record|thunder\w*|pressure|"
    r"warmer than|colder than|than yesterday|hail\w*|sleet|freezing rain|freezing drizzle|drizzl\w*|"
    r"ice pellets|lightning|tornado\w*|hurricane|smoke|haze|hazy)\b",
    re.I,
)
GAP_WORDS = re.compile(r"\b(not available|unavailable|missing|no reading|wasn't recorded|was not recorded)\b", re.I)
# Which elements a clause is about, for checking claims that a reading was missing.
TOPICS = {
    "temperature": ("TMAX", "TMIN"),
    "precipitation": ("PRCP",),
    "rain": ("PRCP",),
    "snowfall": ("SNOW",),
    "gust": ("WSFG",),
    "wind": ("WSFG",),
}
NUMBER = re.compile(r"(?<![\w.])[-−]?\d+(?:\.\d+)?")
CLAUSES = re.compile(r"[.!?;,]\s+")

# "a high of 21 °C", "highs near 21 degrees": the number must be a temperature to be attributed.
TEMPERATURE_CLAIM = r"\b{word}s?\b[^.;\d−-]{{0,20}}?([-−]?\d+(?:\.\d+)?)\s*(?:°|degrees?\b)"

# Compass points: 8-point abbreviations and words map to themselves; 16-point ones (WNW) never match
# the 8-point point the facts give, so they fail, which is the point.
COMPASS_ABBR = re.compile(r"(?<![\w-])(NNE|ENE|ESE|SSE|SSW|WSW|WNW|NNW|NE|SE|SW|NW|N|E|S|W)(?![\w-])")
COMPASS_WORD = re.compile(r"\b(north|south)?-?(east|west)?(?:erly|ern)?\b", re.I)
WORD_TO_POINT = {
    ("north", None): "N",
    ("south", None): "S",
    (None, "east"): "E",
    (None, "west"): "W",
    ("north", "east"): "NE",
    ("north", "west"): "NW",
    ("south", "east"): "SE",
    ("south", "west"): "SW",
}

# Claims that something was zero.
DRY = re.compile(
    r"\b(stayed|remained|was|were|kept)\s+dry\b|\bdry\s+(day|conditions|weather|skies)\b|"
    r"\bno\s+(rain|precipitation)\b",
    re.I,
)
NO_MEASURABLE = re.compile(r"\bno\s+measurable\s+(rain|precipitation)\b", re.I)  # true for a trace too
NO_SNOWFALL = re.compile(r"\bno\s+(new\s+)?snow(fall)?\b(?!\s+on\s+the\s+ground)", re.I)
NO_SNOW_ON_GROUND = re.compile(r"\bno\s+snow\s+on\s+the\s+ground\b", re.I)


@dataclass
class Check:
    name: str
    passed: bool
    severity: str  # error | warn
    detail: str = ""


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.51  # the prompt allows rounding to whole numbers


MONTHS = "January February March April May June July August September October November December".split()


def _without_date(text: str, obs_date: str) -> str:
    """The text with its own date removed ("2026-09-12", "September 12th", "12 Sep, 2026", "2026"), so
    the date's numbers aren't checked as quantities. Only date expressions are removed: a bare 12 on
    the 12th is still a number that has to match a fact ("12 mm of rain" on a dry day fails)."""
    try:
        year, month, day = (int(p) for p in obs_date.split("-"))
        name = MONTHS[month - 1]
    except (ValueError, IndexError):
        return text
    month_word = rf"(?:{name}|{name[:3]}\.?)"
    day_word = rf"0?{day}(?:st|nd|rd|th)?"
    for pattern in (
        rf"\b{year}-0?{month}-0?{day}\b",
        rf"\b{month_word}\s+{day_word}\b",
        rf"\b{day_word}\s+{month_word}\b",
        rf"\b{year}\b",
    ):
        text = re.sub(pattern, " ", text, flags=re.I)
    return text


def _get(rule, key):
    return rule.get(key) if isinstance(rule, dict) else getattr(rule, key)


def _compass_named(narrative: str) -> list[str]:
    points = COMPASS_ABBR.findall(narrative)
    for north_south, east_west in COMPASS_WORD.findall(narrative):
        key = (north_south.lower() or None, east_west.lower() or None)
        if key in WORD_TO_POINT:
            points.append(WORD_TO_POINT[key])
    return points


def validate(
    narrative: str,
    cited: list[dict],
    facts: list[dict],
    obs_date: str,
    city: str | None = None,
    other_cities: tuple[str, ...] | list[str] = (),
    intensity=(),
) -> list[Check]:
    by_element = {f["element"]: f for f in facts}
    usable_values = [f["value"] for f in facts if f["status"] in USABLE and f["value"] is not None]
    text = narrative.replace("−", "-")
    checks = []

    wrong = []
    for c in cited:
        fact = by_element.get(c.get("element"))
        if not fact or fact["value"] is None or not _close(float(c["value"]), float(fact["value"])):
            wrong.append(f"{c.get('element')}={c.get('value')} (fact: {fact['value'] if fact else 'none'})")
    checks.append(Check("cited_values_match", not wrong, "error", "; ".join(wrong)))

    unusable = [c["element"] for c in cited if by_element.get(c.get("element"), {}).get("status") not in USABLE]
    checks.append(Check("cited_only_usable", not unusable, "error", ", ".join(map(str, unusable))))

    ungrounded = []
    for raw in NUMBER.findall(_without_date(text, obs_date).replace(",", "")):
        n = float(raw)
        if not any(_close(n, v) or _close(abs(n), abs(v)) for v in usable_values):
            ungrounded.append(raw)
    checks.append(Check("numbers_grounded", not ungrounded, "error", ", ".join(ungrounded)))

    misattributed = []
    for word, element in (("high", "TMAX"), ("low", "TMIN")):
        fact = by_element.get(element, {})
        for match in re.finditer(TEMPERATURE_CLAIM.format(word=word), text, re.I):
            value = float(match.group(1))
            if fact.get("status") not in USABLE or fact.get("value") is None or not _close(value, fact["value"]):
                misattributed.append(f"{word} {match.group(1)} (fact {element}: {fact.get('value')})")
    checks.append(Check("high_low_attribution", not misattributed, "error", "; ".join(misattributed)))

    expected = {f["compass"] for f in facts if f.get("compass")}
    named = _compass_named(narrative)
    wrong_points = [p for p in named if p not in expected]
    checks.append(
        Check(
            "compass_matches",
            not wrong_points,
            "error",
            (
                f"named {', '.join(wrong_points)}; facts give {', '.join(sorted(expected)) or 'no direction'}"
                if wrong_points
                else ""
            ),
        )
    )

    false_zero = []
    prcp, snow, snwd = (by_element.get(e, {}) for e in ("PRCP", "SNOW", "SNWD"))
    for clause in CLAUSES.split(text):
        if NO_MEASURABLE.search(clause):
            if not (prcp.get("status") == "trace" or (prcp.get("status") == "valid" and prcp.get("value") == 0)):
                false_zero.append(f"no measurable precipitation, but PRCP is {prcp.get('status')} {prcp.get('value')}")
        elif DRY.search(clause) and not (prcp.get("status") == "valid" and prcp.get("value") == 0):
            false_zero.append(f"dry/no precipitation, but PRCP is {prcp.get('status')} {prcp.get('value')}")
        if NO_SNOWFALL.search(clause) and not (snow.get("status") == "valid" and snow.get("value") == 0):
            false_zero.append(f"no snowfall, but SNOW is {snow.get('status')} {snow.get('value')}")
        if NO_SNOW_ON_GROUND.search(clause) and not (
            snwd.get("status") == "not_reported" or (snwd.get("status") == "valid" and snwd.get("value") == 0)
        ):
            false_zero.append(f"no snow on the ground, but SNWD is {snwd.get('status')} {snwd.get('value')}")
    checks.append(Check("no_false_zero", not false_zero, "error", "; ".join(false_zero)))

    false_gaps = []
    # Clause by clause, so "no precipitation, with temperatures unavailable" ties the gap to temperature.
    for clause in CLAUSES.split(narrative):
        if GAP_WORDS.search(clause):
            for word, elements in TOPICS.items():
                if re.search(rf"\b{word}", clause, re.I) and all(
                    by_element.get(e, {}).get("status") in USABLE for e in elements
                ):
                    false_gaps.append(word)
    checks.append(Check("no_false_gaps", not false_gaps, "error", ", ".join(sorted(set(false_gaps)))))

    invented = sorted({m.lower() for m in INVENTED.findall(narrative)})
    checks.append(Check("no_invented_topics", not invented, "error", ", ".join(invented)))

    if city or other_cities:
        others = [c for c in other_cities if c != city and re.search(rf"\b{re.escape(c)}\b", narrative, re.I)]
        checks.append(Check("names_own_city", not others, "error", f"names {', '.join(others)}" if others else ""))
        if city and not others and not re.search(rf"\b{re.escape(city)}\b", narrative, re.I):
            checks.append(Check("names_own_city", False, "warn", f"{city} isn't named"))

    unsupported = []
    for rule in intensity:
        match = re.search(_get(rule, "pattern"), narrative, re.I)
        if not match:
            continue
        fact = by_element.get(_get(rule, "element"), {})
        value = (
            fact.get("value")
            if fact.get("status") in USABLE
            else 0 if fact.get("status") in ("not_reported", None) else None
        )
        low, high = _get(rule, "min"), _get(rule, "max")
        if value is None or (low is not None and value < low) or (high is not None and value > high):
            unsupported.append(f"'{match.group(0)}' with {_get(rule, 'element')}={value}")
    if intensity:
        checks.append(Check("intensity_supported", not unsupported, "warn", "; ".join(unsupported)))

    temps = [by_element.get(e) for e in ("TMAX", "TMIN")]
    if all(t and t["status"] in USABLE for t in temps):
        mentioned = {c["element"] for c in cited}
        ok = {"TMAX", "TMIN"} <= mentioned
        checks.append(Check("mentions_temperatures", ok, "warn", "" if ok else "high or low not cited"))

    gaps = [e for e in ("TMAX", "TMIN", "PRCP") if by_element.get(e, {}).get("status") in UNAVAILABLE]
    if gaps:
        ok = bool(GAP_WORDS.search(narrative))
        checks.append(Check("acknowledges_gaps", ok, "warn", "" if ok else f"{', '.join(gaps)} unavailable"))

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", narrative.strip()) if s]
    ok = 1 <= len(sentences) <= 3 and len(narrative) <= 450
    checks.append(Check("length", ok, "warn", f"{len(sentences)} sentences, {len(narrative)} chars"))
    return checks


def passed(checks: list[Check]) -> bool:
    return all(c.passed for c in checks if c.severity == "error")


def nothing_to_report(facts: list[dict]) -> bool:
    """No usable temperature or precipitation: there's nothing for a model to describe, only to
    invent, so the pipeline writes a fixed sentence instead of calling it."""
    by_element = {f["element"]: f for f in facts}
    return not any(by_element.get(e, {}).get("status") in USABLE for e in ("TMAX", "TMIN", "PRCP"))
