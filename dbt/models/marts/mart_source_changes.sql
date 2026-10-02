-- What NOAA changed, per ingest run and station: new rows, revisions and removals, and how many of
-- them touched dates before the run (backfills and revisions of history, not just new days).
select
    c.run_id,
    min(c.changed_at) as changed_at,
    c.station_id,
    s.city,
    count(*) filter (where c.change = 'insert') as inserted,
    count(*) filter (where c.change = 'update') as updated,
    count(*) filter (where c.change = 'delete') as deleted,
    count(*) filter (where c.change = 'update' and c.old_value is distinct from c.new_value) as value_revisions,
    count(*) filter (where c.change = 'update' and c.old_value is not distinct from c.new_value) as flag_revisions,
    count(*) filter (where c.change in ('update', 'delete')
                     and try_strptime(c.obs_date, '%Y%m%d')::date < c.changed_at::date - 7) as historical_changes,
    min(try_strptime(c.obs_date, '%Y%m%d')::date) as earliest_date_touched,
    max(try_strptime(c.obs_date, '%Y%m%d')::date) as latest_date_touched
from {{ source('raw', 'observation_changes') }} c
left join {{ ref('int_stations__selected') }} s using (station_id)
group by c.run_id, c.station_id, s.city
