# NAND KPI recurring data pipeline

## Objective

Financial Database v3 regularly stores comparable NAND operating KPIs from official company disclosures:

- NAND ASP change: QoQ, derived YoY, and versus comparable company guidance
- NAND bit-shipment change: QoQ, derived YoY, and versus comparable company guidance

The pipeline does not treat an undisclosed company assumption as zero and does not fill it with an analyst estimate. Missing guidance remains `not_disclosed_or_not_comparable`.

## Data flow

1. `data/financial_db/nand_kpi_sources.json` registers official IR discovery pages, allowed domains, document adapters, fiscal periods, and direct source documents.
2. `scripts/update_nand_kpis.py` checks official pages and documents, extracts disclosed NAND statements, and updates `nand_kpi_observations.json` without deleting prior evidence.
3. Every qualitative disclosure keeps `reported_text`. A versioned normalization policy converts phrases such as “mid-single-digit” into an explicit interval and adds `normalized_qualitative_band`.
4. `scripts/build_financial_database_with_nand.py` merges the ledger into the existing `observations` schema, derives YoY by compounding four consecutive QoQ intervals, and compares actuals with same-period company guidance only when such guidance exists.
5. JSON and SQLite expose the same rows. `views.nand_kpi_comparisons` gives one comparison record per issuer and quarter.
6. Tests and the live deployment audit reject missing sources, missing original wording, unknown concepts, duplicate IDs, invalid SQLite output, or absent public artifacts.

## Source classes

| Class | Meaning |
|---|---|
| `actual` | Company-reported result. A qualitative band may be normalized, but the original wording is preserved. |
| `company_guidance` | A company target for the same KPI, scope, and period. |
| `internal_estimate` | Deterministic YoY compounding or actual-versus-guidance calculation with evidence IDs. |

Company guidance is not inferred from general market commentary, annual industry forecasts, revenue guidance, or analyst consensus.

## Interval normalization policy

The initial policy is `qualitative-percentage-band.v1`:

- low / mid / high single digit: 1–3% / 4–6% / 7–9%
- low / mid / high teens: 11–13% / 14–16% / 17–19%
- low / mid / high `N0s`: `N1–N3%` / `N4–N6%` / `N7–N9%`
- an approximate point value receives a ±0.5 percentage-point interval

This is a machine normalization convention, not an assertion that the company disclosed the interval endpoints.

## Schedule

`.github/workflows/nand-kpi-update.yml` runs twice on weekdays:

- 07:00 JST
- 16:00 JST

The workflow installs `poppler-utils`, checks official sources, validates the ledger, rebuilds Financial Database v3, runs the NAND contract tests, and commits only changed source-ledger and collection-state files. The resulting push triggers the GitHub Pages deployment.

## Public outputs

- GitHub Pages: `https://kafka2306.github.io/semiconductor-earnings-model/`
- JSON: `https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/index.json`
- SQLite: `https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/financial.db`

## Project-wide publication rule

Every delivered GitHub project must place its live GitHub Pages URL near the top of `README.md`. `scripts/check_readme_pages_link.py` converts `owner/repository` into the expected Pages URL and fails CI when the labeled link is absent.
