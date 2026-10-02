-- Which in-scope element each selected station reports, and over which years (inventory).
-- An element a station doesn't report isn't "missing" on its days; it was never expected.
select
    s.station_id,
    i.element,
    i.first_year,
    i.last_year
from {{ ref('int_stations__selected') }} s
join {{ ref('stg_ghcnd__inventory') }} i using (station_id)
join {{ ref('int_elements__in_scope') }} e using (element)
