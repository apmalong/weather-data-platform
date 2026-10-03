-- Elements in scope: reported by a selected station during the window (inventory), defined in the
-- readme catalog, and not excluded in config. Carries each element's policy from config.
with reported as (
    select distinct inventory.element
    from {{ ref('stg_ghcnd__inventory') }} as inventory
    inner join {{ ref('int_stations__selected') }} as stations on inventory.station_id = stations.station_id
    cross join {{ ref('stg_config__run_scope') }} as scope
    where inventory.first_year <= year(scope.end_date) and inventory.last_year >= year(scope.start_date)
)

select
    elements.element,
    elements.description,
    regexp_replace(elements.description, '\s*[(\[].*$', '') as label,   -- "Maximum temperature (tenths of degrees C)"
    elements.unit,
    elements.scale,
    elements.is_core,
    coalesce(policies.absent_means_zero, false) as absent_means_zero,
    coalesce(policies.persistent, false) as persistent,   -- read in fct_station_day_element only, so not in policy_hash
    policies.fed_by,
    policies.lower_bound,
    policies.upper_bound,
    coalesce(policies.display_unit, elements.unit) as display_unit,
    coalesce(policies.display_factor, 1) as display_factor,
    md5(concat_ws(
        '|',
        elements.scale,
        coalesce(policies.absent_means_zero, false),
        policies.lower_bound,
        policies.upper_bound
    )) as policy_hash
from reported
inner join {{ ref('stg_ghcnd__elements') }} as elements
    on
        reported.element = elements.element
        and elements.is_exact_code = true
left join {{ source('config', 'elements') }} as policies on elements.element = policies.element
where coalesce(policies.excluded, false) = false
