-- What NOAA changed, per ingest run and station: new rows, revisions and removals, and how many of
-- them touched dates before the run (backfills and revisions of history, not just new days).
select
    changes.run_id,
    min(changes.changed_at) as changed_at,
    changes.station_id,
    stations.city,
    count(*) filter (where changes.change = 'insert') as inserted,
    count(*) filter (where changes.change = 'update') as updated,
    count(*) filter (where changes.change = 'delete') as deleted,
    count(*) filter (
        where changes.change = 'update' and changes.old_value is distinct from changes.new_value
    ) as value_revisions,
    count(*) filter (
        where changes.change = 'update' and changes.old_value is not distinct from changes.new_value
    ) as flag_revisions,
    count(
        *) filter (
        where changes.change in ('update', 'delete')
        and try_strptime(changes.obs_date, '%Y%m%d')::date < changes.changed_at::date - 7
    ) as historical_changes,
    min(try_strptime(changes.obs_date, '%Y%m%d')::date) as earliest_date_touched,
    max(try_strptime(changes.obs_date, '%Y%m%d')::date) as latest_date_touched
from {{ source('raw', 'observation_changes') }} as changes
left join {{ ref('int_stations__selected') }} as stations on changes.station_id = stations.station_id
group by changes.run_id, changes.station_id, stations.city
