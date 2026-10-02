-- The configured cities' stations, as resolved from the metadata by `wx ingest`, with their metadata.
select
    sel.city,
    sel.province,
    st.station_id,
    st.station_name,
    st.country_code,
    co.country_name,
    st.state_code,
    sa.state_name,
    st.network_code,
    st.network_station_id,
    st.latitude,
    st.longitude,
    st.elevation_m,
    st.wmo_id
from {{ source('config', 'selected_stations') }} sel
join {{ ref('stg_ghcnd__stations') }} st on st.station_id = sel.station_id
left join {{ ref('stg_ghcnd__countries') }} co on co.country_code = st.country_code
left join {{ ref('stg_ghcnd__states') }} sa on sa.state_code = st.state_code
