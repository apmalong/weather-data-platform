{#-
    The elements in scope for this run, read from the warehouse at execution time:
    elements the selected stations report in raw.inventory during the window, that the readme's
    catalog defines (exact codes, not patterns like WT**), minus config.elements exclusions.
    Ordered core elements first. Models use it to build columns dynamically, so a new element or
    station needs no SQL change.
-#}
{% macro scoped_elements() %}
    {% if not execute %}{{ return([]) }}{% endif %}
    {% set query %}
        select c.code, coalesce(p.absent_means_zero, false) as absent_means_zero
        from {{ source('raw', 'element_catalog') }} c
        left join {{ source('config', 'elements') }} p on p.element = c.code
        where c.code in (
            select i.element
            from {{ source('raw', 'inventory') }} i
            join {{ source('config', 'selected_stations') }} s on s.station_id = i.id
            cross join {{ source('config', 'window') }} w
            where i.first_year::int <= year(w.end_date) and i.last_year::int >= year(w.start_date))
          and not coalesce(p.excluded, false)
        order by not c.core, c.code
    {% endset %}
    {% set elements = [] %}
    {% for row in run_query(query).rows %}
        {% do elements.append({'code': row[0], 'absent_means_zero': row[1]}) %}
    {% endfor %}
    {{ return(elements) }}
{% endmacro %}
