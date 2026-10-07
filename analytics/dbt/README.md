# dbt Medallion analytics layer

This dbt project makes the repository's existing Medallion contract executable without moving source acquisition out of the Python pipeline.

## Ownership

- Bronze: source acquisition, raw snapshots, rejected rows, and source state remain owned by the existing Python ingestion pipeline.
- Silver: canonical ledgers remain the normalized evidence boundary. dbt reads them, normalizes analytical types, and tests keys/contracts; dbt does not rewrite canonical evidence.
- Gold: dbt builds analysis/publication-safe marts from Silver. Gold models must fail closed on provenance or verification gaps.
- dbt also owns transformation tests, analytical lineage metadata, generated docs/catalog artifacts, and CI verification for models under `analytics/dbt/`.

Current Silver inputs include both `data/canonical/*.jsonl` and the verified earnings ledger `data/earnings_ledger/verified_revenue_actuals.ndjson`.

Current Gold coverage includes:

- publication-safe CapEx projects,
- CapEx company coverage,
- verified SEC revenue actuals,
- latest annual and discrete-quarter verified revenue per US-listed entity,
- CapEx + revenue context joined by canonical `entity_id`.

The CapEx + revenue model is deliberately named **context**. It does not infer causality. It makes the evidence needed for later CapEx → capacity → revenue → EPS → valuation analysis available on one tested lineage.

## Run

From this directory:

```bash
uv run --with "dbt-duckdb==1.11.0" dbt build --profiles-dir .
uv run --with "dbt-duckdb==1.11.0" dbt docs generate --profiles-dir .
```

The generated DuckDB database and dbt artifacts are local build outputs under `target/`; they are not sources of truth.

## Design rule

Do not put source fetching, spreadsheet import, source verification, or canonical identity generation in dbt. Those belong upstream.

Do not make UI, API, Google Sheets, or BI layers independently reimplement transformation logic that belongs in Gold. Consumers should use canonical services or tested Gold marts according to the repository contract.

A dbt failure must fail the affected analytical publication path closed. It must not be "fixed" by weakening provenance, unit, period, or source requirements.
