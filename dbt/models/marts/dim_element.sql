select element, description, unit, scale, is_core, absent_means_zero, lower_bound, upper_bound
from {{ ref('int_elements__in_scope') }}
