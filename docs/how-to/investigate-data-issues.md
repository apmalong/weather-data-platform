# How to investigate data issues

Open the warehouse read-only (stop it with Ctrl+C before running other `wx` commands):

```bash
uv run wx --explore
```

**1. Start with everything that's wrong, in one query.**

```sql
select issue_type, severity, city, obs_date, element, value, reason
from audit.data_issues
order by obs_date desc;
```

| `issue_type` | Means | Look in |
|---|---|---|
| `quarantined` | A value NOAA flagged, outside bounds, inconsistent (TMAX below TMIN) or unparseable; kept but not used | `marts.fct_observations` |
| `rejected_row` | A line that couldn't be loaded | `raw.rejected_rows` |
| `revised_by_noaa` | A value NOAA changed or removed after publishing | `raw.observation_changes` |
| `test_failure` | Output that breaks a dbt test: a pipeline bug | `audit.all_failures`, then `audit.<test name>` |

**2. For a failing test, see its rows.**

```sql
select test_name, tested, severity, failing_row from audit.all_failures;
```

**3. For gaps (missing days), use data quality.** Expected gaps aren't issues; they're counted here:

```sql
select city, element, completeness, missing_days, freshness, last_usable_date
from marts.mart_data_quality order by completeness;
```

**4. For a pipeline run that failed**, see the run log and the overall status:

```sql
select command, status, started_at, error from ops.runs order by started_at desc limit 10;
```

```bash
uv run wx health
```

**5. To check a value against the original source**, compare with Environment Canada's record for the
same station (climate ID = the NOAA ID without `CAN0`):

=== "macOS"

    ```bash
    curl "https://api.weather.gc.ca/collections/climate-daily/items?CLIMATE_IDENTIFIER=1108395&datetime=2025-02-01/2025-02-09&f=json"
    ```

=== "Linux"

    ```bash
    curl "https://api.weather.gc.ca/collections/climate-daily/items?CLIMATE_IDENTIFIER=1108395&datetime=2025-02-01/2025-02-09&f=json"
    ```

=== "Windows"

    ```powershell
    curl.exe "https://api.weather.gc.ca/collections/climate-daily/items?CLIMATE_IDENTIFIER=1108395&datetime=2025-02-01/2025-02-09&f=json"   # curl.exe: in Windows PowerShell 5.1, plain curl is a different command
    ```

What each status and column means: [metadata columns](../reference/warehouse/metadata-columns.md).
