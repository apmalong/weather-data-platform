-- Observations for the selected stations, scaled to real units and assessed. Nothing is dropped:
-- a value that fails NOAA's checks or our bounds is kept with a status saying why it's unusable.
--   valid          passed NOAA's checks and our bounds
--   trace          measurable amount too small to record (mflag T): stored as 0, reported as "trace"
--   qc_failed      NOAA quality flag set (readme QFLAG): quarantined
--   out_of_bounds  outside the element's physical bounds in config: quarantined
--   unparseable    date or value didn't parse
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
