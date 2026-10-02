-- One row per selected station, day in the window and in-scope element, including the days with no
-- observation, so gaps are rows you can count rather than absences you have to infer.
--   valid / trace / qc_failed / out_of_bounds / unparseable   as observed (fct_observations)
--   missing        the station reports this element that year (inventory) but not this day
--   not_reported   absent, and config says absence means "nothing to report" for this element
--                  (Environment Canada omits gusts below ~31 km/h and zero snow depth): value 0
--   not_expected   the station doesn't report this element that year
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
        sp.station_id, sp.obs_date, e.element, e.unit, e.is_core, e.absent_means_zero,
        se.station_id is not null as is_expected
    from spine sp
    cross join {{ ref('int_elements__in_scope') }} e
    left join {{ ref('int_station_elements') }} se
        on se.station_id = sp.station_id and se.element = e.element
       and year(sp.obs_date) between se.first_year and se.last_year
)

select
    g.station_id,
    g.obs_date,
    g.element,
    g.unit,
    g.is_core,
    g.is_expected,
    case
        when f.station_id is not null then f.quality_status
        when not g.is_expected then 'not_expected'
        when g.absent_means_zero then 'not_reported'
        else 'missing'
    end as status,
    case
        when f.is_usable then f.value
        when f.station_id is null and g.is_expected and g.absent_means_zero then 0
    end as value,
    coalesce(f.is_trace, false) as is_trace,
    f.qflag,
    f.raw_value
from grid g
left join {{ ref('fct_observations') }} f
    on f.station_id = g.station_id and f.obs_date = g.obs_date and f.element = g.element and not f.is_deleted
