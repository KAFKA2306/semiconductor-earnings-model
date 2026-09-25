with annual as (
    select *
    from {{ ref('gold_verified_revenue_actuals') }}
    where fiscal_period = 'FY'
      and duration_days between 330 and 380
    qualify row_number() over (
        partition by entity_id
        order by period_end desc, filed_date desc, accession_number desc
    ) = 1
),
quarterly as (
    select *
    from {{ ref('gold_verified_revenue_actuals') }}
    where fiscal_period like 'Q%'
      and duration_days between 70 and 110
    qualify row_number() over (
        partition by entity_id
        order by period_end desc, filed_date desc, accession_number desc
    ) = 1
)
select
    coalesce(annual.entity_id, quarterly.entity_id) as entity_id,
    coalesce(annual.ticker, quarterly.ticker) as ticker,
    annual.period_end as latest_annual_period_end,
    annual.fiscal_year as latest_annual_fiscal_year,
    annual.value as latest_annual_revenue,
    annual.unit as latest_annual_revenue_unit,
    annual.source_url as latest_annual_source_url,
    quarterly.period_end as latest_quarter_period_end,
    quarterly.fiscal_year as latest_quarter_fiscal_year,
    quarterly.fiscal_period as latest_quarter_fiscal_period,
    quarterly.value as latest_quarter_revenue,
    quarterly.unit as latest_quarter_revenue_unit,
    quarterly.source_url as latest_quarter_source_url,
    'gold' as data_layer,
    'gold' as publication_tier
from annual
full outer join quarterly using (entity_id)
