# Primary Facts / Semiconductor Infrastructure Ledger

SEC primary facts API → exact quarterly selection → deterministic fact audit → GitHub Pages.

Public evidence:

- GitHub Pages: [https://kafka2306.github.io/semiconductor-earnings-model/earnings/](https://kafka2306.github.io/semiconductor-earnings-model/earnings/)
- [Evidence ledger](https://kafka2306.github.io/semiconductor-earnings-model/earnings/)
- [Calculation model / input → formula → intermediate value → verdict](https://kafka2306.github.io/semiconductor-earnings-model/model/)
- [Primary API index](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/index.json)
- [All primary facts](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/facts.json)
- [Semiconductor profit API / 5-year time series](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/semiconductor-profit/index.json)
- [Demand-side API / normalized 5-year time series](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/demand/index.json)
- [Quant audit JSON](https://kafka2306.github.io/semiconductor-earnings-model/data/quant-audit.json)
- [Semiconductor issuer registry](data/primary/semiconductor_entities.json)
- [GitHub Actions workflow](https://github.com/KAFKA2306/semiconductor-earnings-model/actions/workflows/pages.yml)
- [Main branch history](https://github.com/KAFKA2306/semiconductor-earnings-model/commits/main)

The Pages site has two deliberately separate routes:

- `/earnings/` is the primary-facts ledger. It shows reported revenue, operating income, operating cash flow, CapEx, periods, XBRL tags, and directly derived values such as FCF. It does not forecast earnings or invent an index total.
- `/model/` is the calculation boundary. It places inputs, formulas, intermediate values, unknown variables, and the verdict in that order. The current state is derived as `一部成立`: the observed customer-funding → semiconductor-profit chain is established from the registered periods, while the forward calculation stops at `未計算` because external funding, semiconductor allocation, investment lag, index weights, and future margin inputs are not registered as primary facts.

## Update contract

The weekday schedule and changes to main mechanically re-fetch SEC primary facts, rebuild the static JSON APIs, validate raw values, and republish the evidence ledger.

1. [SEC EDGAR Companyfacts](https://www.sec.gov/edgar/sec-api-documentation) is fetched for the registered public entities listed in [`data/primary/entities.json`](data/primary/entities.json).
2. [`site/public/api/v1/index.json`](site/public/api/v1/index.json), [`site/public/api/v1/facts.json`](site/public/api/v1/facts.json), and the [company JSON endpoints](site/public/api/v1/companies/) are rebuilt.
3. Only companies with both exact registry-mapped quarterly facts in one unique largest common period enter the cohort.
4. [`semiconductor-profit/index.json`](site/public/api/v1/semiconductor-profit/index.json) stores up to 20 quarters of directly reported SEC revenue and operating income for the registered semiconductor issuers in [`data/primary/semiconductor_entities.json`](data/primary/semiconductor_entities.json).
5. The profit API preserves `ambiguous` or `no_common_period` cohorts. It never invents an index-level profit total when fiscal periods do not line up, and it does not infer SOX weights.
6. [`demand/index.json`](site/public/api/v1/demand/index.json) stores up to 20 quarters of hyper-scaler and data-center OCF/CapEx facts. Direct quarterly values are preferred; when only same-tag YTD or annual facts exist, the API exposes their reported-period difference as `derived_from_reported_periods` with both source facts retained.
7. Demand bars use a within-company shared absolute maximum normalization. Raw USD values, source tags, and source filings remain available; normalization is display-only and is not a cross-company aggregate.
8. [LangGraph](src/quant_audit_graph.py) validates and summarizes [`data/quant_audit/semiconductor_latest.json`](data/quant_audit/semiconductor_latest.json). It does not forecast semiconductor earnings.
9. [Astro](site/src/pages/earnings.astro) builds the `/earnings/` route and [GitHub Pages](.github/workflows/pages.yml) deploys it.

Missing data is never estimated: private xAI/OpenAI/Anthropic remain excluded, and newly public SpaceX remains listed as public but has no 10-Q XBRL facts until it files them. Companies with no exact quarterly fact are not forced into a cohort or chart. Capex concepts are kept by reported XBRL tag and are not combined when definitions differ. The central test is funding capacity → data-center investment → semiconductor revenue → semiconductor operating income. Unstarted leases, debt capacity, purchase commitments, AI revenue, guidance, and financing terms are not inferred by the current API. The SOX target is a reference index; the displayed time view is a bottom-up issuer ledger, not a reconstructed index earnings series. This repository currently covers the SEC registry only; it is not a global semiconductor-company database.

## Local verification

```sh
uv sync
uv run python -m pytest -q
: "${SEC_USER_AGENT:?set SEC_USER_AGENT to identify the real operator/contact}"
uv run python scripts/build_model_snapshot.py
uv run python scripts/run_quant_audit.py data/quant_audit/semiconductor_latest.json --output site/public/data/quant-audit.json
uv run python scripts/build_semiconductor_profit_api.py
uv run python scripts/build_demand_api.py
npm --prefix site ci
GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model npm --prefix site run build
```

`SEC_USER_AGENT` is required and must identify the real operator/contact. A failed fetch, ambiguous fact selection, failed contract test, invalid snapshot, failed Astro build, or failed public smoke test stops deployment.

This is not investment advice.
