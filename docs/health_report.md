# Pipeline health

**Status: OK**

## Latest run of each stage

| stage | status | started (UTC) | seconds | error |
|---|---|---|---|---|
| ingest | success | 2026-10-02 18:16:21 | 13.0 |  |
| transform | success | 2026-10-02 18:28:51 | 5.0 |  |
| narrate | success | 2026-10-02 18:47:07 | 1.0 |  |

## Ingest (20261002T181621-c0f10e)

11 files downloaded, 0 changed since the last run, 0 failed, 48.8 MB.

| city | station | candidates considered | why it won |
|---|---|---|---|
| Vancouver | CAN01108395 VANCOUVER INTL A | 43 | selected |
| Montreal | CAN07025251 MONTREAL INTL A | 16 | selected |
| Calgary | CAN03031092 CALGARY INTL A | 39 | selected |
| Toronto | CAN06158731 TORONTO INTL A | 91 | selected |
| Ottawa | CAN06106001 OTTAWA INTL A | 25 | selected |

What NOAA changed in the most recent load that changed anything (revisions and removals of past dates count as historical):

| run | city | inserted | updated | deleted | historical |
|---|---|---|---|---|---|
| 20261002T172108-4f3f93 | Calgary | 36166 | 0 | 0 | 0 |
| 20261002T172108-4f3f93 | Montreal | 34594 | 0 | 0 | 0 |
| 20261002T172108-4f3f93 | Ottawa | 37995 | 0 | 0 | 0 |
| 20261002T172108-4f3f93 | Toronto | 33855 | 0 | 0 | 0 |
| 20261002T172108-4f3f93 | Vancouver | 77287 | 0 | 0 | 0 |

## Transform: dbt build (20261002T182851-b931f9)

1 model success, 2 test pass.

## Data quality over the window

| city | worst completeness | element | missing days | trace days | quarantined | latest | freshness |
|---|---|---|---|---|---|---|---|
| Calgary | 0.967 | TMIN | 83 | 276 | 6 | 2026-09-29 | fresh |
| Montreal | 0.989 | TAVG | 29 | 238 | 0 | 2026-09-29 | fresh |
| Ottawa | 0.9945 | TAVG | 14 | 219 | 0 | 2026-09-29 | fresh |
| Toronto | 0.9986 | SNOW | 1 | 236 | 0 | 2026-09-29 | fresh |
| Vancouver | 0.9451 | TAVG | 128 | 62 | 0 | 2026-09-29 | fresh |

## Narratives (20261002T184707-fadab2)

Latest run: 1 requests for 1 station-days on gemini-3.5-flash-lite, 1489+119 tokens, 1.1 s per request, 0 retries, 0 failed requests.
Current narratives: 70 station-days from 2026-09-16 to 2026-09-29 (gemini gemini-3.5-flash-lite), 70 passed validation.

Evaluation on evals/cases.yml, latest run per prompt version:

| prompt | model | passed | style issues | avg chars | when (UTC) |
|---|---|---|---|---|---|
| narrative_v1@65ba9f09 | gemini-3.5-flash-lite | 11/11 | 18 | 156.1 | 2026-10-02 17:50 |
| narrative_v2@bb835346 | gemini-3.5-flash-lite | 11/11 | 0 | 125.5 | 2026-10-02 17:56 |
| narrative_v3@fb4b5556 | gemini-3.5-flash-lite | 11/11 | 0 | 121.5 | 2026-10-02 18:32 |
