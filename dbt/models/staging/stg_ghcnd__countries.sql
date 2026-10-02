select code as country_code, name as country_name
from {{ source('raw', 'countries') }}
