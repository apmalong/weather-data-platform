# Data quality: detect, quarantine, measure, surface

## Nothing is dropped silently

Every value NOAA publishes ends up somewhere with a reason. A value that fails a check is kept in
`fct_observations` with a status saying why it isn't used: `qc_failed` (NOAA's own check),
`out_of_bounds` (physically impossible, per config), `inconsistent` (TMAX below TMIN that day),
`unparseable`. A line that can't be loaded at all goes to `raw.rejected_rows`. Gaps are rows too:
every station × day × element in the window has a status, so a missing day is countable, not an
absence you have to infer. `audit.data_issues` lists it all in one place.

What the pipeline deliberately doesn't do: interpolate missing days, borrow a nearby station's value,
or correct values NOAA flagged. Each would give the narratives a number nobody measured.

## Source errors are quarantined; tests guard the pipeline

A bad value from NOAA never fails the build: it's set aside with a status and counted. If it failed a
test instead, one bad reading would stop the build, and dbt would skip the marts for every city.

The error-severity dbt tests check what the pipeline guarantees after quarantine: unique keys, valid
statuses, no usable TMAX below TMIN. A failure therefore means a bug in our code, and stopping the
build is the right response. Judgement calls (TAVG slightly outside TMIN–TMAX, completeness under 90%)
are warnings.

The inverted TMAX/TMIN case shows the difference. It used to be caught only by a test, so one bad pair
would have failed the build. Now both values are quarantined as `inconsistent`, since either could be
wrong, and the test checks that this rule held.

## Absent doesn't always mean missing

Environment Canada reports a peak gust only above about 30 km/h (the smallest gust reported since 2019
is 31 km/h), and snow depth only when there's snow. Counting those absences as missing would make
completeness wrong and let a narrative say "no wind data". So for gusts and snow depth, an absent day
is `not_reported`: nothing to report, value 0.

But snow on the ground doesn't vanish between readings. Checking Vancouver against Environment Canada's
own record found 2 February 2025: 4 cm on the ground and 5.8 cm of new snow, but no snow-depth row in
NOAA's file, so the pipeline said "0 cm". Snow depth is now `persistent`: an absent day between two
non-zero readings, or on a day with new snowfall, is `missing`. That changed 72 days; all 45 checked at
Toronto and Calgary are backed by Environment Canada (snow on the ground, or no reading either; none
said zero).

A trace is different again: NOAA stores it as 0 with flag `T`. Kept as status `trace`, it reads as "a
trace of", never "no snow". Vancouver's 2025–26 winter had only traces at the airport, which matches
Environment Canada's record and its public statement that the winter was snowless.

## Freshness: an alert, not an outage

An element's latest usable reading is compared with the date of the last ingest: over 7 days it's
`lagging`, over 30 `stale`. A stale station fails a test and the health status goes ERROR, but nothing
is rolled back, because nothing depends on the data quality mart. Narrate skips the station, so no
narrative describes weeks-old weather. Not running the pipeline doesn't make data stale: age is
measured against the last ingest, not the calendar.

Related: [investigate data issues](../how-to/investigate-data-issues.md),
[NOAA conventions](../reference/noaa/conventions.md), [models and tests](../reference/dbt/models-and-tests.md).
