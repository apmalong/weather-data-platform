select
    id as station_id,
    element,
    try_cast(first_year as integer) as first_year,
    try_cast(last_year as integer) as last_year
from {{ source('raw', 'inventory') }}
