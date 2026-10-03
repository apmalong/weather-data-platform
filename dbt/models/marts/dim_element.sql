select
    element, label, description, unit, scale, display_unit, display_factor, is_core, absent_means_zero,
    persistent, fed_by, lower_bound, upper_bound
from {{ ref('int_elements__in_scope') }}
