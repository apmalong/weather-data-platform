-- One row per station and day, one value and one status column per in-scope element. The element
-- columns are generated from the warehouse at build time (macros/scoped_elements.sql): a station
-- that starts reporting a new element, or a new city that reports different ones, adds columns
-- without a SQL change. Values are in real units (dim_element.unit); null when unusable or missing.
{% set elements = scoped_elements() %}

select
    cells.station_id,
    stations.city,
    stations.station_name,
    cells.obs_date,
    {%- for e in elements %}
    max(cells.value) filter (where cells.element = '{{ e.code }}') as {{ e.code | lower }},
    max(cells.status) filter (where cells.element = '{{ e.code }}') as {{ e.code | lower }}_status,
    {%- endfor %}
    count(*) filter (where cells.is_core = true and cells.is_expected = true) as core_expected,
    count(*) filter (
        where cells.is_core = true and cells.is_expected = true and cells.status in ('valid', 'trace', 'not_reported')
    )
        as core_present,
    string_agg(cells.element, ', ' order by cells.element) filter (where cells.status = 'missing') as missing_elements,
    string_agg(cells.element, ', ' order by cells.element) filter (
        where cells.status in ('qc_failed', 'out_of_bounds', 'inconsistent', 'unparseable')
    )
        as quarantined_elements
from {{ ref('fct_station_day_element') }} as cells
inner join {{ ref('int_stations__selected') }} as stations on cells.station_id = stations.station_id
group by all
