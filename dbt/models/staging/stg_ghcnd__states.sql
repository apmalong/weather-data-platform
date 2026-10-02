select code as state_code, name as state_name
from {{ source('raw', 'states') }}
