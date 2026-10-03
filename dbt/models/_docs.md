{#- Column definitions shared across sources and models: written once, referenced with doc('name').
    persist_docs writes them to the warehouse as comments (marts here, sources in an on-run-end hook),
    so they show in `describe` and the DuckDB UI. docs/metadata_columns.md has the overview. -#}

{% docs run_id %}
The `wx` run that wrote the row: its UTC start time plus six random hex characters
(`20261002T211033-bfaf4e`). Joins to `ops.runs`.
{% enddocs %}

{% docs raw_run_id %}
The ingest run that last inserted or changed this row in `raw.observations` (its `_run_id`).
Joins to `ops.runs`.
{% enddocs %}

{% docs raw_changed_at %}
When NOAA last changed this value or its flags, as detected by ingest (`_last_changed_at` in raw).
The incremental fact uses it as its watermark. UTC.
{% enddocs %}

{% docs source_file %}
The NOAA file the row was read from, such as `CAN06158731.csv.gz` or `ghcnd-stations.txt`.
{% enddocs %}

{% docs sha256 %}
SHA-256 of the file when it was loaded. NOAA's Last-Modified header is unreliable, so this
fingerprint decides whether a file changed; unchanged files are skipped.
{% enddocs %}

{% docs loaded_at %}
When this snapshot was loaded. Reference files are replaced whole when their fingerprint changes. UTC.
{% enddocs %}

{% docs row_hash %}
md5 of `value|mflag|qflag|sflag|obs_time`. Comparing it between loads finds NOAA's revisions without
comparing every column.
{% enddocs %}

{% docs first_loaded_at %}
When this station, date and element first appeared. Never changes, even when NOAA revises the value. UTC.
{% enddocs %}

{% docs last_changed_at %}
When NOAA last changed the value or its flags. UTC.
{% enddocs %}

{% docs mflag %}
NOAA measurement flag (readme section III): how the value was measured. `T` trace (stored as 0,
status `trace`), `H` highest or lowest hourly temperature, `D` total of four six-hour readings,
`B` two 12-hour totals; blank for none.
{% enddocs %}

{% docs qflag %}
NOAA quality flag (readme section III). Blank means the value passed NOAA's checks; any code is a
failed check (`I` internal consistency, `O` climatological outlier, `G` gap, `M` megaconsistency, …)
and makes the value `qc_failed`.
{% enddocs %}

{% docs sflag %}
NOAA source flag (readme section III): where NOAA got the value. `C` Environment Canada, `S` Global
Summary of the Day, `W` US WBAN/ASOS, …
{% enddocs %}

{% docs obs_time %}
Time of observation (HHMM) where the source provides one. Never set for the Canadian stations.
{% enddocs %}

{% docs raw_value %}
The integer as NOAA publishes it, before scaling (tenths of °C, tenths of mm, …). Kept so a scaled
value can always be checked against the source. Null when the text isn't an integer.
{% enddocs %}

{% docs value %}
The value in the element's unit (`raw_value × scale`), at fixed precision (decimal(12,1)).
{% enddocs %}

{% docs quality_status %}
What the value is fit for. `valid` passed NOAA's checks and our bounds; `trace` a measurable amount
too small to record (value 0); `qc_failed` NOAA's quality flag is set; `out_of_bounds` outside the
element's physical bounds in config; `unparseable` the date or value didn't parse;
`removed_at_source` NOAA deleted the row (fct_observations only). Only `valid` and `trace` are usable.
{% enddocs %}

{% docs status %}
The cell's status. Observed values carry their `quality_status`; days with no row at all are
`missing` (the station reports this element that year but not this day, or a persistent element is
evidently present: snow on the ground on both sides, or new snow that day), `not_reported` (absent,
and config says absence means nothing to report: gusts below ~31 km/h, zero snow depth; value 0) or
`not_expected` (the station doesn't report this element that year).
{% enddocs %}

{% docs is_usable %}
True when `quality_status` is `valid` or `trace`. Everything downstream uses only these values.
{% enddocs %}

{% docs is_trace %}
A trace amount (mflag `T`): stored as 0, described as "a trace", never as "none".
{% enddocs %}

{% docs is_expected %}
The inventory says this station reports this element in this year. Separates `missing` from
`not_expected`.
{% enddocs %}

{% docs is_deleted %}
Tombstone: NOAA removed this row. It stays, with status `removed_at_source`, so the removal shows
downstream instead of the row silently disappearing.
{% enddocs %}

{% docs dbt_loaded_at %}
When the incremental model last wrote this row. Rows a build doesn't touch keep their old time. UTC.
{% enddocs %}

{% docs policy_hash %}
md5 of the element's processing rules: scale, absent_means_zero, lower and upper bound. When a rule
changes in config/pipeline.yml the hash changes, and the next build rewrites only that element's rows.
{% enddocs %}

{% docs input_hash %}
md5 of the fact sheet, the exact JSON the narrative model sees. A narrative is regenerated only when
this changes (a NOAA revision, a rule change), never just because the pipeline ran again.
{% enddocs %}

{% docs facts %}
The station-day as the narrative model sees it: one entry per in-scope element with label, value in
display units, unit and status (plus the compass point for wind direction). Built only from marts.
{% enddocs %}

{% docs is_core %}
One of NOAA's five core elements: PRCP, SNOW, SNWD, TMAX, TMIN.
{% enddocs %}

{% docs scale %}
Multiplier from NOAA's integer to the unit, parsed from the readme's element description
("tenths of" → 0.1).
{% enddocs %}

{% docs is_exact_code %}
False for readme entries that describe a family of codes (`SN*#`, `WT**`), which can't match an
observation directly.
{% enddocs %}

{% docs absent_means_zero %}
From config: an absent day means "nothing to report" (status `not_reported`, value 0), not missing
data. Environment Canada omits gusts below ~31 km/h and zero snow depth.
{% enddocs %}

{% docs persistent %}
From config: a quantity that carries over from day to day (snow on the ground). An absent day is
`missing`, not zero, between two non-zero readings or when `fed_by` (new snowfall) is non-zero that day.
{% enddocs %}

{% docs bounds %}
From config: physically plausible range in the element's unit. Values outside are `out_of_bounds`.
{% enddocs %}

{% docs display_unit %}
From config: the unit narratives and the report use (km/h for gusts, cm for snow), with
`display_factor` converting from the stored unit (m/s × 3.6 = km/h; mm × 0.1 = cm). Fact tables and the
daily mart keep NOAA's units. docs/source_conventions.md gives each element's unit chain and the reason for it.
{% enddocs %}

{% docs network_code %}
Third character of the station ID (readme section IV). `N` national meteorological service
(Environment Canada since v3.35), `1` CoCoRaHS volunteers, `W` US WBAN, `C` US Cooperative,
`0` unspecified (the old Canadian IDs).
{% enddocs %}

{% docs wmo_id %}
World Meteorological Organization station number, when the station has one. A ranking rule in
station selection.
{% enddocs %}

{% docs first_last_year %}
First and last year the station reported this element, per ghcnd-inventory.txt. Used by station
selection (coverage of the window) and by `is_expected`.
{% enddocs %}

{% docs changed_at %}
When ingest detected the change. UTC.
{% enddocs %}

{% docs change %}
`insert` (new row), `update` (value or flags differ) or `delete` (row no longer in NOAA's file).
{% enddocs %}
