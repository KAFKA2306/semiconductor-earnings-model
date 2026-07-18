# Semiconductor Earnings Model

SEC primary facts API -> exact quarterly selection -> deterministic fact audit -> GitHub Pages.

Public page: https://kafka2306.github.io/semiconductor-earnings-model/

## Update contract

The weekday schedule and changes to main mechanically re-fetch SEC primary facts, rebuild the static JSON API, select one unambiguous quarterly cohort, validate raw values, and republish the evidence ledger.

1. SEC EDGAR Companyfacts is fetched for the registered public entities.
2. site/public/api/v1/index.json and company/facts JSON endpoints are rebuilt.
3. Only companies with both exact registry-mapped quarterly facts in one unique largest common period enter the cohort.
4. LangGraph validates and summarizes the raw fact snapshot. It does not forecast semiconductor earnings.
5. Astro builds the /earnings/ route and GitHub Pages deploys it.

Missing data is never estimated: private xAI/OpenAI/Anthropic remain excluded, and newly public SpaceX remains listed as public but has no 10-Q XBRL facts until it files them. Companies with no exact quarterly fact are not forced into the cohort. Capex concepts are kept by reported XBRL tag and are not combined when definitions differ. This repository currently covers the SEC registry only; it is not a global semiconductor-company database.

## Local verification

```sh
uv sync
uv run python -m pytest -q
SEC_USER_AGENT='KAFKA2306/semiconductor-earnings-model contact=<real contact>' uv run python scripts/build_primary_api.py
uv run python scripts/build_model_snapshot.py
uv run python scripts/run_quant_audit.py data/quant_audit/semiconductor_latest.json --output site/public/data/quant-audit.json
cd site && npm ci && GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model npm run build
```

`SEC_USER_AGENT` is required and must identify the real operator/contact. A failed fetch, ambiguous fact selection, failed contract test, invalid snapshot, failed Astro build, or failed public smoke test stops deployment.

This is not investment advice.
