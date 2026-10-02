-- The run's window and quality thresholds as one row, for joining.
select w.start_date, w.end_date, q.freshness_warn_days, q.freshness_error_days, q.volume_change_warn_pct
from {{ source('config', 'window') }} w
cross join {{ source('config', 'quality') }} q
