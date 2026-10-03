{{
    config(
        materialized='incremental',
        unique_key=['station_id', 'obs_date', 'element'],
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns',
    )
}}
-- Every observation for the selected stations, full history, assessed. Incremental by change, not
-- by date: a build reprocesses only the rows that
--   1. NOAA changed since the last build (raw.observation_changes: revisions, backfills, removals),
--   2. belong to an element whose policy changed in config (scale, bounds, absent rule),
--   3. belong to a station/element pair new to scope (a city added to config).
-- Rows NOAA removed become tombstones (is_deleted) so downstream sees the removal.
-- `dbt build --full-refresh` rebuilds from raw at any time and gives the same result.
-- depends_on: {{ ref('int_elements__in_scope') }}
-- depends_on: {{ ref('int_stations__selected') }}

with assessed as (
    select * from {{ ref('int_observations__assessed') }}
)

{% if is_incremental() %}
, watermark as (
    select coalesce(max(raw_changed_at), '1900-01-01'::timestamp) as changed_after from {{ this }}
)

, noaa_changes as (
    select distinct station_id, try_strptime(obs_date, '%Y%m%d')::date as obs_date, element
    from {{ source('raw', 'observation_changes') }}
    where changed_at > (select changed_after from watermark)
)

, changed_keys as (
    select station_id, obs_date, element from noaa_changes
    union
    -- TMAX and TMIN are assessed as a pair (inconsistent when TMAX < TMIN), so a change to one
    -- reprocesses the other for that day too
    select station_id, obs_date, case element when 'TMAX' then 'TMIN' else 'TMAX' end
    from noaa_changes where element in ('TMAX', 'TMIN')
    union
    select t.station_id, t.obs_date, t.element
    from {{ this }} t
    join {{ ref('int_elements__in_scope') }} e on e.element = t.element
    where t.policy_hash is distinct from e.policy_hash
    union
    select a.station_id, a.obs_date, a.element
    from assessed a
    join (
        select distinct station_id, element from assessed
        except
        select distinct station_id, element from {{ this }}
    ) new_pairs on new_pairs.station_id = a.station_id and new_pairs.element = a.element
)

, removed as (
    select c.station_id, try_strptime(c.obs_date, '%Y%m%d')::date as obs_date, c.element,
           max(c.changed_at) as changed_at, arg_max(c.run_id, c.changed_at) as run_id
    from {{ source('raw', 'observation_changes') }} c
    join {{ ref('int_stations__selected') }} s on s.station_id = c.station_id
    where c.change = 'delete' and c.changed_at > (select changed_after from watermark)
    group by c.station_id, c.obs_date, c.element
)
{% endif %}

select
    a.station_id, a.obs_date, a.element, a.raw_value, a.value, a.unit, a.mflag, a.qflag, a.sflag, a.is_trace,
    a.quality_status, a.quality_status in ('valid', 'trace') as is_usable, a.policy_hash,
    a.raw_changed_at, a.raw_run_id, false as is_deleted, current_timestamp::timestamp as dbt_loaded_at
from assessed a
{% if is_incremental() %}
-- changed_keys is a union, so its keys are distinct and this join can't duplicate rows
join changed_keys k on k.station_id = a.station_id and k.obs_date = a.obs_date and k.element = a.element

union all

select
    r.station_id, r.obs_date, r.element, null, null, null, null, null, null, false,
    'removed_at_source', false, null,
    r.changed_at, r.run_id, true, current_timestamp::timestamp
from removed r
left join assessed a on a.station_id = r.station_id and a.obs_date = r.obs_date and a.element = r.element
where a.station_id is null   -- removed from NOAA's file and not re-published
{% endif %}
