# Japan national hydrofluoric-acid monthly quantity (secondary evidence)

## Purpose
This is a **non-canonical research snapshot** of reported METI Current Survey of Production figures **reprinted by a third party**. It is a separate series from Stella Chemifa's company-specific semiconductor-grade high-purity HF quarterly quantities and from `monthly_20261015.csv` (company-wide sales revenue). No dbt Gold / earnings-ledger / API ingestion is authorized from this snapshot.

## Source and status
- Secondary numerical source (as read 2026-10-16): https://www.am-consulting.co.jp/econ-jpn-seisan-doutai-toukei
- METI/e-Stat official dataset listing: https://www.e-stat.go.jp/stat-search/files?layout=dataset&toukei=00550200&tstat=000001022932
- METI survey item specifies nationwide 50% concentration equivalent with no semiconductor-only split.
- **Verification status: SECONDARY_ONLY_NOT_PRIMARY_VERIFIED** for every observation.
- Official August 2026 final-statistics release calendar: https://www.e-stat.go.jp/release-calendar?endDay=31&endMonth=10&endYear=2026&startDay=2&startMonth=10&startYear=2026 (released 2026-10-15 13:30 JST).
- No verified August 2026 *numeric* row. Missing values are omitted, not zero-filled.
- 2026 Apr–Jul: production, sales and month-end inventory (each in tonnes); 12 observations total. Values are transcribed from a secondary reproduction of a government dataset, **not independently checked against original Excel**.

## Limitations
- Not semiconductor-grade or issuer-specific: includes all uses, and differs in concentration / product scope from 4109's high-purity HF series.
- National production minus sales is **not** simply change in month-end inventories: self-consumption, receipts, other shipment categories and reporting population affect the balance.
- Sales quantity is not direct wafer-fab consumption or proof of demand from AI/memory production.
- Do not imply current latest government month is July. **July is only the latest month where values were independently transcribed from the available secondary page.** August's government release exists but numbers are not verified in this snapshot.
- No interpolation, percentage synthesis replacing actual tonnes, or unsupported cross-series addition.

## Tests
```bash
python -m unittest tests.test_national_hf_monthly
```

Companion Google Sheets read-only display: https://docs.google.com/spreadsheets/d/1MrjTwva96oYVOsT28Z33ybytAbFRNioywquiz2eDsQE/edit
