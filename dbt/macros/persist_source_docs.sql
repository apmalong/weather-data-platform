{#-
    on-run-end hook: write source table and column descriptions (sources.yml, _docs.md) to the
    warehouse as comments. persist_docs does this for models dbt builds; sources are loaded by
    `wx ingest`, so dbt never builds them and they'd otherwise have no comments. Tables or columns
    that don't exist yet are skipped.
-#}
{% macro _comment_literal(text) %}{{ return("'" ~ (text | trim | replace("'", "''")) ~ "'") }}{% endmacro %}

{% macro persist_source_docs() %}
    {% if not execute %}{{ return('') }}{% endif %}
    {% set statements = [] %}
    {% for source in graph.sources.values() %}
        {% set relation = adapter.get_relation(database=source.database, schema=source.schema,
                                               identifier=source.identifier) %}
        {% if relation is not none %}
            {% set existing = adapter.get_columns_in_relation(relation) | map(attribute='name') | list %}
            {% if source.description %}
                {% do statements.append("comment on table " ~ relation ~ " is "
                                        ~ _comment_literal(source.description)) %}
            {% endif %}
            {% for column in source.columns.values() if column.description and column.name in existing %}
                {% do statements.append("comment on column " ~ relation ~ "." ~ adapter.quote(column.name)
                                        ~ " is " ~ _comment_literal(column.description)) %}
            {% endfor %}
        {% endif %}
    {% endfor %}
    {% if statements %}
        {% do run_query(statements | join(";\n")) %}
        {% do adapter.commit() %}
    {% endif %}
{% endmacro %}
