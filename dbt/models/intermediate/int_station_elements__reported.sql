-- Which in-scope element each selected station reports, and over which years (inventory).
-- An element a station doesn't report isn't "missing" on its days; it was never expected.
select
    stations.station_id,
    inventory.element,
    inventory.first_year,
    inventory.last_year
from {{ ref('int_stations__selected') }} as stations
inner join {{ ref('stg_ghcnd__inventory') }} as inventory on stations.station_id = inventory.station_id
inner join {{ ref('int_elements__in_scope') }} as elements on inventory.element = elements.element
