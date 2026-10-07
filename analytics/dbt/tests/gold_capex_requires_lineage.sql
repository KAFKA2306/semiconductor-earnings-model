select *
from {{ ref('gold_capex_projects') }}
where quality_flag <> 'primary_source_extracted'
   or source_doc_id is null
   or trim(source_doc_id) = ''
   or source_url is null
   or trim(source_url) = ''
