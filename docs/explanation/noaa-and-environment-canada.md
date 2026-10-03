# NOAA and Environment Canada

## NOAA's Canadian data is a copy

GHCN-Daily collects data from national weather services; for Canadian stations, the source is
Environment Canada (source flag `C`). NOAA adds value, notably its own quality checks (all 51 values
quarantined here were flagged by them), but its copy also lags and occasionally loses readings.

## What changed just before the brief

On 1 October 2026, NOAA's v3.35 release renamed every Environment Canada station from network code `0`
to `N` and reloaded their histories. The old `CA0…` files, the ones the brief names, are still on the
server but stopped updating on 28 April 2024, when Environment Canada's feed to NOAA broke, and they
store gusts in other units than the readme specifies. Choosing stations from the current metadata
picked the `CAN0…` files without a code change.

## The lag

On 3 October 2026, NOAA's files ended on 29 September, for the Canadian stations and for US airports
alike (Chicago O'Hare, Los Angeles), so it's NOAA's publication cycle, not the Canadian feed.
Environment Canada's own API already had 30 September to 2 October. NOAA's files carried a new
Last-Modified time with identical contents, which is why ingest compares file contents, not timestamps.

The pipeline handles the lag rather than hiding it: the day grid ends at the latest observation, so
unpublished days aren't counted as missing, and the freshness check warns after 7 days without data.

## Checking one against the other

Environment Canada's `climate-daily` API (`api.weather.gc.ca`) uses the climate ID inside the NOAA ID
(CAN0**1108395** → 1108395), so the two line up mechanically. Comparing them:

- **Agreement:** where both have a value, they matched on every day checked, including Vancouver's
  snowless 2025–26 winter: no measurable snowfall, and trace snowfall on three days (20 February,
  10 and 15 March 2026), the same count an Environment Canada meteorologist gave publicly in March.
- **Completeness:** Environment Canada had snow on the ground on 21 days at Toronto and Calgary that
  NOAA's file lacks. Finding one of them (4 cm at Vancouver on 2 February 2025, which the pipeline had
  read as 0) led to the `persistent` snow-depth rule.
- **Definitions:** units differ but meanings match for current data, including the daily mean (both
  (max + min) ÷ 2). NOAA's pre-2014 TAVG averaged hourly readings, so history can't be mixed
  unlabelled.

## Why NOAA is still the source

The brief specifies NOAA's files, and station selection runs on NOAA's metadata and inventory, which
Environment Canada's API doesn't replace; US cities have no Environment Canada equivalent at all. With
more time, the better design for Canadian stations takes each day from Environment Canada as soon as
it's published (provisional), applies NOAA's quality flags when NOAA's copy arrives, fills gaps from
NOAA, and records the source of every value.

Related: [NOAA conventions](../reference/noaa/conventions.md), [data quality](data-quality.md).
