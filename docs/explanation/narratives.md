# Narratives: how they're kept honest

## The reader can't check the source

A narrative is for someone who wants the day's weather in a sentence, not a table. They won't compare
it with NOAA's data, so a wrong number or an invented "heavy snow" quietly breaks their trust. Every
design choice here is about making the text checkable.

## Give the model facts, not data

The model sees one fact sheet per station-day, built only from the marts: each element's label, value
in display units, unit and status. Status matters as much as value: `trace` must read as "a trace of",
`not_reported` gusts as nothing notable, `qc_failed` as unavailable. Anything that needs arithmetic is
done in SQL first. A day with nothing usable gets a fixed sentence instead of a model call, so the
model is never asked to describe nothing.

## Make the model show its work, then check it

The response is structured JSON: the narrative plus every figure it used and which element it came
from. Validation compares both the citations and the free text with the facts before anything is
stored: numbers must match a usable fact, "a high of" must be TMAX, wind directions must be the given
compass point, "dry" needs a valid 0, and nothing may be invented (forecasts, humidity, hail, other
cities). Rules rather than a second model: they're deterministic, free, and every failure says exactly
what's wrong.

## What validation found

Re-scoring every stored narrative found one real, recurring error: wrong wind directions in 19 of 103
narratives (18%) written with prompt v2, such as 290° written as "NW" (it's W). The model was being
asked to convert degrees to compass points and got the arithmetic wrong. The fix took the conversion
away from the model: the compass point is computed in SQL and given as a fact, and a check enforces it.

## Prompts are versioned and evaluated

`wx eval` runs a prompt on 11 hard cases from the real data and stores the results:

| Prompt | Factual checks | Style issues |
|---|---|---|
| v1 | Called present precipitation "missing" once | 18 ("degrees C", "58.0 km/h", template phrasing) |
| v2 | Wrong compass points in 6 of 33 evaluated narratives | 0 |
| v3 (current) | 11/11 | 0 |

Evaluation also improved validation: the check against calling present data "missing" exists because
v1 did it.

## One repair, then flag

A narrative that fails validation goes back to the model once, in a batch with the other failures,
with its previous text and the exact checks it failed. If it passes it becomes current; if not, it
stays flagged. The first attempt is kept as history. In production, one of 70 narratives cited 0.0 for
a missing temperature; one repair request fixed it.

## Built for a free tier

One narrative per city per day, batched 10 to a request and cached by input, so cost grows with cities,
not readers, and an unchanged day costs nothing. Pinned model versions, never `-latest`. A retired
model falls through to the next; a daily quota stops the run cleanly and the next run resumes. Without
a key, a mock with the same interface runs, so every stage works for anyone.

What isn't checked: tone. Validation checks facts, not prose; style is measured by evaluation only.

Related: [narrative stage reference](../reference/llm/narratives.md),
[change the prompt](../how-to/change-the-prompt.md).
