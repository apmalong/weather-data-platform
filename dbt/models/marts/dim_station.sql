select
    s.*,
    (select string_agg(element, ', ' order by element) from {{ ref('int_station_elements') }} se
     where se.station_id = s.station_id) as elements_reported
from {{ ref('int_stations__selected') }} s
