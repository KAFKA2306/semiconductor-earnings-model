# Primary Facts / Financial Research Workbench

**Live GitHub Pages:** https://kafka2306.github.io/semiconductor-earnings-model/

Primary filings and company disclosures → exact period selection → normalized concepts → transparent metrics and evaluations → peer context → GitHub Pages and reusable financial database.

## Public evidence

- [Research workbench / integrated earnings and resilience view](https://kafka2306.github.io/semiconductor-earnings-model/resilience/)
- [Financial Database v3 / normalized observations, metrics, provenance, audit, and query views](https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/index.json)
- [Financial Database v3 / SQLite](https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/financial.db)
- [Kioxia / NAND sector CapEx pre-earnings audit (2026-07-30)](docs/reports/semiconductor/2026-07-30-kioxia-nand-sector-capex.md)
- [NAND KPI recurring pipeline](docs/nand-kpi-pipeline.md)
- [Project-wide GitHub Pages publication standard](docs/project-publication-standard.md)
- [Research API v2 / facts, metrics, evaluations, peers, ontology, benchmark](https://kafka2306.github.io/semiconductor-earnings-model/api/v2/semiconductor-research/index.json)
- [Primary-facts earnings ledger](https://kafka2306.github.io/semiconductor-earnings-model/earnings/)
- [Calculation model / input → formula → intermediate value → verdict](https://kafka2306.github.io/semiconductor-earnings-model/model/)
- [Primary API index](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/index.json)
- [Semiconductor profit API / up to 20 quarters](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/semiconductor-profit/index.json)
- [Semiconductor resilience API / up to five annual periods](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/semiconductor-resilience/index.json)
- [Demand-side API / normalized five-year time series](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/demand/index.json)
- [Machine-readable financial research ontology](data/ontology/financial_research_ontology.json)
- [Financial metric and KPI catalog](data/financial_db/metric_catalog.json)
- [Reviewed non-adapter observation ledger](data/financial_db/manual_observations.json)
- [NAND industry entity registry](data/financial_db/industry_entities.json)
- [NAND KPI source registry](data/financial_db/nand_kpi_sources.json)
- [NAND KPI observation ledger](data/financial_db/nand_kpi_observations.json)
- [Financial database operating contract](docs/financial-database.md)
- [Audited earnings-platform benchmark](data/benchmark/earnings_review_sites.json)
- [GitHub Actions deployment contract](.github/workflows/pages.yml)

## Analytical routes

- `/earnings/` is the primary-facts ledger. It preserves reported revenue, operating income, OCF, CapEx, periods, XBRL tags, source filings, and directly derived values.
- `/resilience/` is the integrated research workbench. It combines quarterly growth and profitability with annual FCF, liquidity, debt, peer medians and percentiles, data-quality flags, deterministic downside scenarios, explainable evaluations, source evidence, ontology, and a benchmark against other research products.
- `/model/` is the demand-to-profit calculation boundary. It separates known inputs, formulas, intermediate values, unknown variables, and verdicts.
- `/api/v3/financial-database/` is the reusable analytical store. It combines current v1/v2 evidence with reviewed guidance, consensus, market, estimate, scenario, and NAND operating-KPI observations while keeping those value classes separate.

## Financial database model

The v3 database separates:

1. **Entity** — issuer, security identity, ticker, CIK, role, and peer group.
2. **Concept** — financial-statement item, operating KPI, guidance item, consensus item, market observation, or derived metric.
3. **Observation** — a point or range with value type, unit, period, scope, as-of date, revision, source tier, and source URL.
4. **Source** — regulatory filing, company disclosure, licensed consensus, market feed, or explicit model.
5. **Derived metric** — formula-backed values with upstream evidence.
6. **Evaluation** — rule ID, threshold, result, and supporting metrics rather than one opaque score.
7. **Evidence edge** — machine-readable lineage from calculations and evaluations back to evidence.
8. **Audit issue** — missing, stale, conflicting, malformed, or unsupported records.

Actual, company guidance, analyst consensus, internal estimate, scenario, and market observation are different semantic classes. Annual, quarterly, duration, instant, segment, consolidated, and point-in-time values are not silently mixed.

The metric catalog includes current financial statements and repeated operating analyses: cloud revenue and growth, RPO, backlog, data-center CapEx, CapEx and depreciation guidance, energy capacity, memory ASP, bit shipments, inventory days, fab utilization, wafer capacity, HBM, advanced packaging capacity, share price, market capitalization, enterprise value, forward P/E, and consensus revenue and EPS.

### NAND operating-KPI contract

NAND ASP and bit shipments are stored as explicit concepts for QoQ actuals, derived YoY, and versus comparable company guidance. Qualitative company wording is preserved in `reported_text`; numeric ranges use the versioned `qualitative-percentage-band.v1` policy. YoY is compounded from four consecutive QoQ intervals rather than summed. When a company does not disclose the same KPI for the same period as guidance, `views.nand_kpi_comparisons` reports `not_disclosed_or_not_comparable` and does not fabricate a variance.

## Existing semiconductor research model

The v2 research API deliberately separates five layers:

1. **Reported fact** — direct SEC XBRL value with tag, unit, period, accession, and filing URL.
2. **Normalized concept** — analysis concept such as revenue, operating cash flow, CapEx, cash, or retained earnings. Equivalent XBRL concepts are selected by recency and history coverage.
3. **Derived metric** — formula-backed values including FCF, margins, YoY, CAGR, volatility, liquidity ratios, and downside runway.
4. **Evaluation** — rule ID, input value, PASS/WATCH/UNKNOWN result, and threshold. A single opaque score is not used.
5. **Evidence edge** — machine-readable `derived_from` and `uses_metric` relationships that connect calculations and evaluations back to evidence.

The ontology also models analyst estimates, earnings surprises, guidance revisions, transcript statements, market-price observations, and segment KPIs. They remain unpopulated until an automated adapter or a reviewed source-backed observation is connected; the application does not fabricate them.

## Update contract

The weekday schedules and changes to `main` mechanically rebuild and validate the evidence chain.

1. SEC EDGAR Companyfacts is fetched for registered issuers.
2. Quarterly semiconductor revenue and operating income are selected without forcing incompatible fiscal periods into an index total.
3. Annual revenue, OCF, CapEx, cash, short-term investments, retained earnings, and debt are selected for up to five 10-K periods.
4. Tag migrations such as `PaymentsToAcquireProductiveAssets` are handled through explicit equivalent-concept sets and recency-aware selection.
5. Official NAND IR pages are checked twice each weekday; new source documents are discovered only on allowlisted company domains.
6. NAND disclosures preserve original wording, normalize qualitative bands, derive compounded YoY, and calculate guidance variance only when a comparable company target exists.
7. The research builder merges annual and quarterly data without treating the two period types as additive.
8. The financial database builder imports v1/v2 evidence and NAND KPI evidence, validates reviewed observations, deduplicates semantically equivalent records, and generates JSON and SQLite.
9. Peer medians and percentiles are calculated only within registered comparison groups.
10. Company classifications are derived from disclosed evaluation rules; missing data remains `unknown`.
11. Tests validate IDs, source URLs, value classes, periods, rules, NAND comparison semantics, ontology coverage, database row counts, SQLite integrity, latest-value views, and self-funding runway semantics.
12. Astro builds the static views, GitHub Pages deploys them, and the deployment job checks the live HTML SHA and all v1/v2/v3 outputs.

## Shared publication rule

Every delivered KAFKA2306 project must show its fully qualified live GitHub Pages URL near the top of `README.md`. `scripts/check_readme_pages_link.py` enforces this repository’s expected URL in CI. A source-code push without a documented and verified public endpoint is not considered complete.

## Local verification

```sh
uv sync
: "${SEC_USER_AGENT:?set SEC_USER_AGENT to identify the real operator/contact}"
uv run python scripts/build_primary_api.py
uv run python scripts/build_semiconductor_profit_api.py
uv run python scripts/build_semiconductor_resilience_api_v2.py
uv run python scripts/build_semiconductor_research_api.py
uv run python scripts/finalize_semiconductor_research_api.py
uv run python scripts/build_demand_api.py
uv run python scripts/update_nand_kpis.py --offline
uv run python scripts/build_financial_database_with_nand.py
uv run python scripts/check_readme_pages_link.py
uv run python scripts/build_model_snapshot.py
uv run python scripts/run_quant_audit.py data/quant_audit/semiconductor_latest.json --output site/public/data/quant-audit.json
uv run python -m pytest -q
npm --prefix site ci
GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model PUBLIC_BUILD_SHA=local npm --prefix site run build
```

`SEC_USER_AGENT` must identify the real operator/contact. A failed fetch, stale period, invalid ontology, malformed NAND or manual observation, missing source wording, broken evidence edge, database audit error, SQLite integrity error, missing README Pages link, failed test, invalid Astro build, or failed public smoke test stops deployment.

This is not investment advice.
