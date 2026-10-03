# Ingestion: `wx ingest`

`wx ingest` downloads NOAA's files, decides which stations to use, and loads both into the
warehouse's `raw` and `config` schemas. Everything it does is recorded in the `ops` schema. dbt
takes over from there ([dbt_models.md](dbt_models.md)). The code is in `src/wx/ingest.py` and
`src/wx/noaa/`.

## What it does, in order

| Step | Code | What happens | Checked | Recorded in |
|---|---|---|---|---|
| 1. Readme | `fetch.download`, `ingest._check_layouts` | Downloads `readme.txt` first, because the other files' column layouts come from it. Compares the readme's layout tables with the layouts in code. | A changed layout stops the run (`LayoutChanged`) instead of mis-reading every file | `ops.downloads`, `ops.checks` (`readme_layout_matches`) |
| 2. Reference files | `load.load_fixed_width`, `load.load_text`, `load.load_element_catalog` | Downloads stations, inventory, countries, states and status. A file whose SHA-256 matches the last download is skipped. Changed files replace their table; the readme's element catalog (units and scales) is parsed into `raw.element_catalog`. | Download retries, gzip integrity, fingerprint | `ops.downloads`, `ops.loads`, `raw.*` |
| 3. Stations | `resolve.resolve` | For each configured city: find its airport by name, then the airport's own station or the nearest one within 5 km that reports TMAX, TMIN and PRCP across the window. | No match, or two cities on one station, stops the run (`ResolutionError`) | `ops.station_resolution` (every candidate and why it won or lost) |
| 4. Observations | `fetch.download`, `load.load_observations` | Downloads each selected station's file; skips it if unchanged. A changed file is read in full and merged: each row is compared by hash with what's stored, and only inserts, updates and deletes are applied. | Rows for another station, duplicates and unparseable lines are counted as checks and kept in `raw.rejected_rows` | `raw.observations`, `raw.observation_changes`, `raw.rejected_rows`, `ops.loads`, `ops.checks` |
| 5. Run scope | `ingest._publish_config` | Writes this run's decisions for dbt: selected stations, the window, element rules, quality thresholds. | | `config.*` |

The whole run is one row in `ops.runs` (started, finished, status, error, and a JSON summary).
A failure at any step marks the run `failed` with the error, and nothing after it runs.

**Re-running is safe and cheap.** Unchanged files are skipped by fingerprint, and an unchanged
file produces no changes. `wx ingest --force` reloads every file regardless.

**Why read the whole file:** NOAA publishes each station's entire history in one file, revises past
values, and offers no "changes since" feed. Only a full comparison finds revisions; v3.35 reloaded 17
months of Canadian data at once. Writing only the differences keeps the history of what NOAA changed.

## When it fails

| Error | Cause | What to do |
|---|---|---|
| `LayoutChanged` | NOAA changed a file layout in the readme | Update `formats.FIXED_WIDTH` to match, after checking the change |
| `ResolutionError` | A city has no airport-named station, or none with full coverage within `max_distance_km`, or two cities resolved to one station | Set `name_prefix` or pin `station_id` in config (the message says which) |
| `WarehouseLocked` | The warehouse is open in another process (`wx --explore`, a DuckDB CLI, Airflow) | Close it and retry |
| HTTP errors | NOAA unreachable after retries | Retry later; nothing partial is committed for that file |

## Tests

`uv run pytest` runs 64 tests; 34 cover ingestion, using small in-memory warehouses and
hand-written NOAA rows, so they need no network.

| File | Tests | What they prove |
|---|---|---|
| `test_formats.py` | 3 | The fixed-width layouts in code match NOAA's readme; the element catalog reads units and scales ("tenths of" → 0.1); wrapped descriptions are joined |
| `test_config.py` | 4 | The repository's config is valid; an unquoted `ON` (read by YAML as `true`) is rejected; city prefixes match NOAA's names (Montréal → MONTREAL); window bounds |
| `test_resolve.py` | 12 | The international airport wins; an airport with full coverage outranks one without; a pinned station must still qualify; the brief's old `CA0` IDs aren't in the metadata; a new city is config only; full ties go to the lowest ID; the climate station beside an airport without precipitation is used (Winnipeg); US cities need only a country; "INTERCONTINENTAL" and names cut off at 30 characters count as international; a city without an airport-named station fails loudly; an unknown city fails loudly |
| `test_load.py` | 7 | The first load inserts everything; revisions, backfills and removals are detected and logged; an unchanged reload changes nothing; other-station and duplicate rows fail their checks; rows that can't be loaded are kept with the reason; one station's load doesn't touch another's; rejected lines don't carry over to the next file |
| `test_ops.py` | 4 | The warehouse folder is created on a fresh clone; a failed run is recorded with its error; a reader and a writer coexist in one process; a warehouse open elsewhere gives a clear message |
| `test_reset.py` | 4 | `wx reset` removes the warehouse but keeps downloads; `--all` removes only what the pipeline created; `--narratives` drops only the narrative cache; nothing to reset is reported |

The other 30 tests cover narratives: validation (14), the Gemini and mock providers (6), the
narrative pipeline (6) and the repair attempt (4).

CI runs the same suite on every push, then the whole pipeline against live NOAA data from a clean
checkout, which tests what unit tests can't: that NOAA's real files download, parse and resolve.
