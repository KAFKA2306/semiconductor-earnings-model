# Semiconductor chemical-demand monthly snapshot (2026-10-15)

## Scope and current status

This is an **additive raw research snapshot**, not a replacement for `data/earnings_ledger/`, the canonical Financial Database v3, the existing SIA market-positioning feed, or dbt Gold models.

- CSV: [`data/raw/chemical_demand/monthly_20261015.csv`](../data/raw/chemical_demand/monthly_20261015.csv)
- Google Sheets review surface: [半導体実需｜月次モニター](https://docs.google.com/spreadsheets/d/1MrjTwva96oYVOsT28Z33ybytAbFRNioywquiz2eDsQE/edit)
- As of: 2026-10-15. Values are a **frozen disclosed-data snapshot**, not a live collector.
- Observations: **66 rows** (TSMC 21, UMC 21, San Fu Chemical 21, SIA/WSTS 3).
- Original supporting package contains quarterly chemical-volume and wafer-shipment data. This monthly CSV does **not** interpolate those quarterly facts.

## Meaning of each signal

| company_id | Count | Source | Scope / unit | Interpretation |
| --- | ---: | --- | --- | --- |
| TSMC | 21 | Issuer monthly revenue IR | Group revenue, TWD million | Foundry monetary activity, **not wafer units** |
| UMC | 21 | Issuer monthly revenue IR; September 2026 secondary relay | Group revenue, TWD thousand | Foundry monetary activity, **not wafer units** |
| SANFU | 21 | Secondary revenue time series; September 2026 company-disclosure relay | Group revenue, TWD thousand | Chemical-company **total revenue, not semiconductor-only chemical shipments** |
| SIA | 3 | SIA release citing WSTS | Global revenue, USD billion, trailing three-month average | **Smoothed market observation, not single-month revenue** |

**Core research question:** if short-lived fab chemicals are consumed at production speed, their *quantity shipped* may be closer to wafer-start demand than durable materials and electronic components. However, chemicals vary in shelf life, process intensity, stock buffers and fab mix. An issuer's group revenue is not itself evidence of semiconductor-grade chemical consumption.

**Known missing observation:** monthly **semiconductor-grade chemical shipment quantity = 0 disclosed rows in this snapshot**. Do not manufacture it from company revenue, divide quarterly tonnage into months, or relabel total sales as chemistry-specific quantity.

## Raw observation contract

Each record is indexed by `observation_id` and identified for comparison by `company_id + scope_id + metric_code + unit_id + observation_basis + period_id`.

- `period_id`: `YYYYMmm`, reporting month, never publication date
- `value`: the numerical amount **in the stated unit**; preserve original `TWD_mn`, `TWD_th`, `USD_bn`, do not silently convert
- `observation_basis`: `month_actual` or `trailing_3m_mean`; never mix in a YoY/MoM denominator
- `signal_tier`: `foundry_total_revenue`, `chemical_supplier_total_revenue`, or `market_smoothed_sales`
- `source_type`: `official_ir`, `official_market_data`, `secondary_market_data`, or `secondary_company_disclosure`; keep secondary provenance explicit
- `source_id`, `source_url`: trace source-level evidence for every row

SIA/WSTS is already modeled in the repository under `data/market_positioning/` with metric `monthly_sales_usd_bn_3mma`. Reconcile that feed before any canonical ingestion to avoid duplicate observations. Transformations to a public star-schema projection should be governed by the existing dbt/data-platform owners, not independent UI or Sheets calculations.

## Verification

```bash
python -m unittest tests.test_chemical_demand_monthly_snapshot
```

The focused regression test checks uniqueness, source links, monthly vs moving-average semantics, coverage counts, and the published September 2026 growth figures from like-for-like comparisons.

Next investigation: obtain monthly shipment tonnage or consumption proxies from semiconductor-grade chemical suppliers; retain product, process, geography, inventory and measurement coverage to distinguish fab starts from price/mix.
