{#-
    on-run-end hook (after audit_failures_view): audit.data_issues, everything wrong with the data in
    one place, one row per issue. Four kinds, from where each is already kept:
      quarantined      a value NOAA flagged, outside our bounds or unparseable (fct_observations)
      rejected_row     a line that couldn't be loaded at all (raw.rejected_rows)
      revised_by_noaa  NOAA changed or removed a value it had published (raw.observation_changes)
      test_failure     output that breaks a data test after all that (audit.all_failures)
    Expected gaps (missing, not reported) aren't issues; mart_data_quality counts them.
-#}
{% macro data_issues_view() %}
    {% if not execute %}{{ return('') }}{% endif %}
    {% set sql %}
create or replace view audit.data_issues as
with stations as (select station_id, city from config.selected_stations)

select 'quarantined' as issue_type, 'info' as severity, o.station_id, s.city, o.obs_date, o.element,
       o.raw_value::varchar as value,
       case o.quality_status
           when 'qc_failed' then 'failed NOAA quality check ' || o.qflag || ': ' || case o.qflag   -- readme section III
               when 'D' then 'duplicate' when 'G' then 'gap' when 'I' then 'internal consistency'
               when 'K' then 'streak/frequent value' when 'L' then 'multiday period length'
               when 'M' then 'megaconsistency' when 'N' then 'naught' when 'O' then 'climatological outlier'
               when 'R' then 'lagged range' when 'S' then 'spatial consistency' when 'T' then 'temporal consistency'
               when 'W' then 'too warm for snow' when 'X' then 'bounds' when 'Z' then 'Datzilla investigation'
               else 'unknown flag' end
           when 'out_of_bounds' then 'outside the physical bounds in config'
           else 'value or date did not parse'
       end as reason,
       'marts.fct_observations' as found_in, o.dbt_loaded_at as detected_at
from marts.fct_observations o   -- a hook can't use ref(); the schema is fixed by generate_schema_name
left join stations s using (station_id)
where o.quality_status in ('qc_failed', 'out_of_bounds', 'unparseable')

union all
select 'rejected_row', 'warn', r.station_id, s.city, null, null, r.line, r.reason,
       'raw.rejected_rows', r.rejected_at
from raw.rejected_rows r
left join stations s using (station_id)

union all
select 'revised_by_noaa', 'info', c.station_id, s.city, try_strptime(c.obs_date, '%Y%m%d')::date, c.element,
       coalesce(c.new_value, c.old_value),
       case when c.change = 'delete' then 'removed by NOAA (was ' || c.old_value || ')'
            when c.old_value is distinct from c.new_value then 'value revised by NOAA: ' || c.old_value || ' -> ' || c.new_value
            else 'flags revised by NOAA: ' || c.old_flags || ' -> ' || c.new_flags end,
       'raw.observation_changes', c.changed_at
from raw.observation_changes c
left join stations s using (station_id)
where c.change in ('update', 'delete')

union all
select 'test_failure', f.severity, json_extract_string(f.failing_row, '$.station_id') as station_id, s.city,
       try_cast(json_extract_string(f.failing_row, '$.obs_date') as date),
       json_extract_string(f.failing_row, '$.element'), f.failing_row,
       'failed test ' || f.test_name || ' on ' || f.tested,
       'audit.all_failures', null
from audit.all_failures f
left join stations s on s.station_id = json_extract_string(f.failing_row, '$.station_id')
    {% endset %}
    {% do run_query(sql) %}
    {% do adapter.commit() %}
    {{ return('') }}
{% endmacro %}
