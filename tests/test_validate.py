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
    checks = validate("A high of 23 °C and a low of 15.3 °C.", [{"element": "TMAX", "value": 23}, CITED[1]],
                      FACTS, "2026-09-28")
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
    facts = [{"element": "PRCP", "value": 0.0, "status": "valid"},
             {"element": "TMAX", "value": None, "status": "missing"},
             {"element": "TMIN", "value": None, "status": "missing"}]
    wrong = validate("Temperatures and precipitation were missing.", [], facts, "2026-09-16")
    right = validate("Vancouver recorded no measurable precipitation, with temperatures unavailable.", [], facts,
                     "2026-09-16")
    assert "no_false_gaps" in failures(wrong) and not passed(wrong)
    assert "no_false_gaps" not in failures(right)
