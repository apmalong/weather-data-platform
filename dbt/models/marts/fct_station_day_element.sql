-- One row per selected station, day in the window and in-scope element, including the days with no
-- observation, so gaps are rows you can count rather than absences you have to infer.
--   valid / trace / qc_failed / out_of_bounds / inconsistent / unparseable   as observed (fct_observations)
--   missing        the station reports this element that year (inventory) but not this day
--   not_reported   absent, and config says absence means "nothing to report" for this element
--                  (Environment Canada omits gusts below ~31 km/h and zero snow depth): value 0
--   not_expected   the station doesn't report this element that year
-- A persistent element (snow on the ground) can't be "nothing to report" while there's evidently
-- snow: an absent day between two non-zero readings, or on a day its feeding element (new snowfall)
-- is non-zero, is missing. Checked against Environment Canada: Vancouver, 2 and 6 February 2025.
-- The window ends at the latest observation date, so publication lag isn't counted as missing;
-- per-station lag is measured by mart_data_quality.days_since_last.
with latest_observation as (
    select max(obs_date) as latest_date
    from {{ ref('fct_observations') }}
    where is_deleted = false
),

bounds as (
    select
        scope.start_date,
        least(scope.end_date, latest_observation.latest_date) as end_date
    from {{ ref('stg_config__run_scope') }} as scope
    cross join latest_observation
),

spine as (
    select
        stations.station_id,
        unnest(generate_series(bounds.start_date, bounds.end_date, interval 1 day))::date as obs_date
    from {{ ref('int_stations__selected') }} as stations
    cross join bounds
),

grid as (
    select
        spine.station_id,
        spine.obs_date,
        elements.element,
        elements.unit,
        elements.is_core,
        elements.absent_means_zero,
        elements.persistent,
        elements.fed_by,
        station_elements.station_id is not null as is_expected
    from spine
    cross join {{ ref('int_elements__in_scope') }} as elements
    left join {{ ref('int_station_elements__reported') }} as station_elements
        on
            spine.station_id = station_elements.station_id and elements.element = station_elements.element
            and year(spine.obs_date) between station_elements.first_year and station_elements.last_year
),

observed as (
    select
        grid.*,
        observations.station_id is not null as has_row,
        observations.quality_status,
        observations.is_usable,
        observations.value as observed_value,
        observations.is_trace,
        observations.qflag,
        observations.raw_value,
        -- the nearest usable readings on either side (trace counts as 0)
        last_value(case when observations.is_usable = true then observations.value end ignore nulls) over (
            partition by grid.station_id, grid.element order by grid.obs_date
            rows between unbounded preceding and 1 preceding
        ) as previous_reading,
        first_value(case when observations.is_usable = true then observations.value end ignore nulls) over (
            partition by grid.station_id, grid.element order by grid.obs_date
            rows between 1 following and unbounded following
        ) as next_reading
    from grid
    left join {{ ref('fct_observations') }} as observations
        on
            grid.station_id = observations.station_id
            and grid.obs_date = observations.obs_date
            and grid.element = observations.element
            and observations.is_deleted = false
),

assessed as (
    select
        observed.*,
        observed.persistent and (
            (observed.previous_reading > 0 and observed.next_reading > 0)
            or coalesce(fed.observed_value, 0) > 0
        ) as evidently_present
    from observed
    left join observed as fed
        on
            observed.station_id = fed.station_id
            and observed.obs_date = fed.obs_date
            and observed.fed_by = fed.element
            and fed.is_usable = true
)

select
    station_id,
    obs_date,
    element,
    unit,
    is_core,
    is_expected,
    case
        when has_row = true then quality_status
        when is_expected = false then 'not_expected'
        when absent_means_zero = true and coalesce(evidently_present, false) = false then 'not_reported'
        else 'missing'
    end as status,
    case
        when is_usable = true then observed_value
        when
            has_row = false
            and is_expected = true
            and absent_means_zero = true
            and coalesce(evidently_present, false) = false
            then 0
    end as value,
    coalesce(is_trace, false) as is_trace,
    qflag,
    raw_value
from assessed
