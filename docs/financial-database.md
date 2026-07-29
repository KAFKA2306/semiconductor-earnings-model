# Financial Database v3

## Purpose

This repository is the reusable evidence base for recurring earnings, balance-sheet, cash-flow, CapEx, AI-infrastructure, semiconductor-cycle, valuation, and downside-resilience questions.

The database is not a single spreadsheet and does not treat every number as equivalent. It preserves the semantic boundary between:

- reported actuals
- company guidance
- analyst consensus
- internal estimates
- scenarios
- market observations

## Public outputs

- JSON: `/api/v3/financial-database/index.json`
- SQLite: `/api/v3/financial-database/financial.db`

JSON is optimized for inspection, citations, and static clients. SQLite is optimized for repeated analytical queries.

## Canonical tables

| Table | Role |
|---|---|
| `entities` | Issuers, tickers, CIKs, roles, peer groups, and availability |
| `concepts` | Financial statements, operating KPIs, guidance, consensus, and market concepts |
| `observations` | Source-traceable values with period, scope, value type, revision, and provenance |
| `sources` | Regulatory filings, company materials, licensed consensus, market feeds, and models |
| `metrics` | Formula-backed derived values |
| `evaluations` | Explicit rules and results rather than opaque scores |
| `evidence_edges` | Lineage from calculations and evaluations back to evidence |
| `audit_issues` | Missing, stale, conflicting, or invalid records |

## Required observation semantics

Every observation identifies:

- `entity_id`
- `concept_id`
- `value_type`
- point value or range
- unit and currency
- reporting period and period type
- consolidated, segment, or geographic scope
- `as_of` date and revision
- source tier and HTTPS source URL

Annual, quarterly, duration, instant, segment, consolidated, actual, estimate, guidance, scenario, and market values are never silently merged.

## Supported recurring analyses

The generated query views define five default routes:

1. `latest_company_snapshot` — latest actuals, derived metrics, and evaluations.
2. `earnings_comparison` — YoY, QoQ, guidance, consensus, and prior-estimate comparisons when those value classes exist.
3. `capex_roi_review` — CapEx, OCF, FCF, revenue, depreciation, and remaining performance obligations.
4. `semiconductor_cycle_review` — revenue, margins, inventory, ASP, bit shipments, utilization, and backlog.
5. `downside_resilience` — liquid reserve, debt, FCF, scenarios, and explicit evaluation rules.

## Adding data

Automated adapters populate direct primary facts. Values that do not yet have an adapter are added to `data/financial_db/manual_observations.json` only after source review.

Rules:

- Never enter values from memory.
- Never use an uncited secondary summary as the quantitative source.
- Preserve guidance ranges rather than inventing midpoints.
- Record consensus provider and observation timestamp.
- Record model ID, assumptions, formula, and evidence IDs for internal estimates and scenarios.
- Correct records with `supersedes_id`; do not erase history silently.

## Audit gate

`scripts/build_financial_database.py` generates JSON and SQLite and fails when it finds a missing source URL, unknown entity, invalid semantic class, malformed date, invalid manual record, duplicate ID, or SQLite integrity error.

Tests additionally require:

- JSON and SQLite row-count parity
- unique observation IDs
- allowed value and source classes
- source traceability
- stable latest-value views
- published API and database availability after deployment

Warnings identify stale or missing public-company coverage and catalog gaps without fabricating replacement values.
