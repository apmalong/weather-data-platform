-- The run's window and quality thresholds as one row, for joining.
select
    run_window.start_date,
    run_window.end_date,
    quality.freshness_warn_days,
    quality.freshness_error_days,
    quality.volume_change_warn_pct
from {{ source('config', 'window') }} as run_window
cross join {{ source('config', 'quality') }} as quality
