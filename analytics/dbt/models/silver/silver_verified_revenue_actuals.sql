select
    accession_number,
    company_id,
    case
        when nullif(trim(ticker), '') is null then null
        else 'US:' || upper(trim(ticker))
    end as entity_id,
    upper(trim(ticker)) as ticker,
    metric,
    concept,
    taxonomy,
    document_type,
    try_cast(fiscal_year as integer) as fiscal_year,
    fiscal_period,
    try_cast(filed as date) as filed_date,
    try_cast(period_start as date) as period_start,
    try_cast(period_end as date) as period_end,
    try_cast(duration_days as integer) as duration_days,
    frame,
    unit,
    try_cast(value as decimal(38, 4)) as value,
    source,
    source_url,
    schema_version,
    'silver' as data_layer
from read_ndjson('{{ var("repo_root") }}/data/earnings_ledger/verified_revenue_actuals.ndjson')
