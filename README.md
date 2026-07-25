# Primary Facts / Semiconductor Research Workbench

SEC primary facts → exact quarterly and annual selection → normalized concepts → transparent metrics and evaluations → peer context → GitHub Pages.

## Public evidence

- [Research workbench / integrated earnings and resilience view](https://kafka2306.github.io/semiconductor-earnings-model/resilience/)
- [Research API v2 / facts, metrics, evaluations, peers, ontology, benchmark](https://kafka2306.github.io/semiconductor-earnings-model/api/v2/semiconductor-research/index.json)
- [Primary-facts earnings ledger](https://kafka2306.github.io/semiconductor-earnings-model/earnings/)
- [Calculation model / input → formula → intermediate value → verdict](https://kafka2306.github.io/semiconductor-earnings-model/model/)
- [Primary API index](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/index.json)
- [Semiconductor profit API / up to 20 quarters](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/semiconductor-profit/index.json)
- [Semiconductor resilience API / up to five annual periods](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/semiconductor-resilience/index.json)
- [Demand-side API / normalized five-year time series](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/demand/index.json)
- [Machine-readable financial research ontology](data/ontology/financial_research_ontology.json)
- [Audited earnings-platform benchmark](data/benchmark/earnings_review_sites.json)
- [GitHub Actions deployment contract](.github/workflows/pages.yml)

## Analytical routes

- `/earnings/` is the primary-facts ledger. It preserves reported revenue, operating income, OCF, CapEx, periods, XBRL tags, source filings, and directly derived values.
- `/resilience/` is the integrated research workbench. It combines quarterly growth and profitability with annual FCF, liquidity, debt, peer medians and percentiles, data-quality flags, deterministic downside scenarios, explainable evaluations, source evidence, ontology, and a benchmark against other research products.
- `/model/` is the demand-to-profit calculation boundary. It separates known inputs, formulas, intermediate values, unknown variables, and verdicts.

## Research data model

The v2 API deliberately separates five layers:

1. **Reported fact** — direct SEC XBRL value with tag, unit, period, accession, and filing URL.
2. **Normalized concept** — analysis concept such as revenue, operating cash flow, CapEx, cash, or retained earnings. Equivalent XBRL concepts are selected by recency and history coverage.
3. **Derived metric** — formula-backed values including FCF, margins, YoY, CAGR, volatility, liquidity ratios, and downside runway.
4. **Evaluation** — rule ID, input value, PASS/WATCH/UNKNOWN result, and threshold. A single opaque score is not used.
5. **Evidence edge** — machine-readable `derived_from` and `uses_metric` relationships that connect calculations and evaluations back to evidence.

The ontology also models analyst estimates, earnings surprises, guidance revisions, transcript statements, market-price observations, and segment KPIs as unsupported entity types. They remain explicitly unpopulated until reliable data sources are connected; the application does not fabricate them.

## Update contract

The weekday schedule and changes to `main` mechanically rebuild and validate the evidence chain.

1. SEC EDGAR Companyfacts is fetched for registered issuers.
2. Quarterly semiconductor revenue and operating income are selected without forcing incompatible fiscal periods into an index total.
3. Annual revenue, OCF, CapEx, cash, short-term investments, retained earnings, and debt are selected for up to five 10-K periods.
4. Tag migrations such as `PaymentsToAcquireProductiveAssets` are handled through explicit equivalent-concept sets and recency-aware selection.
5. The research builder merges annual and quarterly data without treating the two period types as additive.
6. Peer medians and percentiles are calculated only within the registered semiconductor or semiconductor-equipment group.
7. Company classifications are derived from disclosed evaluation rules; missing data remains `unknown`.
8. The normalized database publishes issuers, reported facts, derived metrics, evaluations, and evidence edges.
9. Tests validate IDs, source URLs, rules, ontology coverage, benchmark references, latest reporting periods, and self-funding runway semantics.
10. Astro builds the static views, GitHub Pages deploys them, and the deployment job checks the live HTML SHA against both v1 and v2 API hashes.

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
uv run python scripts/build_model_snapshot.py
uv run python scripts/run_quant_audit.py data/quant_audit/semiconductor_latest.json --output site/public/data/quant-audit.json
uv run python -m pytest -q
npm --prefix site ci
GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model PUBLIC_BUILD_SHA=local npm --prefix site run build
```

`SEC_USER_AGENT` must identify the real operator/contact. A failed fetch, stale period, invalid ontology, broken evidence edge, failed test, invalid Astro build, or failed public smoke test stops deployment.

This is not investment advice.
