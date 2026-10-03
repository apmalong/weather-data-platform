-- The configured cities' stations, as resolved from the metadata by `wx ingest`, with their metadata.
select
    selected.city,
    selected.province,
    stations.station_id,
    stations.station_name,
    stations.country_code,
    countries.country_name,
    stations.state_code,
    states.state_name,
    stations.network_code,
    stations.network_station_id,
    stations.latitude,
    stations.longitude,
    stations.elevation_m,
    stations.wmo_id
from {{ source('config', 'selected_stations') }} as selected
inner join {{ ref('stg_ghcnd__stations') }} as stations on selected.station_id = stations.station_id
left join {{ ref('stg_ghcnd__countries') }} as countries on stations.country_code = countries.country_code
left join {{ ref('stg_ghcnd__states') }} as states on stations.state_code = states.state_code
