-- The selected stations, one per configured city, with the elements each reports.
with elements_by_station as (
    select
        station_id,
        string_agg(element, ', ' order by element) as elements_reported
    from {{ ref('int_station_elements__reported') }}
    group by station_id
)

select
    stations.*,
    elements_by_station.elements_reported
from {{ ref('int_stations__selected') }} as stations
left join elements_by_station on stations.station_id = elements_by_station.station_id
