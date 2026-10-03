{#-
    on-run-end hook: audit.all_failures, every failing row of every data test in one place.
    store_failures gives each test its own table with its own columns, so this view unions them
    with the row as JSON: one row per failure, with the test, the model it tests and its severity.
    Built from the tests the project defines now, so a renamed or removed test's leftover table can't
    show stale failures. Existing tables are read from the catalog, not dbt's relation cache, which
    misses most of them in an on-run-end hook.
-#}
{% macro audit_failures_view() %}
    {% if not execute %}{{ return('') }}{% endif %}
    {% set existing = run_query("select table_name from information_schema.tables "
                                ~ "where table_schema = 'audit' and table_type = 'BASE TABLE'").columns[0].values() %}
    {% set selects = [] %}
    {% for node in graph.nodes.values() if node.resource_type == 'test' and node.alias in existing %}
        {% set tested = node.depends_on.nodes | map('replace', 'model.weather.', '')
                                              | map('replace', 'source.weather.', '') | join(', ') %}
        {% do selects.append(
            "select " ~ dbt.string_literal(node.name) ~ " as test_name, "
            ~ dbt.string_literal(tested) ~ " as tested, "
            ~ dbt.string_literal(node.config.severity | lower) ~ " as severity, "
            ~ "to_json(t)::varchar as failing_row from audit." ~ adapter.quote(node.alias) ~ " t") %}
    {% endfor %}
    {% set body = selects | join("\nunion all\n") if selects else
        "select null::varchar as test_name, null::varchar as tested, null::varchar as severity, "
        ~ "null::varchar as failing_row where false" %}
    {% do run_query("create schema if not exists audit; create or replace view audit.all_failures as\n" ~ body) %}
    {% do adapter.commit() %}
    {{ return('') }}
{% endmacro %}
