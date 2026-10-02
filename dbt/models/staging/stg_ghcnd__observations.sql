-- Typed observations. Values that don't parse become null and are caught by tests, not by a failed
-- cast that stops the build. Scaling to real units happens in the fact, using the readme catalog.
select
    station_id,
    try_strptime(obs_date, '%Y%m%d')::date as obs_date,
    element,
    try_cast(value as integer) as raw_value,
    mflag,
    qflag,
    sflag,
    obs_time,
    obs_date as obs_date_text,
    value as value_text,
    _last_changed_at as raw_changed_at,
    _run_id as raw_run_id
from {{ source('raw', 'observations') }}
