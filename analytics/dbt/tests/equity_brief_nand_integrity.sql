{{ config(enabled=var('equity_brief_facts', '') != '') }}

select *
from {{ ref('gold_nand_equity_brief') }}
where equity_value <= 0
   or abs(q3_profit - q3_profit_bridge) > 50000000
   or normal_annual_fcfe_required >= 'Infinity'::double
   or june11_price is null
   or june4_price is null
   or dividend is null
