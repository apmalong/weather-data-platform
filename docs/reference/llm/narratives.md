# Narrative stage reference: prompts, validation, evaluation

Code: `app/wx/narrate/` (`pipeline.py`, `providers.py`, `validate.py`, `evaluate.py`). What it reads:
`llm/prompts/` and `llm/evals/cases.yml`. Input: `marts.mart_narrative_input`. Output: the
`narratives` schema. Settings: [`narratives` in the configuration](../configuration.md#narratives).
Why it's built this way: [narratives](../../explanation/narratives.md).

## Prompts (`llm/prompts/`)

| File | Status |
|---|---|
| `narrative_v1.md` | First version; kept for comparison |
| `narrative_v2.md` | Fact rules separated from style rules; kept for comparison |
| `narrative_v3.md` | **Current** (`narratives.prompt`): compass from the facts, no unsupported weather types, high/low attribution, "dry" only on a valid 0, intensity thresholds |

`prompt_version` = file name + `@` + first 8 hex characters of the file's SHA-256 (e.g.
`narrative_v3@fb4b5556`). Editing a prompt changes its version even without renaming it.

## Input and output

| | Contents |
|---|---|
| Input fact sheet | Per station-day: one entry per element with `element`, `label`, `value` (display units, only when usable), `unit`, `status`, and `compass` for wind direction |
| Request | Up to `batch_size` station-days; structured JSON output required (`response_json_schema`) |
| Response, per station-day | `station_id`, `date`, `narrative`, `cited` (each figure used: `element`, `value`) |
| `narratives.daily` | Every narrative written, including failed first attempts (`attempt` 1 or 2) |
| `narratives.validation` | Every validation result, with each check's outcome |
| `narratives.latest` | The current narrative per station-day, with `passed`, `failed_checks`, `warnings` |

**Cache:** a narrative is reused when `(station_id, obs_date, input_hash, model, prompt_version)` all
match. `input_hash` = md5 of the fact sheet.

**Skipped without a model call:** a day with no usable temperature or precipitation gets a fixed
sentence (provider `rule`); stations whose data is stale aren't narrated (`skipped_stale`).

## Providers

| Provider | Behaviour |
|---|---|
| Gemini (`GEMINI_API_KEY` set) | Models in `narratives.models` order. 404 (retired for the key) → next model. 429 → waits the delay the API returns. Daily quota → next model, then stops cleanly; the rest is deferred. Up to 4 attempts per request. Paced at `requests_per_minute`, capped at `max_requests_per_run` |
| Mock (`mock-template-v1`, no key) | Builds sentences from the facts with the same interface; used by CI and tests |

## Validation (`validate.py`)

Every narrative, before it's stored. An error fails it; a warning is recorded.

| Check | Severity | Fails when |
|---|---|---|
| `cited_values_match` | error | A cited figure doesn't match the fact it names |
| `cited_only_usable` | error | It cites a value whose status makes it unusable |
| `numbers_grounded` | error | A number in the text matches no usable fact (rounding allowed) |
| `high_low_attribution` | error | "A high of N" isn't TMAX, or "a low of N" isn't TMIN |
| `compass_matches` | error | It names a direction other than the fact's compass point |
| `no_false_zero` | error | "Dry", "no rain" or "no snow" when the value was a trace, positive or missing |
| `no_false_gaps` | error | It calls a usable reading missing |
| `no_invented_topics` | error | Topics it wasn't given: forecasts, humidity, cloud, hail, sleet, freezing rain… |
| `names_own_city` | error / warn | Error if it names another city; warning if it doesn't name its own |
| `intensity_supported` | warn | An intensity word (config `intensity`) the data doesn't support |
| `mentions_temperatures` | warn | High and low were usable but not both mentioned |
| `acknowledges_gaps` | warn | A missing temperature or precipitation reading isn't mentioned |
| `length` | warn | Not 1–3 sentences, or over 450 characters |

**Repair:** with `repair_attempts: 1`, failures (including ones from earlier runs) go back once in a
batch, each with its previous text and failed checks. The repair is stored as `attempt` 2.

## Evaluation (`wx eval`, `llm/evals/cases.yml`)

11 fixed station-days, chosen because they're hard:

| Case | City, date | Why it's hard |
|---|---|---|
| `missing-temps` | Vancouver, 2026-09-16 | Temperatures missing; must say so, not guess |
| `trace-rain` | Montréal, 2026-09-29 | A trace must not become "no rain" |
| `big-gust` | Ottawa, 2026-08-12 | The strongest gust in the window (107 km/h) |
| `big-snow` | Toronto, 2026-01-25 | 46.2 cm of snowfall |
| `deep-snow` | Ottawa, 2025-02-17 | 92 cm on the ground |
| `qc-failed-snow` | Calgary, 2025-12-19 | Snow values failed NOAA's checks; must not be reported |
| `coldest` | Calgary, 2025-02-15 | −28.5 °C; negative numbers |
| `hottest` | Toronto, 2026-07-14 | 36.8 °C |
| `heavy-rain` | Ottawa, 2026-07-01 | 118.4 mm of rain |
| `calm-dry` | Ottawa, 2026-09-29 | Nothing notable; gusts and snow not reported |
| `summer-snow-trace` | Montréal, 2026-06-28 | A trace of snow in June, reported as published |

Each case runs through the production validation, plus three style checks scored only here:
`units_as_symbols` (°C, not "degrees C"), `no_trailing_zero` (58, not 58.0), `no_template_phrasing`
("a high of", not "maximum temperature of"). Results: `ops.eval_runs`, `ops.eval_results`, and the
report's Evaluation tab.
