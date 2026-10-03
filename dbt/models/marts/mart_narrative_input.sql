-- The narrative pipeline's input: one fact sheet per station and day, built only from the marts.
-- Each fact carries its status, so the narrative can say "a trace of rain", "no reading" or
-- "no notable gusts" instead of guessing. Values are in display units (config elements.display).
-- input_hash fingerprints the facts: a narrative is regenerated only when its facts change
-- (a NOAA revision, a policy change), never just because the pipeline ran again.
with facts as (
    select
        cells.station_id,
        cells.obs_date,
        list(
            { 'element': cells.element, 'label': elements.label,
            -- a value only when usable; "not_reported" gusts are "none notable", not "0 km/h"
            'value': case
                when cells.status in ('valid', 'trace') then round(cells.value * elements.display_factor, 1)
            end,
            'unit': elements.display_unit,
            'status': cells.status,
            -- Direction elements (unit "degrees" in the readme catalog) get their 8-point compass
            -- point here: models converted degrees to compass points wrongly in ~1 in 8
            -- narratives (290 -> "NW"), so the conversion isn't left to them.
            'compass': case
                when elements.unit = 'degrees' and cells.status in ('valid', 'trace')
                    then ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][(round(cells.value / 45)::int % 8) + 1]
            end }
            order by elements.is_core desc, cells.element asc
        ) as facts
    from {{ ref('fct_station_day_element') }} as cells
    inner join {{ ref('dim_element') }} as elements on cells.element = elements.element
    where cells.status != 'not_expected'
    group by all
)

select
    fact_sheets.station_id,
    stations.city,
    stations.province,
    stations.station_name,
    fact_sheets.obs_date,
    to_json(fact_sheets.facts) as facts,
    md5(to_json(fact_sheets.facts)::varchar) as input_hash
from facts as fact_sheets
inner join {{ ref('dim_station') }} as stations on fact_sheets.station_id = stations.station_id
