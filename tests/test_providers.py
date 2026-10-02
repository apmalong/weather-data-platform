import json
from types import SimpleNamespace

import pytest
from google.genai import errors

from wx.narrate.providers import GeminiProvider, MockProvider, ProviderError, QuotaExhausted, StationDay

DAY = StationDay("CAN06158731", "Toronto", "ON", "TORONTO INTL A", "2026-09-28", [
    {"element": "TMAX", "label": "Maximum temperature", "value": 21.4, "unit": "degrees C", "status": "valid"},
    {"element": "TMIN", "label": "Minimum temperature", "value": 15.3, "unit": "degrees C", "status": "valid"},
    {"element": "PRCP", "label": "Precipitation", "value": 0.0, "unit": "mm", "status": "trace"},
], "hash")


def ok_response(drafts):
    return SimpleNamespace(text=json.dumps({"narratives": drafts}),
                           usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=40))


def api_error(code, status, details=()):
    body = {"code": code, "status": status, "message": status, "details": list(details)}
    return errors.APIError(code, {"error": body})


class FakeClient:
    """Plays back a script of responses or errors, recording which model each call used."""

    def __init__(self, script):
        self.script, self.models_called = list(script), []
        self.models = self

    def generate_content(self, model, contents, config):
        self.models_called.append(model)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def provider(script, models=("m1", "m2")):
    client = FakeClient(script)
    sleeps = []
    return GeminiProvider("key", list(models), 0.3, client=client, sleep=sleeps.append), client, sleeps


DRAFT = {"station_id": DAY.station_id, "date": DAY.obs_date, "narrative": "x", "cited": []}


def test_retired_model_falls_through_to_the_next():
    gemini, client, _ = provider([api_error(404, "NOT_FOUND"), ok_response([DRAFT])])
    call = gemini.generate([DAY], "instructions")
    assert client.models_called == ["m1", "m2"] and call.model == "m2" and call.drafts == [DRAFT]
    assert "not available" in call.notes[0]


def test_rate_limit_waits_the_delay_the_api_asks_for():
    retry = {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}
    gemini, client, sleeps = provider([api_error(429, "RESOURCE_EXHAUSTED", [retry]), ok_response([DRAFT])])
    call = gemini.generate([DAY], "instructions")
    assert sleeps == [8.0] and call.attempts == 2 and client.models_called == ["m1", "m1"]


def test_daily_quota_moves_on_then_stops_cleanly():
    per_day = {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
               "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}
    gemini, client, _ = provider([api_error(429, "RESOURCE_EXHAUSTED", [per_day])] * 2)
    with pytest.raises(QuotaExhausted):
        gemini.generate([DAY], "instructions")
    assert client.models_called == ["m1", "m2"]


def test_bad_request_is_not_retried():
    gemini, client, _ = provider([api_error(400, "INVALID_ARGUMENT")])
    with pytest.raises(ProviderError, match="400"):
        gemini.generate([DAY], "instructions")
    assert client.models_called == ["m1"]


def test_malformed_json_is_an_error():
    gemini, _, _ = provider([SimpleNamespace(text="not json", usage_metadata=None)])
    with pytest.raises(ProviderError, match="expected JSON"):
        gemini.generate([DAY], "instructions")


def test_mock_follows_the_status_rules():
    draft = MockProvider().generate([DAY], "").drafts[0]
    assert "trace of precipitation" in draft["narrative"]
    assert {c["element"] for c in draft["cited"]} == {"TMAX", "TMIN"}
