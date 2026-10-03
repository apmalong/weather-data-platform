{{
    config(
        materialized='incremental',
        unique_key=['station_id', 'obs_date', 'element'],
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns',
        pre_hook="{% if is_incremental() %}
            delete from {{ this }}
            where station_id not in (select station_id from {{ source('config', 'selected_stations') }})
        {% endif %}",
    )
}}
-- Every observation for the selected stations, full history, assessed. Incremental by change, not
-- by date: a build reprocesses only the rows that
--   1. NOAA changed since the last build (raw.observation_changes: revisions, backfills, removals),
--      and the other of a TMAX/TMIN pair when one changes (they're assessed together),
--   2. belong to an element whose policy changed in config (scale, bounds, absent rule),
--   3. belong to a station/element pair new to scope (a city added to config).
-- Rows NOAA removed become tombstones (is_deleted) so downstream sees the removal. A station that
-- leaves scope (a city removed or re-pointed in config) is dropped by the pre-hook, as a full refresh would.
-- `dbt build --full-refresh` rebuilds from raw at any time and gives the same result.
-- depends_on: {{ ref('int_elements__in_scope') }}
-- depends_on: {{ ref('int_stations__selected') }}

with assessed as (
    select * from {{ ref('int_observations__assessed') }}
){% if is_incremental() %},

watermark as (
    select coalesce(max(raw_changed_at), '1900-01-01'::timestamp) as changed_after
    from {{ this }}
),

noaa_changes as (
    select distinct
        changes.station_id,
        changes.element,
        try_strptime(changes.obs_date, '%Y%m%d')::date as obs_date
    from {{ source('raw', 'observation_changes') }} as changes
    cross join watermark
    where changes.changed_at > watermark.changed_after
),

new_station_elements as (
    select distinct
        station_id,
        element
    from assessed
    except
    select distinct
        station_id,
        element
    from {{ this }}
),

changed_keys as (
    select
        station_id,
        obs_date,
        element
    from noaa_changes
    union
    -- TMAX and TMIN are assessed as a pair (inconsistent when TMAX < TMIN), so a change to one
    -- reprocesses the other for that day too
    select
        station_id,
        obs_date,
        case element when 'TMAX' then 'TMIN' else 'TMAX' end as element
    from noaa_changes
    where element in ('TMAX', 'TMIN')
    union
    select
        current_rows.station_id,
        current_rows.obs_date,
        current_rows.element
    from {{ this }} as current_rows
    inner join {{ ref('int_elements__in_scope') }} as elements on current_rows.element = elements.element
    where current_rows.policy_hash is distinct from elements.policy_hash
    union
    select
        assessed.station_id,
        assessed.obs_date,
        assessed.element
    from assessed
    inner join new_station_elements
        on
            assessed.station_id = new_station_elements.station_id
            and assessed.element = new_station_elements.element
),

removed as (
    select
        changes.station_id,
        changes.element,
        try_strptime(changes.obs_date, '%Y%m%d')::date as obs_date,
        max(changes.changed_at) as changed_at,
        arg_max(changes.run_id, changes.changed_at) as run_id
    from {{ source('raw', 'observation_changes') }} as changes
    inner join {{ ref('int_stations__selected') }} as stations on changes.station_id = stations.station_id
    cross join watermark
    where
        changes.change = 'delete'
        and changes.changed_at > watermark.changed_after
    group by changes.station_id, changes.element, changes.obs_date
)
{% endif %}

select
    assessed.station_id,
    assessed.obs_date,
    assessed.element,
    assessed.raw_value,
    assessed.value,
    assessed.unit,
    assessed.mflag,
    assessed.qflag,
    assessed.sflag,
    assessed.is_trace,
    assessed.quality_status,
    assessed.quality_status in ('valid', 'trace') as is_usable,
    assessed.policy_hash,
    assessed.raw_changed_at,
    assessed.raw_run_id,
    false as is_deleted,
    current_timestamp::timestamp as dbt_loaded_at
from assessed
{% if is_incremental() %}
-- changed_keys is a union, so its keys are distinct and this join can't duplicate rows
inner join changed_keys
    on
        assessed.station_id = changed_keys.station_id
        and assessed.obs_date = changed_keys.obs_date
        and assessed.element = changed_keys.element

union all

select
    removed.station_id,
    removed.obs_date,
    removed.element,
    null as raw_value,
    null as value,
    null as unit,
    null as mflag,
    null as qflag,
    null as sflag,
    false as is_trace,
    'removed_at_source' as quality_status,
    false as is_usable,
    null as policy_hash,
    removed.changed_at as raw_changed_at,
    removed.run_id as raw_run_id,
    true as is_deleted,
    current_timestamp::timestamp as dbt_loaded_at
from removed
left join assessed
    on
        removed.station_id = assessed.station_id
        and removed.obs_date = assessed.obs_date
        and removed.element = assessed.element
where assessed.station_id is null  -- removed from NOAA's file and not re-published
{% endif %}
