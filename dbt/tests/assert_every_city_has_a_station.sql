-- Every configured city made it through to the marts with its station.
select c.city
from {{ source('config', 'selected_stations') }} c
anti join {{ ref('dim_station') }} d using (city)
