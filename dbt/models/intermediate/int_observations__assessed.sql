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
        observations.station_id,
        observations.obs_date,
        observations.element,
        observations.raw_value,
        -- fixed precision (tenths at most), so 0.1 scaling never shows float noise like -15.100000000000001
        (observations.raw_value * elements.scale)::decimal(12, 1) as value,
        elements.unit,
        observations.mflag,
        observations.qflag,
        observations.sflag,
        observations.mflag = 'T' as is_trace,
        case
            when observations.obs_date is null or observations.raw_value is null then 'unparseable'
            when observations.qflag is not null then 'qc_failed'
            when
                observations.raw_value * elements.scale < elements.lower_bound
                or observations.raw_value * elements.scale > elements.upper_bound
                then 'out_of_bounds'
            when observations.mflag = 'T' then 'trace'
            else 'valid'
        end as quality_status,
        elements.policy_hash,
        observations.raw_changed_at,
        observations.raw_run_id
    from {{ ref('stg_ghcnd__observations') }} as observations
    inner join {{ ref('int_stations__selected') }} as stations on observations.station_id = stations.station_id
    inner join {{ ref('int_elements__in_scope') }} as elements on observations.element = elements.element
),

inverted_days as (
    select
        tmax.station_id,
        tmax.obs_date
    from checked as tmax
    inner join checked as tmin on tmax.station_id = tmin.station_id and tmax.obs_date = tmin.obs_date
    where
        tmax.element = 'TMAX' and tmin.element = 'TMIN'
        and tmax.quality_status = 'valid' and tmin.quality_status = 'valid'
        and tmax.value < tmin.value
)

select
    checked.station_id,
    checked.obs_date,
    checked.element,
    checked.raw_value,
    checked.value,
    checked.unit,
    checked.mflag,
    checked.qflag,
    checked.sflag,
    checked.is_trace,
    case
        when inverted.station_id is not null and checked.element in ('TMAX', 'TMIN') then 'inconsistent'
        else checked.quality_status
    end as quality_status,
    checked.policy_hash,
    checked.raw_changed_at,
    checked.raw_run_id
from checked
left join inverted_days as inverted on checked.station_id = inverted.station_id and checked.obs_date = inverted.obs_date
