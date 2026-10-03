-- Observations for the selected stations, scaled to real units and assessed. Nothing is dropped:
-- a value that fails NOAA's checks or ours is kept with a status saying why it's unusable.
--   valid          passed NOAA's checks and ours
--   trace          measurable amount too small to record (mflag T): stored as 0, reported as "trace"
--   qc_failed      NOAA quality flag set (readme QFLAG): quarantined
--   out_of_bounds  outside the element's physical bounds in config: quarantined
--   inconsistent   the day's maximum temperature is below its minimum: both quarantined, since
--                  either could be the wrong one (a source error NOAA's checks didn't flag)
--   unparseable    date or value didn't parse
-- Source errors are quarantined here rather than failing a test, so one bad reading can't stop the
-- build for every station; assert_tmax_not_below_tmin then checks this rule, not the source.
with checked as (
    select
        o.station_id,
        o.obs_date,
        o.element,
        o.raw_value,
        -- fixed precision (tenths at most), so 0.1 scaling never shows float noise like -15.100000000000001
        (o.raw_value * e.scale)::decimal(12, 1) as value,
        e.unit,
        o.mflag,
        o.qflag,
        o.sflag,
        o.mflag = 'T' as is_trace,
        case
            when o.obs_date is null or o.raw_value is null then 'unparseable'
            when o.qflag is not null then 'qc_failed'
            when o.raw_value * e.scale < e.lower_bound or o.raw_value * e.scale > e.upper_bound then 'out_of_bounds'
            when o.mflag = 'T' then 'trace'
            else 'valid'
        end as quality_status,
        e.policy_hash,
        o.raw_changed_at,
        o.raw_run_id
    from {{ ref('stg_ghcnd__observations') }} o
    join {{ ref('int_stations__selected') }} s on s.station_id = o.station_id
    join {{ ref('int_elements__in_scope') }} e on e.element = o.element
)

, inverted_days as (
    select x.station_id, x.obs_date
    from checked x
    join checked n on n.station_id = x.station_id and n.obs_date = x.obs_date
    where x.element = 'TMAX' and n.element = 'TMIN'
      and x.quality_status = 'valid' and n.quality_status = 'valid'
      and x.value < n.value
)

select
    c.station_id, c.obs_date, c.element, c.raw_value, c.value, c.unit, c.mflag, c.qflag, c.sflag, c.is_trace,
    case when i.station_id is not null and c.element in ('TMAX', 'TMIN') then 'inconsistent'
         else c.quality_status end as quality_status,
    c.policy_hash, c.raw_changed_at, c.raw_run_id
from checked c
left join inverted_days i on i.station_id = c.station_id and i.obs_date = c.obs_date
