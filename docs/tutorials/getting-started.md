# Getting started

In about fifteen minutes you'll run the whole pipeline, read its results, query the warehouse, and
see a sixth city added by configuration alone. You need [uv](https://docs.astral.sh/uv/getting-started/installation/)
and an internet connection; no API key, database or Docker.

## 1. Run the pipeline

```powershell
git clone https://github.com/apmalong/weather-data-platform.git
cd weather-data-platform
uv sync
uv run wx run
```

`uv sync` installs Python 3.12 and the locked dependencies. `wx run` then runs the three stages and
writes the report. Watch the log scroll:

- `Toronto -> CAN06158731 (TORONTO INTL A)`: each city resolved to a station from NOAA's metadata.
- `Done. PASS=94`: dbt built 19 models and ran 71 tests.
- `narrate ...: 70 generated (70 passed validation)`: without a key, an offline mock writes the
  narratives, and every one is checked against the data.

It takes about a minute.

## 2. Read the report

Open `data/report.html` in a browser.

- **Overview:** the health status and the five stations. Each one won against dozens of candidates;
  the table says why the others lost.
- **Weather:** pick Vancouver and **1 year**. The snowfall chart shows only thin grey marks: the
  2025–26 winter had no measurable snow at the airport, only traces. Switch to **Window** and the
  February 2025 snowfall appears.
- **Data quality:** completeness per city and element. Gusts and snow depth count as complete on days
  with nothing to report; that's Environment Canada's reporting, not missing data.
- **Narratives:** open **Facts and checks** on any narrative to see what it was written from and
  every validation check it passed.

## 3. Ask the pipeline how it's doing

```powershell
uv run wx health
```

One status (OK, WARN or ERROR), the reasons, and a section per stage.

## 4. Query the warehouse

```powershell
uv run wx --explore
```

In the browser tab that opens, run:

```sql
select issue_type, city, obs_date, element, value, reason
from audit.data_issues order by obs_date desc;
```

These are values NOAA's own quality checks failed. In the window they're all Calgary snow: snow on
the ground rose on a day with no snowfall recorded. The pipeline kept them, marked them and didn't
use them. Press Ctrl+C in the terminal to stop the UI.

## 5. Add a sixth city

Try it on copies, so your setup is untouched:

```powershell
copy config\pipeline.yml $env:TEMP\pipeline-try.yml
copy data\warehouse.duckdb $env:TEMP\wx-try.duckdb
```

Open `$env:TEMP\pipeline-try.yml` and add a line under `cities`:

```yaml
    - {city: Edmonton, province: 'AB'}
```

Then:

```powershell
$env:WX_CONFIG = "$env:TEMP\pipeline-try.yml"; $env:WX_WAREHOUSE = "$env:TEMP\wx-try.duckdb"
uv run wx ingest
uv run wx transform
Remove-Item Env:WX_CONFIG, Env:WX_WAREHOUSE
```

The log shows `Edmonton -> CAN03012216 (EDMONTON INTL A)`, and Edmonton is in every mart, with no
SQL or Python changed.

## 6. Optional: real narratives

Get a free key at https://aistudio.google.com/apikey (no billing), then:

```powershell
copy .env.example .env      # add the key after GEMINI_API_KEY=
uv run wx narrate
uv run wx report
```

About 7 requests; the narratives tab now shows Gemini's text.

## Next

- Tasks: [how-to guides](../README.md#how-to-guides), such as [add a city](../how-to/add-a-city.md)
  or [investigate data issues](../how-to/investigate-data-issues.md).
- Why it works this way: [explanation](../README.md#explanation).
