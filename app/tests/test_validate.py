from wx.narrate.validate import passed, validate

FACTS = [
    {"element": "PRCP", "label": "Precipitation", "value": 0.0, "unit": "mm", "status": "trace"},
    {"element": "TMAX", "label": "Maximum temperature", "value": 21.4, "unit": "degrees C", "status": "valid"},
    {"element": "TMIN", "label": "Minimum temperature", "value": 15.3, "unit": "degrees C", "status": "valid"},
    {"element": "WSFG", "label": "Peak gust wind speed", "value": None, "unit": "km/h", "status": "not_reported"},
    {"element": "SNWD", "label": "Snow depth", "value": None, "unit": "cm", "status": "not_reported"},
]
CITED = [{"element": "TMAX", "value": 21.4}, {"element": "TMIN", "value": 15.3}]


def failures(checks):
    return {c.name for c in checks if not c.passed}


def test_faithful_narrative_passes_and_may_round():
    text = "Toronto peaked at 21 °C after a low of 15.3 °C, with a trace of rain on 2026-09-28."
    checks = validate(text, CITED, FACTS, "2026-09-28")
    assert passed(checks) and failures(checks) == set()


def test_invented_number_fails():
    checks = validate("A high of 21.4 °C, a low of 15.3 °C and gusts to 60 km/h.", CITED, FACTS, "2026-09-28")
    assert "numbers_grounded" in failures(checks) and not passed(checks)


def test_misquoted_citation_fails():
    checks = validate(
        "A high of 23 °C and a low of 15.3 °C.", [{"element": "TMAX", "value": 23}, CITED[1]], FACTS, "2026-09-28"
    )
    assert {"cited_values_match", "numbers_grounded"} <= failures(checks)


def test_citing_an_unusable_fact_fails():
    cited = CITED + [{"element": "WSFG", "value": 0}]
    checks = validate("A high of 21.4 °C, a low of 15.3 °C and gusts of 0 km/h.", cited, FACTS, "2026-09-28")
    assert "cited_only_usable" in failures(checks)


def test_invented_topics_fail_but_weekdays_dont():
    checks = validate("Sunday was humid, a high of 21.4 °C and low of 15.3 °C.", CITED, FACTS, "2026-09-27")
    assert {c.name: c.detail for c in checks if not c.passed} == {"no_invented_topics": "humid"}


def test_missing_temperature_should_be_acknowledged():
    facts = [dict(f, status="missing", value=None) if f["element"] == "TMIN" else f for f in FACTS]
    quiet = validate("A high of 21.4 °C.", CITED[:1], facts, "2026-09-28")
    told = validate("A high of 21.4 °C; the low was not available.", CITED[:1], facts, "2026-09-28")
    assert "acknowledges_gaps" in failures(quiet) and passed(quiet)  # a warning, not a failure
    assert "acknowledges_gaps" not in failures(told)


def test_unicode_minus_is_read_as_negative():
    facts = [{"element": "TMIN", "value": -28.0, "unit": "degrees C", "status": "valid"}]
    checks = validate("A low of −28 °C.", [{"element": "TMIN", "value": -28.0}], facts, "2026-01-24")
    assert passed(checks)


def test_false_claim_of_missing_data_fails_but_clauses_are_kept_apart():
    facts = [
        {"element": "PRCP", "value": 0.0, "status": "valid"},
        {"element": "TMAX", "value": None, "status": "missing"},
        {"element": "TMIN", "value": None, "status": "missing"},
    ]
    wrong = validate("Temperatures and precipitation were missing.", [], facts, "2026-09-16")
    right = validate(
        "Vancouver recorded no measurable precipitation, with temperatures unavailable.", [], facts, "2026-09-16"
    )
    assert "no_false_gaps" in failures(wrong) and not passed(wrong)
    assert "no_false_gaps" not in failures(right)


GUSTY = FACTS[:3] + [
    {"element": "WSFG", "label": "Peak gust wind speed", "value": 32.0, "unit": "km/h", "status": "valid"},
    {
        "element": "WDFG",
        "label": "Direction of peak wind gust",
        "value": 290.0,
        "unit": "degrees",
        "status": "valid",
        "compass": "W",
    },
]


def test_wrong_compass_point_fails():
    # The real failure: 290 degrees written as NW, in 6 of the narratives before compass points were given.
    wrong = validate("Gusts from the NW reached 32 km/h; a trace of rain.", [], GUSTY, "2026-09-16")
    right = validate("Gusts from the west reached 32 km/h; a trace of rain.", [], GUSTY, "2026-09-16")
    assert "compass_matches" in failures(wrong) and "compass_matches" not in failures(right)
    assert "compass_matches" in failures(validate("Gusts from the WNW.", [], GUSTY, "2026-09-16"))


def test_swapped_high_and_low_fail():
    checks = validate("A high of 15 °C and a low of 21 °C, with a trace of rain.", CITED, FACTS, "2026-09-28")
    assert "high_low_attribution" in failures(checks) and not passed(checks)


def test_trace_is_not_dry():
    assert "no_false_zero" in failures(validate("It stayed dry with a high of 21 °C.", [], FACTS, "2026-09-28"))
    assert "no_false_zero" not in failures(
        validate("There was no measurable precipitation, only a trace.", [], FACTS, "2026-09-28")
    )


def test_naming_another_city_fails():
    checks = validate(
        "Montreal reached a high of 21 °C and a low of 15 °C.",
        CITED,
        FACTS,
        "2026-09-28",
        city="Toronto",
        other_cities=["Toronto", "Montreal"],
    )
    assert {c.name: c.severity for c in checks if not c.passed}.get("names_own_city") == "error"


def test_weather_types_never_given_fail():
    assert "no_invented_topics" in failures(validate("Freezing rain fell overnight.", [], FACTS, "2026-09-28"))


def test_intensity_words_need_the_data_to_back_them():
    rules = [{"pattern": r"heavy\b.{0,30}\b(rain|precipitation)", "element": "PRCP", "min": 25, "max": None}]
    checks = validate("Heavy rain fell, a trace in all.", [], FACTS, "2026-09-28", intensity=rules)
    assert {c.name: c.severity for c in checks if not c.passed}.get("intensity_supported") == "warn"
    assert passed(checks) or "no_false_zero" in failures(checks)  # intensity alone never fails a narrative
