# How to change element rules

Element rules live under `elements` in `config/pipeline.yml`
([reference](../reference/configuration.md#elements)). After any change, run ingest first, because it
publishes the rules dbt reads:

```powershell
uv run wx ingest
uv run wx transform
```

| To | Edit | What gets reprocessed |
|---|---|---|
| Tighten or loosen what counts as physically possible | `bounds`, e.g. `TMAX: [-60, 45]` | Only that element's rows: the rule change alters its `policy_hash` |
| Treat an absent day as "nothing to report" instead of missing | add the element to `absent_means_zero` | That element's rows, and its completeness |
| Treat an absent day as missing while the quantity is evidently present | `persistent`, e.g. `SNWD: {fed_by: SNOW}` | The day grid (rebuilt every run) |
| Show a different unit to readers | `display`, e.g. `WSFG: {unit: knots, factor: 1.944}` | Narrative input and the report; marts keep NOAA's units |
| Leave an element out entirely | add it to `exclude` | Everything downstream |

Narratives depend on their facts: a change that alters a station-day's facts (a value quarantined, a
display unit) changes its `input_hash`, so its narrative is regenerated on the next `wx narrate`.

Check the effect:

```sql
select element, status, count(*) from marts.fct_station_day_element group by all order by all;
select * from audit.data_issues where element = 'TMAX' order by obs_date desc;
```

Units and their conversions: [NOAA conventions](../reference/noaa/conventions.md).
