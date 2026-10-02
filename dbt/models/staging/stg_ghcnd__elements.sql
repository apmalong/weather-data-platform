-- The readme's element catalog. Pattern codes (WT**, SN*#) describe element families; only exact
-- codes can match observations.
select
    code as element,
    description,
    unit,
    scale,
    core as is_core,
    not regexp_matches(code, '[*#]') as is_exact_code
from {{ source('raw', 'element_catalog') }}
