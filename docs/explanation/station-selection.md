# Station selection: cities, not station IDs

## Why not just list the five station IDs?

The brief requires that adding a sixth city change only configuration. Listing station IDs would
make every new city a lookup by hand. So the config lists cities, and the pipeline finds each city's
station in NOAA's own metadata (`ghcnd-stations.txt` for names and coordinates, `ghcnd-inventory.txt`
for which elements each station reports, and in which years).

It paid off before the brief arrived. NOAA's v3.35 release (1 October 2026) renamed every Environment
Canada station from network code `0` to `N`, so the brief's file names (`CA006158731`) point at files
that stopped updating in April 2024. Resolving from the metadata picked the current `CAN0…` files with
no change.

## The rule, in two steps

1. **Find the city's airport.** Among stations in the province whose name starts with the city, take
   those named like an airport (`… A` for Environment Canada, `… AP` for NOAA's US stations), and
   prefer the international one, then the one reporting more of TMAX, TMIN and PRCP, then the most
   recent data.
2. **Use the station at that airport that reports everything.** That's the airport's own station if it
   reports TMAX, TMIN and PRCP across the whole window; otherwise the nearest station that does, within
   5 km.

Ties go to the station with more elements, then the lowest ID, so the same metadata always gives the
same answer. Every candidate and the reason it won or lost is recorded.

## Why the distance step exists

Newer Environment Canada airport stations often report temperature but not precipitation. A climate
station beside them, often named `… CS` or `… RCS`, reports both. Name matching alone resolved 9 of 20
extra Canadian cities; the distance step resolved 9 more:

| City | Station used | Distance from the airport station |
|---|---|---|
| Regina, London, Kelowna | `REGINA RCS`, `LONDON CS`, `KELOWNA` | 0.1 km |
| Winnipeg | `WINNIPEG A CS` | 1.0 km |
| Iqaluit, Saskatoon, Québec | climate stations | 1.2–1.6 km |
| Whitehorse | `WHITEHORSE AUTO` | 3.1 km |

5 km takes all of them, and keeps out stations that aren't at the airport: Winnipeg's next
full-coverage station, downtown at The Forks, is 8.3 km away and measures different weather.

Distances come from the coordinates in NOAA's station file (haversine, great-circle distance). The
"airport" is the airport station's coordinates: there's no separate airport dataset.

For the five cities in the brief, every airport station reports everything itself, so this step
never fires. It's what makes the sixth-city requirement hold for cities like Winnipeg.

## How well it generalises

Tested against NOAA's full metadata for 20 more Canadian and 15 US cities: 29 of 35 resolve to the
main airport from config alone; the other 6 need one field (`name_prefix` or a pinned `station_id`)
because their airport isn't named after the city (JFK, Kitchener/Waterloo) or is another city's
(Mississauga is Pearson, which is Toronto's). The rules fail loudly rather than guess.

## Limits

Finding the airport depends on naming conventions. Matching cities to airports by coordinates would
remove that, but NOAA doesn't provide city or airport locations; it would mean adding an airport
dataset. The coverage check works in whole years, so a station that stopped in March passes until the
freshness check catches it.

Related: [add a city](../how-to/add-a-city.md), [ingest reference](../reference/app/ingest.md).
