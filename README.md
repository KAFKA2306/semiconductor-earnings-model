# Primary Facts / Semiconductor Infrastructure Ledger

SEC primary facts API → exact quarterly selection → deterministic fact audit → GitHub Pages.

Public evidence:

- GitHub Pages: [https://kafka2306.github.io/semiconductor-earnings-model/earnings/](https://kafka2306.github.io/semiconductor-earnings-model/earnings/)
- [Evidence ledger](https://kafka2306.github.io/semiconductor-earnings-model/earnings/)
- [Primary API index](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/index.json)
- [All primary facts](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/facts.json)
- [Quant audit JSON](https://kafka2306.github.io/semiconductor-earnings-model/data/quant-audit.json)
- [GitHub Actions workflow](https://github.com/KAFKA2306/semiconductor-earnings-model/actions/workflows/pages.yml)
- [Main branch history](https://github.com/KAFKA2306/semiconductor-earnings-model/commits/main)

## Update contract

The weekday schedule and changes to main mechanically re-fetch SEC primary facts, rebuild the static JSON API, select one unambiguous quarterly cohort, validate raw values, and republish the evidence ledger.

1. [SEC EDGAR Companyfacts](https://www.sec.gov/edgar/sec-api-documentation) is fetched for the registered public entities listed in [`data/primary/entities.json`](data/primary/entities.json).
2. [`site/public/api/v1/index.json`](site/public/api/v1/index.json), [`site/public/api/v1/facts.json`](site/public/api/v1/facts.json), and the [company JSON endpoints](site/public/api/v1/companies/) are rebuilt.
3. Only companies with both exact registry-mapped quarterly facts in one unique largest common period enter the cohort.
4. [LangGraph](src/quant_audit_graph.py) validates and summarizes [`data/quant_audit/semiconductor_latest.json`](data/quant_audit/semiconductor_latest.json). It does not forecast semiconductor earnings.
5. [Astro](site/src/pages/earnings.astro) builds the `/earnings/` route and [GitHub Pages](.github/workflows/pages.yml) deploys it.

Missing data is never estimated: private xAI/OpenAI/Anthropic remain excluded, and newly public SpaceX remains listed as public but has no 10-Q XBRL facts until it files them. Companies with no exact quarterly fact are not forced into the cohort. Capex concepts are kept by reported XBRL tag and are not combined when definitions differ. This repository currently covers the SEC registry only; it is not a global semiconductor-company database.

## Local verification

```sh
uv sync
uv run python -m pytest -q
: "${SEC_USER_AGENT:?set SEC_USER_AGENT to identify the real operator/contact}"
uv run python scripts/build_model_snapshot.py
uv run python scripts/run_quant_audit.py data/quant_audit/semiconductor_latest.json --output site/public/data/quant-audit.json
npm --prefix site ci
GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model npm --prefix site run build
```

`SEC_USER_AGENT` is required and must identify the real operator/contact. A failed fetch, ambiguous fact selection, failed contract test, invalid snapshot, failed Astro build, or failed public smoke test stops deployment.

This is not investment advice.
