{#- Generic tests, kept in the project so the build needs no `dbt deps` (no network, nothing to pin). -#}

{% test unique_combination(model, columns) %}
    select {{ columns | join(', ') }}, count(*) as rows
    from {{ model }}
    group by all
    having count(*) > 1
{% endtest %}

{#- Rows outside [lower, upper]; bounds can come from columns of the model itself. -#}
{% test within_bounds(model, column_name, lower, upper) %}
    select * from {{ model }}
    where {{ column_name }} is not null and ({{ column_name }} < {{ lower }} or {{ column_name }} > {{ upper }})
{% endtest %}

{% test single_row(model) %}
    select count(*) as rows from {{ model }} having count(*) <> 1
{% endtest %}
