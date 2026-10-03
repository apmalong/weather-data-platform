-- Data quality per station and element over the window: how complete, how much was quarantined
-- and why, and how far behind the latest observation is.
with by_status as (
    select
        station_id,
        element,
        count(*) filter (where is_expected) as expected_days,
        count(*) filter (where status = 'valid') as valid_days,
        count(*) filter (where status = 'trace') as trace_days,
        count(*) filter (where status = 'missing') as missing_days,
        count(*) filter (where status = 'not_reported') as not_reported_days,
        count(*) filter (where status = 'qc_failed') as qc_failed_days,
        count(*) filter (where status = 'out_of_bounds') as out_of_bounds_days,
        count(*) filter (where status = 'inconsistent') as inconsistent_days,
        count(*) filter (where status = 'unparseable') as unparseable_days,
        min(obs_date) filter (where status in ('valid', 'trace')) as first_usable_date,
        max(obs_date) filter (where status in ('valid', 'trace')) as last_usable_date
    from {{ ref('fct_station_day_element') }}
    group by all
)

select
    s.city,
    b.*,
    case when b.expected_days > 0
         then round((b.valid_days + b.trace_days + b.not_reported_days) / b.expected_days, 4) end as completeness,
    w.end_date - b.last_usable_date as days_since_last,
    case
        when b.expected_days = 0 then 'not_expected'
        -- An element whose absence is normal (snow depth in summer) can't show a stalled feed.
        when e.absent_means_zero then 'not_applicable'
        when b.last_usable_date is null or w.end_date - b.last_usable_date > w.freshness_error_days then 'stale'
        when w.end_date - b.last_usable_date > w.freshness_warn_days then 'lagging'
        else 'fresh'
    end as freshness
from by_status b
join {{ ref('int_stations__selected') }} s on s.station_id = b.station_id
join {{ ref('int_elements__in_scope') }} e on e.element = b.element
cross join {{ ref('stg_config__run_scope') }} w
