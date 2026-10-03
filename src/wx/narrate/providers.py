"""Narrative providers: Gemini (google-genai) and an offline mock with the same interface.

The Gemini connector is built for the free tier and for keys we don't control (graders use their
own): the key comes only from GEMINI_API_KEY; models are tried in configured order and a model
retired for the key (404) falls through to the next; a per-minute 429 waits the delay the API asks
for; a per-day 429 moves to the next model (quotas are per model) and, when none is left, raises
QuotaExhausted so the run stops cleanly and the next run resumes from the cache.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "narratives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "station_id": {"type": "string"},
                    "date": {"type": "string"},
                    "narrative": {"type": "string"},
                    "cited": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"element": {"type": "string"}, "value": {"type": "number"}},
                            "required": ["element", "value"],
                        },
                    },
                },
                "required": ["station_id", "date", "narrative", "cited"],
            },
        }
    },
    "required": ["narratives"],
}


@dataclass
class StationDay:
    station_id: str
    city: str
    province: str
    station_name: str
    obs_date: str
    facts: list[dict]
    input_hash: str
    feedback: dict | None = None  # a repair request: the previous recap and what was wrong with it

    def payload(self) -> dict:
        return {
            "station_id": self.station_id,
            "city": f"{self.city}, {self.province}",
            "station": self.station_name,
            "date": self.obs_date,
            "facts": self.facts,
            **(self.feedback or {}),
        }


@dataclass
class Call:
    drafts: list[dict]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 1
    waited_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


class QuotaExhausted(RuntimeError):
    """Every configured model's daily quota is used up; resume tomorrow (cached work is kept)."""


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    @property
    def model(self) -> str: ...

    def generate(self, days: list[StationDay], instructions: str) -> Call: ...


class GeminiProvider:
    name = "gemini"

    def __init__(
        self, api_key: str, models: list[str], temperature: float, max_attempts: int = 4, client=None, sleep=time.sleep
    ):
        if client is None:
            from google import genai  # imported here so the mock path needs no SDK

            client = genai.Client(api_key=api_key)
        self._client = client
        self._sleep = sleep
        self._models = list(models)
        self._temperature = temperature
        self._max_attempts = max_attempts

    @property
    def model(self) -> str:
        if not self._models:
            raise QuotaExhausted("no usable Gemini model left")
        return self._models[0]

    def generate(self, days: list[StationDay], instructions: str) -> Call:
        from google.genai import errors, types

        contents = json.dumps([d.payload() for d in days], ensure_ascii=False)
        config = types.GenerateContentConfig(
            system_instruction=instructions,
            response_mime_type="application/json",
            response_json_schema=RESPONSE_SCHEMA,
            temperature=self._temperature,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        attempts, waited, notes = 0, 0.0, []
        while True:
            model = self.model
            attempts += 1
            try:
                response = self._client.models.generate_content(model=model, contents=contents, config=config)
            except errors.APIError as exc:
                detail = json.dumps(getattr(exc, "details", None) or str(exc))
                if exc.code == 404:
                    notes.append(f"{model}: not available for this key, trying the next model")
                    log.warning(notes[-1])
                    self._models.pop(0)
                    continue
                if exc.code == 429 and "PerDay" in detail:
                    notes.append(f"{model}: daily quota exhausted, trying the next model")
                    log.warning(notes[-1])
                    self._models.pop(0)
                    continue
                if exc.code in (429, 500, 502, 503, 504) and attempts < self._max_attempts:
                    delay = _retry_delay(detail) or min(60, 2**attempts * 5)
                    notes.append(f"{model}: {exc.code}, retrying in {delay:.0f}s")
                    log.warning(notes[-1])
                    self._sleep(delay)
                    waited += delay
                    continue
                raise ProviderError(f"{model}: {exc.code} {str(exc)[:300]}") from exc
            text = response.text or ""
            try:
                drafts = json.loads(text)["narratives"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ProviderError(f"{model}: response isn't the expected JSON: {text[:200]!r}") from exc
            usage = response.usage_metadata
            return Call(
                drafts,
                model,
                getattr(usage, "prompt_token_count", 0) or 0,
                getattr(usage, "candidates_token_count", 0) or 0,
                attempts,
                waited,
                notes,
            )


def _retry_delay(detail: str) -> float | None:
    match = re.search(r'retryDelay"?\s*:\s*"?(\d+(?:\.\d+)?)s', detail)
    return float(match.group(1)) + 1 if match else None


class MockProvider:
    """Deterministic narratives from the facts alone: no key, no network. Used when GEMINI_API_KEY
    is unset (`provider: auto`) and in CI, so the whole pipeline and its validation always run."""

    name = "mock"
    model = "mock-template-v1"

    def generate(self, days: list[StationDay], instructions: str) -> Call:
        return Call([self._draft(d) for d in days], self.model)

    @staticmethod
    def _draft(day: StationDay) -> dict:
        facts = {f["element"]: f for f in day.facts}
        sentences, cited = [], []

        def usable(code):
            fact = facts.get(code)
            return fact if fact and fact["status"] in ("valid", "trace") and fact["value"] is not None else None

        high, low = usable("TMAX"), usable("TMIN")
        if high and low:
            sentences.append(f"{day.city} reached a high of {high['value']:g} °C and a low of {low['value']:g} °C.")
            cited += [{"element": "TMAX", "value": high["value"]}, {"element": "TMIN", "value": low["value"]}]
        else:
            sentences.append(f"Temperature readings for {day.city} were not available.")
        rain, snow = facts.get("PRCP"), usable("SNOW")
        if rain and rain["status"] == "trace":
            sentences.append("There was a trace of precipitation.")
        elif usable("PRCP") and rain["value"] > 0:
            sentences.append(f"{rain['value']:g} mm of precipitation fell.")
            cited.append({"element": "PRCP", "value": rain["value"]})
        elif rain and rain["status"] == "valid":
            sentences.append("It stayed dry.")
        else:
            sentences.append("The precipitation reading was not available.")
        if snow and snow["value"] > 0:
            sentences[-1] = sentences[-1].rstrip(".") + f", with {snow['value']:g} cm of snow."
            cited.append({"element": "SNOW", "value": snow["value"]})
        gust = usable("WSFG")
        if gust:
            sentences.append(f"Gusts peaked at {round(gust['value']):g} km/h.")
            cited.append({"element": "WSFG", "value": gust["value"]})
        return {
            "station_id": day.station_id,
            "date": day.obs_date,
            "narrative": " ".join(sentences[:3]),
            "cited": cited,
        }
