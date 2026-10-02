{#- Use the configured schema name as is (staging, intermediate, marts) instead of dbt's default
    "<target schema>_<custom schema>", so the warehouse reads raw -> staging -> intermediate -> marts. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name or target.schema }}
{%- endmacro %}
