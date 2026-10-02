"""Validate a narrative against the facts it was written from (the bonus "compare LLM narratives
against source data"). Pure functions, shared by the pipeline and the eval harness.

Errors fail the narrative; warnings are recorded but don't.
  cited_values_match     every number the model says it used matches the fact it names
  cited_only_usable      it cites no fact whose status makes the value unusable
  numbers_grounded       every number in the text matches some usable fact (rounding allowed)
  no_invented_topics     it doesn't talk about things it wasn't given (forecasts, humidity...)
  mentions_temperatures  warn: high and low were usable but not both mentioned
  acknowledges_gaps      warn: a temperature or precipitation reading was missing but not mentioned
  length                 warn: 1-3 sentences, at most 450 characters
"""
import re
from dataclasses import dataclass

USABLE = {"valid", "trace"}
# Topics the facts never contain; mentioning them means the model made something up.
INVENTED = re.compile(r"\b(forecast|tomorrow|humid\w*|cloud\w*|sunny|sunshine|fog\w*|visibility|record|thunder\w*|"
                      r"pressure|warmer than|colder than|than yesterday)\b", re.I)
GAP_WORDS = re.compile(r"\b(not available|unavailable|missing|no reading|wasn't recorded|was not recorded)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])[-−]?\d+(?:\.\d+)?")


@dataclass
class Check:
    name: str
    passed: bool
    severity: str  # error | warn
    detail: str = ""


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.51  # the prompt allows rounding to whole numbers


def validate(narrative: str, cited: list[dict], facts: list[dict], obs_date: str) -> list[Check]:
    by_element = {f["element"]: f for f in facts}
    usable_values = [f["value"] for f in facts if f["status"] in USABLE and f["value"] is not None]
    checks = []

    wrong = []
    for c in cited:
        fact = by_element.get(c.get("element"))
        if not fact or fact["value"] is None or not _close(float(c["value"]), float(fact["value"])):
            wrong.append(f"{c.get('element')}={c.get('value')} (fact: {fact['value'] if fact else 'none'})")
    checks.append(Check("cited_values_match", not wrong, "error", "; ".join(wrong)))

    unusable = [c["element"] for c in cited if by_element.get(c.get("element"), {}).get("status") not in USABLE]
    checks.append(Check("cited_only_usable", not unusable, "error", ", ".join(map(str, unusable))))

    date_parts = {float(p) for p in re.findall(r"\d+", obs_date)}
    text = narrative.replace("−", "-").replace(",", "")
    ungrounded = []
    for raw in NUMBER.findall(text):
        n = float(raw)
        if n in date_parts or abs(n) in date_parts:
            continue
        if not any(_close(n, v) or _close(abs(n), abs(v)) for v in usable_values):
            ungrounded.append(raw)
    checks.append(Check("numbers_grounded", not ungrounded, "error", ", ".join(ungrounded)))

    invented = sorted({m.lower() for m in INVENTED.findall(narrative)})
    checks.append(Check("no_invented_topics", not invented, "error", ", ".join(invented)))

    temps = [by_element.get(e) for e in ("TMAX", "TMIN")]
    if all(t and t["status"] in USABLE for t in temps):
        mentioned = {c["element"] for c in cited}
        ok = {"TMAX", "TMIN"} <= mentioned
        checks.append(Check("mentions_temperatures", ok, "warn", "" if ok else "high or low not cited"))

    gaps = [e for e in ("TMAX", "TMIN", "PRCP") if by_element.get(e, {}).get("status") in
            ("missing", "qc_failed", "out_of_bounds", "unparseable")]
    if gaps:
        ok = bool(GAP_WORDS.search(narrative))
        checks.append(Check("acknowledges_gaps", ok, "warn", "" if ok else f"{', '.join(gaps)} unavailable"))

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", narrative.strip()) if s]
    ok = 1 <= len(sentences) <= 3 and len(narrative) <= 450
    checks.append(Check("length", ok, "warn", f"{len(sentences)} sentences, {len(narrative)} chars"))
    return checks


def passed(checks: list[Check]) -> bool:
    return all(c.passed for c in checks if c.severity == "error")
