import duckdb
from test_narrate_pipeline import cfg  # noqa: F401  (the warehouse fixture)

from wx.narrate import pipeline
from wx.narrate.providers import Call


class Scripted:
    """First pass: a narrative that invents a value. Repair pass: as scripted per call."""

    name = "scripted"
    model = "scripted-v1"

    def __init__(self, repair_text: str):
        self.repair_text, self.requests = repair_text, []

    def generate(self, days, instructions):
        repairing = "failed validation" in instructions
        self.requests.append([d.payload() for d in days])
        drafts = []
        for d in days:
            text = self.repair_text if repairing else "A high of 30 °C and a low of 15 °C, with 2 mm of rain."
            drafts.append({"station_id": d.station_id, "date": d.obs_date, "narrative": text, "cited": []})
        return Call(drafts, self.model)


def test_a_failed_narrative_is_repaired_once(cfg):  # noqa: F811
    provider = Scripted("Toronto saw a high of 21 °C and a low of 15 °C, with 2 mm of rain.")
    result = pipeline.run(cfg, provider=provider, days=1)
    assert (result["generated"], result["repaired"], result["passed"], result["failed_validation"]) == (1, 1, 1, 0)
    assert len(provider.requests) == 2
    repair = provider.requests[1][0]
    assert repair["previous_narrative"].startswith("A high of 30") and any("30" in p for p in repair["problems"])
    conn = duckdb.connect(str(cfg.warehouse), read_only=True)
    assert conn.execute("select attempt, passed from narratives.latest").fetchone() == (2, True)
    assert conn.execute("select count(*) from narratives.daily").fetchone()[0] == 2  # the failed first try is kept


def test_a_narrative_still_failing_stays_flagged(cfg):  # noqa: F811
    result = pipeline.run(cfg, provider=Scripted("Still a high of 30 °C."), days=1)
    assert (result["repaired"], result["failed_validation"]) == (0, 1)
    conn = duckdb.connect(str(cfg.warehouse), read_only=True)
    assert conn.execute("select attempt, passed from narratives.latest").fetchone() == (2, False)


def test_repair_can_be_turned_off(cfg):  # noqa: F811
    cfg.narratives.repair_attempts = 0
    provider = Scripted("unused")
    result = pipeline.run(cfg, provider=provider, days=1)
    assert len(provider.requests) == 1 and result["failed_validation"] == 1


def test_failures_from_an_earlier_run_are_repaired_by_the_next(cfg):  # noqa: F811
    cfg.narratives.repair_attempts = 0
    pipeline.run(cfg, provider=Scripted("unused"), days=1)  # fails, no repair allowed
    cfg.narratives.repair_attempts = 1
    fixed = Scripted("Toronto saw a high of 21 °C and a low of 15 °C, with 2 mm of rain.")
    result = pipeline.run(cfg, provider=fixed, days=1)
    assert (result["carried_over"], result["repaired"], len(fixed.requests)) == (1, 1, 1)  # only the repair request
