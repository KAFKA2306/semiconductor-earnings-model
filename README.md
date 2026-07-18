# Semiconductor Earnings Model

SEC primary facts API -> same-period selection -> deterministic LangGraph calculation -> audit gate -> GitHub Pages.

Public page: https://kafka2306.github.io/semiconductor-earnings-model/

## Update contract

The weekday schedule and changes to main mechanically re-fetch SEC primary facts, rebuild the static JSON API, select the largest same-period group, recalculate the graph, and republish the model.

1. SEC EDGAR Companyfacts is fetched for the registered public entities.
2. site/public/api/v1/index.json and company/facts JSON endpoints are rebuilt.
3. Only companies with both reported facts in the largest common period enter the aggregate.
4. LangGraph recalculates site/public/data/quant-audit.json.
5. Astro builds the /earnings/ route and GitHub Pages deploys it.

Missing data is never estimated: private xAI/OpenAI/Anthropic remain excluded, and newly public SpaceX remains listed as public but has no 10-Q XBRL facts until it files them. Oracle's latest report is cumulative rather than the selected quarter; Digital Realty has no selected standard capex fact. The API exposes these states instead of forcing them into the sum. Yardeni consensus is secondary information; beta and investment lag are not estimated.

## Local verification

```sh
uv sync
uv run python -m pytest -q
uv run python scripts/build_primary_api.py
uv run python scripts/build_model_snapshot.py
uv run python scripts/run_quant_audit.py data/quant_audit/semiconductor_latest.json --output site/public/data/quant-audit.json
cd site && npm ci && GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model npm run build
```

`SEC_USER_AGENT` is optional locally and can be supplied as a repository variable for Actions. A failed fetch, failed contract test, invalid snapshot, or failed Astro build stops deployment.

This is not investment advice.
