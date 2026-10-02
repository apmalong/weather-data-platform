-- Error when any element a station reports every day is older than quality.freshness_error_days:
-- the narratives would describe stale weather. mart_data_quality warns earlier, at "lagging".
-- Elements whose absence is normal (absent_means_zero) are "not_applicable" and never stale.
select q.city, q.station_id, q.element, q.last_usable_date, q.days_since_last
from {{ ref('mart_data_quality') }} q
where q.freshness = 'stale'
