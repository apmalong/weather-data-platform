-- Every configured city made it through to the marts with its station.
select configured.city
from {{ source('config', 'selected_stations') }} as configured
left join {{ ref('dim_station') }} as dims on configured.city = dims.city
where dims.city is null
