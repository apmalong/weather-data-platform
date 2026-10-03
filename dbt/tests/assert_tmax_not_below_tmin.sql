-- A day's usable maximum temperature can't be below its minimum. Inverted source pairs are quarantined
-- as 'inconsistent' in int_observations__assessed, so a row here means that rule is broken: a
-- pipeline bug, which should stop the build.
select
    tmax.station_id,
    tmax.obs_date,
    tmax.value as tmax,
    tmin.value as tmin
from {{ ref('fct_observations') }} as tmax
inner join {{ ref('fct_observations') }} as tmin on tmax.station_id = tmin.station_id and tmax.obs_date = tmin.obs_date
where
    tmax.element = 'TMAX'
    and tmin.element = 'TMIN'
    and tmax.is_usable = true
    and tmin.is_usable = true
    and tmax.value < tmin.value
