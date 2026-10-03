# Configuration reference: `config/pipeline.yml`

The one file to edit. Validated on load (`app/wx/config.py`), so a typo or wrong type fails before
anything runs. `wx ingest` publishes the parts dbt needs into the `config` schema, so after a change
run `wx ingest` before `wx transform` (or `wx run`).

## `source`

| Key | Meaning |
|---|---|
| `base_url` | NOAA GHCN-Daily root: `https://www.ncei.noaa.gov/pub/data/ghcn/daily` |
| `reference_files` | Name → file: `stations`, `inventory`, `countries`, `states`, `readme`, `status`. All are loaded into `raw` |

## `window`

Set **either** `last_days` **or** `start` (with an optional `end`); both or neither is an error.

| Key | Meaning |
|---|---|
| `last_days` | Days back from today (730 = two years) |
| `start`, `end` | Fixed dates, `YYYY-MM-DD`; `end` defaults to today |

Raw keeps each station's full history; the window applies from dbt onwards.

## `stations`

| Key | Meaning |
|---|---|
| `country` | Default country code for cities (`CA`) |
| `selection.airport_name_pattern` | Regex for airport station names: `' (A\|AP\|INT)$'` |
| `selection.preferred_name_pattern` | Regex for international airports: `'\bINT(L\|''L\|ERCONTINENTAL)?\b'` |
| `selection.required_elements` | Elements a station must report across the window: `[TMAX, TMIN, PRCP]` |
| `selection.max_distance_km` | How far from the airport station a substitute may be: default 5, at most 25 |
| `cities` | List of cities (below), at least one |

Each city:

| Key | Required | Meaning |
|---|---|---|
| `city` | yes | City name; its capitals, accents removed, are the station-name prefix (Montréal → MONTREAL) |
| `province` | yes | Province or US state code. **Quote it**: YAML reads a bare `ON` as `true` |
| `country` | no | Overrides `stations.country` (e.g. `US`) |
| `name_prefix` | no | Station-name prefix when the airport isn't named after the city (e.g. `JFK`) |
| `station_id` | no | Pins a station; it must exist and report the required elements |

## `elements`

| Key | Meaning |
|---|---|
| `exclude` | Elements kept out of scope |
| `absent_means_zero` | Elements whose absent day means "nothing to report" (`not_reported`, value 0), not missing: `[WDFG, WSFG, SNWD]` |
| `persistent` | Elements that carry over between days, each with an optional `fed_by`: `SNWD: {fed_by: SNOW}`. An absent day between two non-zero readings, or with `fed_by` above zero, is `missing` |
| `bounds` | Element → `[lower, upper]` in the stored unit. Values outside are `out_of_bounds` |
| `display` | Element → `{unit, factor}` for readers: `WSFG: {unit: km/h, factor: 3.6}` (unit chains: [NOAA conventions](noaa/conventions.md)) |

Changing `bounds` or `absent_means_zero` changes the element's `policy_hash`, so the next build
reprocesses only that element's rows.

## `narratives`

| Key | Default | Meaning |
|---|---|---|
| `provider` | `auto` | `auto` (Gemini when `GEMINI_API_KEY` is set, else mock), `gemini` or `mock` |
| `models` | required | Gemini models tried in order; a model retired for the key falls through to the next |
| `prompt` | required | Prompt file: `llm/prompts/narrative_v3.md` |
| `days` | 14 | Most recent days with data, per station |
| `batch_size` | 10 | Station-days per request, 1–50 |
| `requests_per_minute` | 5 | Pacing |
| `max_requests_per_run` | 30 | Cap; the rest is deferred to the next run |
| `temperature` | 0.3 | Sampling temperature |
| `repair_attempts` | 1 | 0 or 1: send a failed narrative back once with its failed checks |
| `intensity` | `[]` | Rules `{pattern, element, min, max}`: a word matching `pattern` needs the element (display units) at or above `min` / at or below `max`, else a warning |

## `quality`

| Key | Default | Meaning |
|---|---|---|
| `freshness_warn_days` | 7 | Latest usable reading older than this (vs. the ingest date): `lagging`, a warning |
| `freshness_error_days` | 30 | Older than this, or none: `stale`, an error; the station isn't narrated |
| `volume_change_warn_pct` | 20 | A station file's row count changing by more than this between loads: a warning |
