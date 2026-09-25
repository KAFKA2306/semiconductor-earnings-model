select
    accession_number,
    company_id,
    entity_id,
    ticker,
    metric,
    concept,
    taxonomy,
    document_type,
    fiscal_year,
    fiscal_period,
    filed_date,
    period_start,
    period_end,
    duration_days,
    frame,
    unit,
    value,
    source,
    source_url,
    schema_version,
    'gold' as data_layer,
    'gold' as publication_tier
from {{ ref('silver_verified_revenue_actuals') }}
where metric = 'revenue'
  and schema_version = 'verified-revenue-actual.v1'
  and source = 'SEC Company Facts API'
  and source_url like 'https://data.sec.gov/%'
  and nullif(trim(accession_number), '') is not null
  and entity_id is not null
  and period_start is not null
  and period_end is not null
  and value is not null
  and nullif(trim(unit), '') is not null
