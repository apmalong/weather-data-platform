# Pipeline health

**Status: OK**

## Latest run of each stage

| stage | status | started (UTC) | seconds | error |
|---|---|---|---|---|
| narrate | success | 2026-10-02 22:45:33 | 0.0 |  |
| ingest | success | 2026-10-03 14:09:08 | 15.0 |  |
| transform | success | 2026-10-03 18:32:26 | 14.0 |  |

## Ingest (20261003T140908-cdecf5)

11 files downloaded, 0 changed since the last run, 0 failed, 48.8 MB.

| city | station | candidates considered | why it won |
|---|---|---|---|
| Montreal | CAN07025251 MONTREAL INTL A | 19 | selected: the airport's own station |
| Calgary | CAN03031092 CALGARY INTL A | 39 | selected: the airport's own station |
| Toronto | CAN06158731 TORONTO INTL A | 93 | selected: the airport's own station |
| Ottawa | CAN06106001 OTTAWA INTL A | 25 | selected: the airport's own station |
| Vancouver | CAN01108395 VANCOUVER INTL A | 43 | selected: the airport's own station |

What NOAA changed in the most recent load that changed anything (revisions and removals of past dates count as historical):

| run | city | inserted | updated | deleted | historical |
|---|---|---|---|---|---|
| 20261002T172108-4f3f93 | Calgary | 36166 | 0 | 0 | 0 |
| 20261002T172108-4f3f93 | Montreal | 34594 | 0 | 0 | 0 |
| 20261002T172108-4f3f93 | Ottawa | 37995 | 0 | 0 | 0 |
| 20261002T172108-4f3f93 | Toronto | 33855 | 0 | 0 | 0 |
| 20261002T172108-4f3f93 | Vancouver | 77287 | 0 | 0 | 0 |

## Transform: dbt build (20261003T183226-53cac1)

19 model success, 69 test pass, 2 unit_test pass.

## Data quality over the window

| city | worst completeness | element | missing days | trace days | quarantined | latest | freshness |
|---|---|---|---|---|---|---|---|
| Calgary | 0.967 | Average daily temperature | 99 | 276 | 6 | 2026-09-29 | fresh |
| Montreal | 0.9835 | Snow depth | 41 | 238 | 0 | 2026-09-29 | fresh |
| Ottawa | 0.9876 | Snow depth | 23 | 219 | 0 | 2026-09-29 | fresh |
| Toronto | 0.9601 | Snow depth | 30 | 235 | 0 | 2026-09-29 | fresh |
| Vancouver | 0.945 | Average daily temperature | 134 | 62 | 0 | 2026-09-29 | fresh |

## Narratives (20261002T224533-cb8e74)

Latest run: 0 requests for 0 station-days on None, 0+0 tokens, None s per request, 0 retries, 0 failed requests.
Current narratives: 70 station-days from 2026-09-16 to 2026-09-29 (gemini gemini-3.5-flash-lite), 70 passed validation.

Evaluation on evals/cases.yml, latest run per prompt version:

| prompt | model | passed | style issues | avg chars | when (UTC) |
|---|---|---|---|---|---|
| narrative_v1@65ba9f09 | gemini-3.5-flash-lite | 11/11 | 18 | 156.1 | 2026-10-02 17:50 |
| narrative_v2@bb835346 | gemini-3.5-flash-lite | 11/11 | 0 | 125.5 | 2026-10-02 17:56 |
| narrative_v3@fb4b5556 | gemini-3.5-flash-lite | 11/11 | 0 | 121.5 | 2026-10-02 18:32 |
