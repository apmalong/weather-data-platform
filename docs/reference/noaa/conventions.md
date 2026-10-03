# NOAA data conventions reference

How to read the numbers in NOAA's GHCN-Daily files: the units, how they're converted, and the values
whose meaning isn't the number itself. Sources: NOAA's `readme.txt` (shipped with the data and loaded
into `raw.documents`) and what the five stations' files actually contain. Counts are from the full
station histories loaded on 2026-10-03. Why NOAA's data and Environment Canada's differ, and what that
means for this pipeline: [NOAA and Environment Canada](../../explanation/noaa-and-environment-canada.md).

## Units and conversions

NOAA stores every value as an integer. Two steps turn it into what a reader sees:

1. **Scale (from the readme, automatic).** Each element's readme description states its unit, and
   `wx ingest` parses it: "tenths of" means multiply by 0.1. So TMAX `253` is 25.3 °C and PRCP `12`
   is 1.2 mm, as the brief notes. Nothing is hand-coded per element. Values are stored at fixed
   precision (`decimal(12,1)`) so 0.1 scaling never produces float noise.
2. **Display (from config, for readers).** `elements.display` in `config/pipeline.yml` converts a few
   elements from NOAA's unit into the one Canadians read on a forecast. Only
   `mart_narrative_input`, the narratives and the report use display units; the fact tables and the
   daily and quality marts keep NOAA's units.

| Element | NOAA's integer is | Scale | Stored unit | Display | Factor | Why |
|---|---|---|---|---|---|---|
| TMAX, TMIN, TAVG | tenths of °C | 0.1 | °C | °C | 1 | Already the everyday unit. |
| PRCP | tenths of mm | 0.1 | mm | mm | 1 | Rain is reported in mm in Canada. |
| SNOW | mm | 1 | mm | cm | 0.1 | Snowfall is reported in cm (10 mm = 1 cm). |
| SNWD | mm | 1 | mm | cm | 0.1 | Snow on the ground is reported in whole cm: every value since 2019 is a multiple of 10 mm. |
| WSFG | tenths of m/s | 0.1 | m/s | km/h | 3.6 | Wind is reported in km/h in Canada. 1 m/s = 3,600 m per hour = 3.6 km/h. |
| WDFG | degrees | 1 | degrees | degrees, plus a compass point | 1 | The narrative and the report add an 8-point compass point, computed in SQL (see below). |

**Direction to compass point:** `index = round(degrees / 45) mod 8` into
`[N, NE, E, SE, S, SW, W, NW]`, so each point covers a 45° sector centred on it (N is 337.5°–22.5°).
Directions are where the gust came **from**, clockwise from north. It's computed in
`mart_narrative_input`, and with the same formula in the report, because the model got it wrong in 19
of 103 narratives when asked to do it itself.

To change a display unit: [change element rules](../../how-to/change-element-rules.md).

## Values that mean more than their number

| Encoding | Meaning | In these stations' data | How the pipeline reads it |
|---|---|---|---|
| Value 0 with `mflag = T` | **Trace**: precipitation, snowfall or snow on the ground too small to measure (Environment Canada: under about 0.2 mm of rain or 0.2 cm of snow). NOAA stores no amount, only the flag. | 6,485 rows, all years | Status `trace`, value 0, `is_trace`. Narratives say "a trace of", never "no" or "dry". |
| No row for a day | Usually **missing**. Environment Canada leaves out peak gusts below about 30 km/h and snow depth when there's no snow, so for those the absence means "nothing to report". | Every day | `missing`, or `not_reported` (value 0) for `absent_means_zero` elements, except snow depth while snow is evidently on the ground (`persistent`), which stays `missing`. |
| Any `qflag` code | The value **failed one of NOAA's quality checks** (`I` internal consistency, `O` outlier, `G` gap, `M` megaconsistency, …). | 51 rows | `qc_failed`: kept but not used. |
| Station elevation `-999.9` | **Missing** elevation. | Station file | Null. |
| `mflag H` on TAVG | Average of **hourly** readings (how it was computed). | 1957–2013 only | No effect on the value. |
| `mflag D` on PRCP | Total formed from **four 6-hour totals** (how it was measured). | 1979–1999 only | No effect on the value. |
| TAVG with `sflag = S` | Average over a **UTC** day ending 24:00 UTC, not the local day, per the readme. For a Canadian station that's a different 24 hours from its TMAX and TMIN. | 1957–2013, 13,395 rows: the same rows that carry `mflag H`. Every value in the window is `sflag = C` (Environment Canada). | Not distinguished. Matters only if the window reaches back to `S` data. |
| WSFG `0` **and** WDFG `0` on the same day | **No gust recorded**: Environment Canada's old encoding of what it now expresses by leaving the row out. They always occur together, and the smallest real gust before 2019 is 8.3 m/s (30 km/h). | 2,632 days, 2011-12 to 2018-10 only | **Not handled**: would read as "a 0 km/h gust from the N". Outside the window, so no effect today. |
| WDFG `360` vs `0` | `360` is north; `0` is the "no gust" case above. | All years / pre-2019 | 360 → N. |
| `-9999` | **Missing**, in NOAA's `.dly` file format. The CSV files used here leave the row out instead. | 0 rows | Would be quarantined as `out_of_bounds`, so labelled out of range rather than missing. |
| `mflag P` | **"Missing, presumed zero"**, from US cooperative data. | 0 rows (US only) | **Not handled**: would read as a real 0. Matters for US cities. |
| MDPR / DAPR | Precipitation **totalled over several days**, and how many days. A day without PRCP may be inside such a total. | Not reported by these stations | Not in scope. |

The unhandled cases are listed in the README's "With more time"; each would be a small config rule
(a WSFG/WDFG pair of 0 as `not_reported`; `mflag P` and `-9999` as `missing`).

## Mapping to Environment Canada's API

`api.weather.gc.ca`, collection `climate-daily`. The climate ID is the NOAA station ID without
`CAN0` (CAN01108395 → 1108395). Checked on Ottawa, 12 August 2026 (a 107 km/h gust):

| NOAA | Environment Canada | Difference |
|---|---|---|
| TMAX / TMIN (tenths of °C) | MAX_TEMPERATURE / MIN_TEMPERATURE (°C) | Units only |
| TAVG (tenths of °C) | MEAN_TEMPERATURE (°C) | Units only for current data: both are (max + min) ÷ 2 (18.6 °C from 24.0 and 13.2). NOAA's source-`S` TAVG before 2014 averaged hourly readings instead. |
| PRCP (tenths of mm) | TOTAL_PRECIPITATION (mm) | Units only |
| SNOW (mm) | TOTAL_SNOW (cm) | Units only |
| SNWD (mm) | SNOW_ON_GROUND (cm) | Units only |
| WSFG (tenths of m/s) | SPEED_MAX_GUST (km/h) | Units only: 29.7 m/s × 3.6 = 107 km/h |
| WDFG (degrees) | DIRECTION_MAX_GUST (tens of degrees) | Units only: 31 → 310° |
| `mflag T` | `*_FLAG = T` | Same meaning: trace |
| `qflag` (NOAA's checks) | none | Environment Canada's recent values are provisional; NOAA's checks run later |
