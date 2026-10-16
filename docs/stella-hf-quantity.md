# Semiconductor chemical shipments: Stella Chemifa high-purity HF

## Scope and evidence

This is a separate source-tracked physical-quantity dataset. `data/raw/chemical_demand/monthly_20261015.csv` contains **revenue proxies**, not chemical shipment volume. Do not reinterpret that dataset or `data/earnings_ledger/`.

- Raw data: [`data/raw/chemical_demand/stella_hf_quantity_20261016.csv`](../data/raw/chemical_demand/stella_hf_quantity_20261016.csv)
- Spreadsheet: https://docs.google.com/spreadsheets/d/1MrjTwva96oYVOsT28Z33ybytAbFRNioywquiz2eDsQE/edit
- Issuer: Stella Chemifa (4109), product: **high-purity hydrofluoric acid for semiconductors**, reporting units **metric tonnes**.
- Reporting grain: `quarter` or `fiscal_year`, both explicitly stored. No monthly allocation, no interpolation.
- Direct reported quarterly values: 2025 Apr–Jun 18,500 t, 2025 Oct–Dec 18,300 t, 2026 Apr–Jun 18,700 t.
- Derived quarterly values: 2025 Jul–Sep = first-half 36,900 minus first-quarter 18,500 = **18,400 t**; 2026 Jan–Mar = FY total 73,800 minus first-three-quarter cumulative 55,200 = **18,600 t**.
- FY ending March 2026 total: **73,800 t**. Sum of its four quarters must equal 73,800 t.
- Year-over-year for Apr–Jun 2026 vs Apr–Jun 2025: **+1.081081%** calculated from comparable tonnage.

## Limitations

- **No verified company-specific monthly shipment quantities**. The spreadsheet's month-by-month company-wide revenue is a different metric and must not be mixed with tonnes.
- METI Japan-wide hydrofluoric-acid statistics use a 50%-concentration equivalent and include non-semiconductor applications. They cannot be merged into this issuer/product series; actual monthly values are not present in this dataset.
- Supplier shipments are not the same as wafer starts or downstream consumption; customer inventory movements can still produce temporary differences. The 2025 Aug 7 issuer deck mentions inventory accumulation for certain products in connection with tariffs, though it does not establish it as the principal semiconductor-HF driver.
- Product composition, geography, manufacturing processes and chip types matter; do not attribute physical-quantity changes to AI memory demand without matched evidence.
- Derived differences are calculated from **official disclosed cumulative totals**, not guessed months. Snapshot frozen as of 2026-10-16.

## Verification

```bash
python -m unittest tests.test_stella_hf_quantity
```

Authoritative issuer source PDFs, page 10:
- https://www.stella-chemifa.co.jp/ir/material/files/IG_20250807.pdf
- https://www.stella-chemifa.co.jp/ir/material/files/IG_20251113.pdf
- https://www.stella-chemifa.co.jp/ir/material/files/IG_2026.02.12.pdf
- https://www.stella-chemifa.co.jp/files/IG_20260514.pdf
- https://www.stella-chemifa.co.jp/ir/material/files/IG_20260806.pdf
