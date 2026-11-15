{{ config(enabled=var('equity_brief_facts', '') != '') }}

with f as (
    select map(list(id), list(value)) as v
    from {{ ref('silver_equity_brief_facts') }}
), assumptions as (
    select
        {{ var('equity_brief_claimed_pe', 2.5) }}::double as claimed_pe,
        {{ var('equity_brief_discount_rate', 0.1) }}::double as discount_rate,
        {{ var('equity_brief_terminal_growth', 0) }}::double as terminal_growth,
        {{ var('equity_brief_boom_quarterly_operating_cf_jpy', 0) }}
          - {{ var('equity_brief_boom_quarterly_capex_jpy', 0) }}
          - {{ var('equity_brief_boom_quarterly_extra_cash_tax_jpy', 0) }}
          - {{ var('equity_brief_boom_quarterly_incremental_working_capital_jpy', 0) }}
          + {{ var('equity_brief_boom_quarterly_net_borrowing_jpy', 0) }} as boom_fcfe,
        coalesce(
            {{ var('equity_brief_normal_annual_capex_jpy', 'null') if var('equity_brief_normal_annual_capex_jpy', 'null') is not none else 'null' }},
            f.v['full_year_capex']
        ) as normal_capex,
        {{ var('equity_brief_normal_annual_net_borrowing_jpy', 0) }} as normal_net_borrowing
    from f
), basics as (
    select
        v['close'] * (v['issued'] - v['treasury'] + v['october_shares_added']) as equity_value,
        v['q3_cumulative_profit'] - v['half_profit'] as q3_profit_bridge,
        v['q3_profit'] as q3_profit,
        v['q3_cumulative_profit'] as cumulative_profit,
        v['fy_consensus'] as consensus,
        v['previous_profit'] as previous_profit,
        v['cash'] - v['current_borrowing'] - v['long_borrowing'] - v['current_lease'] - v['long_lease'] as net_cash,
        v['tax_payable'] as tax_payable,
        v['sales_receivables_increase'] as sales_receivables_increase,
        v['operating_cf'] - v['plant_capex'] - v['intangible_capex'] as half_cash_after_capex,
        v['buyback'] as buyback,
        v['dividend_pre_split'] / v['split_factor'] as dividend,
        v['excess_return_percent'] as excess_return_percent,
        v['cayman1a_june4'] / v['split_factor'] as june4_price,
        v['cayman1a_june11'] / v['split_factor'] as june11_price,
        v['cayman2_holding'] as cayman2_holding
    from f
), metrics as (
    select
        equity_value, q3_profit_bridge, q3_profit, cumulative_profit, consensus,
        case when consensus > 0 then equity_value / consensus end as consensus_pe,
        case when cumulative_profit + q3_profit > 0 then equity_value / (cumulative_profit + q3_profit) end as flat_q4_pe,
        equity_value / claimed_pe as implied_fy_profit,
        equity_value / claimed_pe - cumulative_profit as implied_q4_profit,
        consensus - cumulative_profit as consensus_q4_profit,
        previous_profit, net_cash, tax_payable, sales_receivables_increase, half_cash_after_capex,
        buyback, dividend, excess_return_percent, june4_price, june11_price, cayman2_holding
    from basics cross join assumptions
), horizons as (
    select unnest([{{ var('equity_brief_boom_quarters', [0, 2, 4, 8, 12]) | join(', ') }}]) as quarters
), present_values as (
    select h.quarters,
        coalesce((
            select sum(a.boom_fcfe / pow(1 + a.discount_rate, t.n / 4.0))
            from range(1, h.quarters + 1) t(n)
        ), 0) as boom_pv
    from horizons h cross join assumptions a
)
select
    m.*,
    p.quarters as boom_quarters,
    p.boom_pv,
    (m.equity_value - p.boom_pv) * pow(1 + a.discount_rate, p.quarters / 4.0)
        * (a.discount_rate - a.terminal_growth) as normal_annual_fcfe_required,
    normal_annual_fcfe_required + a.normal_capex - a.normal_net_borrowing as normal_annual_ocf_required
from metrics m cross join assumptions a cross join present_values p
