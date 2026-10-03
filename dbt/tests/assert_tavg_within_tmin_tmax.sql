{{ config(severity='warn') }}
-- TAVG is a mean of hourly readings, so it should sit between the day's TMIN and TMAX. A warning,
-- not an error: different sources and rounding can put it marginally outside (0.5 C tolerance).
select
    tavg.station_id,
    tavg.obs_date,
    tavg.value as tavg,
    tmin.value as tmin,
    tmax.value as tmax
from {{ ref('fct_observations') }} as tavg
inner join {{ ref('fct_observations') }} as tmin on tavg.station_id = tmin.station_id and tavg.obs_date = tmin.obs_date
inner join {{ ref('fct_observations') }} as tmax on tavg.station_id = tmax.station_id and tavg.obs_date = tmax.obs_date
where
    tavg.element = 'TAVG' and tmin.element = 'TMIN' and tmax.element = 'TMAX'
    and tavg.is_usable = true and tmin.is_usable = true and tmax.is_usable = true
    and (tavg.value < tmin.value - 0.5 or tavg.value > tmax.value + 0.5)
