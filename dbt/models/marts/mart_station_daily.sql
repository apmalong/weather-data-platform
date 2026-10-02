-- One row per station and day, one value and one status column per in-scope element. The element
-- columns are generated from the warehouse at build time (macros/scoped_elements.sql): a station
-- that starts reporting a new element, or a new city that reports different ones, adds columns
-- without a SQL change. Values are in real units (dim_element.unit); null when unusable or missing.
{% set elements = scoped_elements() %}

select
    d.station_id,
    s.city,
    s.station_name,
    d.obs_date,
    {%- for e in elements %}
    max(d.value) filter (where d.element = '{{ e.code }}') as {{ e.code | lower }},
    max(d.status) filter (where d.element = '{{ e.code }}') as {{ e.code | lower }}_status,
    {%- endfor %}
    count(*) filter (where d.is_core and d.is_expected) as core_expected,
    count(*) filter (where d.is_core and d.is_expected and d.status in ('valid', 'trace', 'not_reported'))
        as core_present,
    string_agg(d.element, ', ' order by d.element) filter (where d.status = 'missing') as missing_elements,
    string_agg(d.element, ', ' order by d.element) filter (where d.status in ('qc_failed', 'out_of_bounds', 'unparseable'))
        as quarantined_elements
from {{ ref('fct_station_day_element') }} d
join {{ ref('int_stations__selected') }} s using (station_id)
group by all
