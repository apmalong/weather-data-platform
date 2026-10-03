-- Error when any element a station reports every day is older than quality.freshness_error_days:
-- the narratives would describe stale weather. mart_data_quality warns earlier, at "lagging".
-- Elements whose absence is normal (absent_means_zero) are "not_applicable" and never stale.
select
    city,
    station_id,
    element,
    last_usable_date,
    days_since_last
from {{ ref('mart_data_quality') }}
where freshness = 'stale'
