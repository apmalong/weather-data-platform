-- The narrative pipeline's input: one fact sheet per station and day, built only from the marts.
-- Each fact carries its status, so the narrative can say "a trace of rain", "no reading" or
-- "no notable gusts" instead of guessing. Values are in display units (config elements.display).
-- input_hash fingerprints the facts: a narrative is regenerated only when its facts change
-- (a NOAA revision, a policy change), never just because the pipeline ran again.
with facts as (
    select
        d.station_id,
        d.obs_date,
        list(
            {'element': d.element, 'label': e.label,
             -- a value only when usable; "not_reported" gusts are "none notable", not "0 km/h"
             'value': case when d.status in ('valid', 'trace') then round(d.value * e.display_factor, 1) end,
             'unit': e.display_unit,
             'status': d.status}
            order by e.is_core desc, d.element
        ) as facts
    from {{ ref('fct_station_day_element') }} d
    join {{ ref('dim_element') }} e using (element)
    where d.status <> 'not_expected'
    group by all
)

select
    f.station_id,
    s.city,
    s.province,
    s.station_name,
    f.obs_date,
    to_json(f.facts) as facts,
    md5(to_json(f.facts)::varchar) as input_hash
from facts f
join {{ ref('dim_station') }} s using (station_id)
