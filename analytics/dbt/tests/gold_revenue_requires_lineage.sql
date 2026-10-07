select *
from {{ ref('gold_verified_revenue_actuals') }}
where source <> 'SEC Company Facts API'
   or source_url not like 'https://data.sec.gov/%'
   or nullif(trim(accession_number), '') is null
   or entity_id is null
   or period_start is null
   or period_end is null
   or value is null
   or nullif(trim(unit), '') is null
