-- Every configured city made it through to the marts with its station.
select c.city
from {{ source('config', 'selected_stations') }} c
left join {{ ref('dim_station') }} d on d.city = c.city
where d.city is null
