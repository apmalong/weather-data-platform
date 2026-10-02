{{ config(severity='warn') }}
-- TAVG is a mean of hourly readings, so it should sit between the day's TMIN and TMAX. A warning,
-- not an error: different sources and rounding can put it marginally outside (0.5 C tolerance).
select a.station_id, a.obs_date, a.value as tavg, n.value as tmin, x.value as tmax
from {{ ref('fct_observations') }} a
join {{ ref('fct_observations') }} n using (station_id, obs_date)
join {{ ref('fct_observations') }} x using (station_id, obs_date)
where a.element = 'TAVG' and n.element = 'TMIN' and x.element = 'TMAX'
  and a.is_usable and n.is_usable and x.is_usable
  and (a.value < n.value - 0.5 or a.value > x.value + 0.5)
