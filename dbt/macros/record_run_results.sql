{#-
    on-run-end hook: one row per dbt invocation in ops.dbt_runs and one per model, seed or test in
    ops.dbt_node_runs (status, duration, rows, failures, message), in the same `ops` schema as the
    ingest and narrative ledgers. Written from dbt's own connection, so no second DuckDB writer.
-#}
{% macro record_run_results(results) %}
    {% if not execute or not results %}{{ return('') }}{% endif %}
    {% do run_query(
        "create schema if not exists ops;
         create table if not exists ops.dbt_runs (invocation_id varchar, command varchar, started_at timestamp,
             finished_at timestamp, nodes integer, wx_run_id varchar);
         create table if not exists ops.dbt_node_runs (invocation_id varchar, unique_id varchar, name varchar,
             resource_type varchar, status varchar, execution_seconds double, rows_affected bigint,
             failures bigint, message varchar)") %}
    {% set fmt = '%Y-%m-%d %H:%M:%S.%f' %}
    {% do run_query("insert into ops.dbt_runs values (" ~ ledger_literal(invocation_id) ~ ", "
        ~ ledger_literal(flags.WHICH) ~ ", " ~ ledger_literal(run_started_at.strftime(fmt)) ~ "::timestamp, "
        ~ ledger_literal(modules.datetime.datetime.now(modules.pytz.utc).strftime(fmt)) ~ "::timestamp, "
        ~ results | length ~ ", " ~ ledger_literal(env_var('WX_RUN_ID', '') or none) ~ ")") %}
    {% set rows = [] %}
    {% for r in results %}
        {% set response = r.adapter_response or {} %}
        {% do rows.append("(" ~ [ledger_literal(invocation_id), ledger_literal(r.node.unique_id),
            ledger_literal(r.node.name), ledger_literal(r.node.resource_type), ledger_literal(r.status | string),
            ledger_literal(r.execution_time), ledger_literal(response.get('rows_affected')),
            ledger_literal(r.failures),
            ledger_literal((r.message or '') | string | truncate(500, true, '...')
                           if r.status | string in ('error', 'fail', 'warn') else none)] | join(', ') ~ ")") %}
    {% endfor %}
    {% do run_query("insert into ops.dbt_node_runs values " ~ rows | join(', ')) %}
    {{ return('') }}
{% endmacro %}

{% macro ledger_literal(value) %}
    {%- if value is none or (value is number and value < 0) -%}{{ return('null') }}
    {%- elif value is number -%}{{ return(value | string) }}
    {%- else -%}{{ return("'" ~ (value | string | replace("'", "''")) ~ "'") }}
    {%- endif -%}
{% endmacro %}
