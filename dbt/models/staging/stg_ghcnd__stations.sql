-- ID = FIPS country code (2) + network code (1) + station number (8), per readme section IV.
select
    id as station_id,
    left(id, 2) as country_code,
    substr(id, 3, 1) as network_code,
    substr(id, 4) as network_station_id,
    try_cast(latitude as double) as latitude,
    try_cast(longitude as double) as longitude,
    try_cast(nullif(elevation, '-999.9') as double) as elevation_m,   -- -999.9 = missing (readme)
    state as state_code,
    name as station_name,
    gsn_flag = 'GSN' as is_gsn,
    hcn_crn_flag,
    wmo_id
from {{ source('raw', 'stations') }}
