-- Elements in scope: reported by a selected station during the window (inventory), defined in the
-- readme catalog, and not excluded in config. Carries each element's policy from config.
with reported as (
    select distinct i.element
    from {{ ref('stg_ghcnd__inventory') }} i
    join {{ ref('int_stations__selected') }} s using (station_id)
    cross join {{ ref('stg_config__run_scope') }} w
    where i.first_year <= year(w.end_date) and i.last_year >= year(w.start_date)
)

select
    e.element,
    e.description,
    e.unit,
    e.scale,
    e.is_core,
    coalesce(p.absent_means_zero, false) as absent_means_zero,
    p.lower_bound,
    p.upper_bound,
    md5(concat_ws('|', e.scale, coalesce(p.absent_means_zero, false), p.lower_bound, p.upper_bound)) as policy_hash
from reported r
join {{ ref('stg_ghcnd__elements') }} e on e.element = r.element and e.is_exact_code
left join {{ source('config', 'elements') }} p on p.element = e.element
where not coalesce(p.excluded, false)
