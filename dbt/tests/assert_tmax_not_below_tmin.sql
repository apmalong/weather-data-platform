-- A day's usable maximum temperature can't be below its minimum.
select x.station_id, x.obs_date, x.value as tmax, n.value as tmin
from {{ ref('fct_observations') }} x
join {{ ref('fct_observations') }} n on n.station_id = x.station_id and n.obs_date = x.obs_date
where x.element = 'TMAX' and n.element = 'TMIN' and x.is_usable and n.is_usable and x.value < n.value
