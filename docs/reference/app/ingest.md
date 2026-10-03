# Ingest stage reference (`wx ingest`)

Code: `app/wx/ingest/`. `pipeline.py` runs the steps; `noaa/` holds NOAA's file formats (`formats.py`),
downloads (`fetch.py`), loading (`load.py`) and station resolution (`resolve.py`). Tests:
`app/tests/`. Writes the `raw` and `config` schemas; dbt reads them next
([models and tests](../dbt/models-and-tests.md)). Why it works this way:
[incremental loading and idempotency](../../explanation/incremental-and-idempotency.md),
[station selection](../../explanation/station-selection.md).

## Steps, in order

| Step | Code | What happens | Checked | Recorded in |
|---|---|---|---|---|
| 1. Readme | `noaa/fetch.py`, `pipeline._check_layouts` | Downloads `readme.txt` first; compares its column-layout tables with the layouts in `noaa/formats.py`. | A changed layout stops the run (`LayoutChanged`) | `ops.downloads`, `ops.checks` (`readme_layout_matches`) |
| 2. Reference files | `noaa/load.py`: `load_fixed_width`, `load_text`, `load_element_catalog` | Downloads stations, inventory, countries, states and status. Skips a file whose SHA-256 matches the last download; a changed file replaces its table. Parses the readme's element catalog (unit, scale) into `raw.element_catalog`. | Retries, gzip integrity, fingerprint | `ops.downloads`, `ops.loads`, `raw.*` |
| 3. Stations | `noaa/resolve.py`: `resolve` | Resolves each configured city to a station: its airport by name, then the airport's own station or the nearest within `max_distance_km` that reports `required_elements` across the window. | No match, or two cities on one station, stops the run (`ResolutionError`) | `ops.station_resolution` |
| 4. Observations | `noaa/fetch.py`, `noaa/load.py`: `load_observations` | Downloads each selected station's `by_station/<id>.csv.gz`; skips it if unchanged. A changed file is read in full and merged by row hash: inserts, updates and deletes only. | Other-station rows, duplicates and unparseable lines (kept in `raw.rejected_rows`); a file that would remove more than `max_deleted_pct` of the station's rows is refused (`deletes_within_limit`), and the station keeps its last good load | `raw.observations`, `raw.observation_changes`, `raw.rejected_rows`, `ops.loads`, `ops.checks` |
| 5. Run scope | `pipeline._publish_config` | Writes the selected stations, window, element rules and quality thresholds for dbt. | | `config.*` |

- **Run record:** one row in `ops.runs` per run (start, finish, status, error, JSON summary). A failed
  step marks the run `failed`; later steps don't run.
- **Transactions:** steps 2, 4 (per file) and 5 each run in one transaction (`ops.atomic`).
- **Options:** `wx ingest --force` reloads every file even if unchanged, and accepts a station file
  the deletion limit refused.
- **Skipping:** a station file is skipped when its SHA-256 matches the last file *loaded*, not the last
  downloaded, so a refused file is tried and reported again on every run.

## Errors

| Error | Cause | Fix |
|---|---|---|
| `LayoutChanged` | NOAA changed a file layout documented in the readme | Check the change; update `noaa/formats.py` (`FIXED_WIDTH`) |
| `ResolutionError` | No airport-named station; none with full coverage within `max_distance_km`; or two cities on one station | Set `name_prefix` or pin `station_id` ([add a city](../../how-to/add-a-city.md)) |
| `WarehouseLocked` | The warehouse is open in another process (`wx --explore`, a DuckDB CLI, Airflow) | Close it and retry |
| HTTP error | NOAA unreachable after retries | Retry later; nothing is committed for that file |

## Tests

36 of the 68 tests in `app/tests/` cover this stage. They use in-memory warehouses and hand-written
NOAA rows, so they need no network.

| File | Tests | What they prove |
|---|---|---|
| `test_formats.py` | 3 | The fixed-width layouts in code match NOAA's readme; the element catalog reads units and scales ("tenths of" → 0.1); wrapped descriptions are joined |
| `test_config.py` | 4 | The repository's config is valid; an unquoted `ON` (YAML's `true`) is rejected; city prefixes match NOAA's names (Montréal → MONTREAL); window bounds |
| `test_resolve.py` | 12 | The international airport wins; full coverage outranks partial; a pinned station must still qualify; the brief's old `CA0` IDs aren't in the metadata; a new city is config only; full ties go to the lowest ID; the climate station beside an airport without precipitation is used; US cities need only a country; "INTERCONTINENTAL" and names cut off at 30 characters count as international; a city without an airport-named station fails loudly; an unknown city fails loudly |
| `test_load.py` | 8 | The first load inserts everything; revisions, backfills and removals are detected and logged; an unchanged reload changes nothing; other-station and duplicate rows fail their checks; unloadable rows are kept with the reason; one station's load doesn't touch another's; rejected lines don't carry over to the next file; an interrupted merge changes nothing |
| `test_ops.py` | 4 | The warehouse folder is created on a fresh clone; a failed run is recorded; a reader and a writer coexist in one process; a warehouse open elsewhere gives a clear message |
| `test_reset.py` | 4 | `wx reset` removes the warehouse but keeps downloads; `--all` removes only what the pipeline created; `--narratives` drops only the narrative cache; nothing to reset is reported |

CI also runs the whole pipeline against live NOAA data from a clean checkout.
