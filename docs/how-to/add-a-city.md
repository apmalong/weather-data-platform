# How to add a city

Adding a city is configuration only: no SQL or Python changes.

1. Add it under `stations.cities` in `config/pipeline.yml`. Quote the province:

   ```yaml
   cities:
     - {city: Edmonton, province: 'AB'}
   ```

   For a US city, add `country: US` and use the state code: `{city: Chicago, province: 'IL', country: US}`.

2. Run the pipeline:

   ```powershell
   uv run wx run
   ```

3. Check which station it chose, and why:

   ```sql
   select station_name, selected, reason from ops.station_resolution
   where city = 'Edmonton' and run_id = (select max(run_id) from ops.station_resolution)
   order by selected desc, rank;
   ```

   The city now appears in `dim_station`, the daily mart, data quality, the narratives and the report.

## If ingest stops with `ResolutionError`

The message says why. Fix it in the city's entry:

| Cause | Fix | Example |
|---|---|---|
| The airport station isn't named after the city | `name_prefix` | New York: `name_prefix: JFK`; Las Vegas: `name_prefix: McCarran` |
| No station has an airport-style name | `station_id` (pin) | Boston: `station_id: USW00014739` (named just `BOSTON`); Kitchener: `station_id: CAN06144239` |
| The city's airport is another city's | Not addable: two cities can't share a station | Mississauga (Pearson is Toronto's) |

A pinned station must exist in NOAA's metadata and report TMAX, TMIN and PRCP across the window.

## Try it without changing your setup

Use a copy of the config and the warehouse, so the real ones are untouched:

```powershell
copy config\pipeline.yml $env:TEMP\pipeline-try.yml        # then add the city to the copy
copy data\warehouse.duckdb $env:TEMP\wx-try.duckdb
$env:WX_CONFIG = "$env:TEMP\pipeline-try.yml"; $env:WX_WAREHOUSE = "$env:TEMP\wx-try.duckdb"
uv run wx ingest; uv run wx transform
Remove-Item Env:WX_CONFIG, Env:WX_WAREHOUSE
```

Before adding US cities, read the README's "With more time": some element rules describe Environment
Canada's reporting and would need their own US equivalents.
