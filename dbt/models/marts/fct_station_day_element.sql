-- One row per selected station, day in the window and in-scope element, including the days with no
-- observation, so gaps are rows you can count rather than absences you have to infer.
--   valid / trace / qc_failed / out_of_bounds / unparseable   as observed (fct_observations)
--   missing        the station reports this element that year (inventory) but not this day
--   not_reported   absent, and config says absence means "nothing to report" for this element
--                  (Environment Canada omits gusts below ~31 km/h and zero snow depth): value 0
--   not_expected   the station doesn't report this element that year
-- A persistent element (snow on the ground) can't be "nothing to report" while there's evidently
-- snow: an absent day between two non-zero readings, or on a day its feeding element (new snowfall)
-- is non-zero, is missing. Checked against Environment Canada: Vancouver, 2 and 6 February 2025.
-- The window ends at the latest observation date, so publication lag isn't counted as missing;
-- per-station lag is measured by mart_data_quality.days_since_last.
with bounds as (
    select
        w.start_date,
        least(w.end_date, (select max(obs_date) from {{ ref('fct_observations') }} where not is_deleted)) as end_date
    from {{ ref('stg_config__run_scope') }} w
)

, spine as (
    select s.station_id, unnest(generate_series(b.start_date, b.end_date, interval 1 day))::date as obs_date
    from {{ ref('int_stations__selected') }} s
    cross join bounds b
)

, grid as (
    select
        sp.station_id, sp.obs_date, e.element, e.unit, e.is_core, e.absent_means_zero, e.persistent, e.fed_by,
        se.station_id is not null as is_expected
    from spine sp
    cross join {{ ref('int_elements__in_scope') }} e
    left join {{ ref('int_station_elements') }} se
        on se.station_id = sp.station_id and se.element = e.element
       and year(sp.obs_date) between se.first_year and se.last_year
)

, observed as (
    select
        g.*,
        f.station_id is not null as has_row,
        f.quality_status,
        f.is_usable,
        f.value as observed_value,
        f.is_trace,
        f.qflag,
        f.raw_value,
        -- the nearest usable readings on either side (trace counts as 0)
        last_value(case when f.is_usable then f.value end ignore nulls) over (
            partition by g.station_id, g.element order by g.obs_date
            rows between unbounded preceding and 1 preceding) as previous_reading,
        first_value(case when f.is_usable then f.value end ignore nulls) over (
            partition by g.station_id, g.element order by g.obs_date
            rows between 1 following and unbounded following) as next_reading
    from grid g
    left join {{ ref('fct_observations') }} f
        on f.station_id = g.station_id and f.obs_date = g.obs_date and f.element = g.element and not f.is_deleted
)

, assessed as (
    select
        o.*,
        o.persistent and (
            (o.previous_reading > 0 and o.next_reading > 0)
            or coalesce(fed.observed_value, 0) > 0
        ) as evidently_present
    from observed o
    left join observed fed
        on fed.station_id = o.station_id and fed.obs_date = o.obs_date and fed.element = o.fed_by and fed.is_usable
)

select
    station_id,
    obs_date,
    element,
    unit,
    is_core,
    is_expected,
    case
        when has_row then quality_status
        when not is_expected then 'not_expected'
        when absent_means_zero and not coalesce(evidently_present, false) then 'not_reported'
        else 'missing'
    end as status,
    case
        when is_usable then observed_value
        when not has_row and is_expected and absent_means_zero and not coalesce(evidently_present, false) then 0
    end as value,
    coalesce(is_trace, false) as is_trace,
    qflag,
    raw_value
from assessed
