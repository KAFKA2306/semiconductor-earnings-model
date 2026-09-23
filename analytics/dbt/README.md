# dbt Medallion analytics layer

This dbt project makes the repository's existing Medallion contract executable without moving source acquisition out of the Python pipeline.

## Ownership

- Bronze: source acquisition, raw snapshots, rejected rows, and source state remain owned by the existing Python ingestion pipeline.
- Silver: `data/canonical/*.jsonl` remains the canonical normalized boundary. dbt reads it and tests keys/contracts; dbt does not rewrite it.
- Gold: dbt builds analysis/publication-safe marts from Silver. Gold models must fail closed on provenance or verification gaps.

The first Gold mart intentionally promotes only `quality_flag = primary_source_extracted` CapEx rows with both `source_doc_id` and `source_url`.

## Run

From this directory:

```bash
uv run --with "dbt-duckdb==1.11.0" dbt build --profiles-dir .
```

The generated DuckDB database is local build output under `target/`; it is not a source of truth.

## Design rule

Do not put source fetching, spreadsheet import, or canonical identity generation in dbt. Those belong upstream. Do not make UI, API, or Google Sheets calculate business facts independently. They consume Gold or canonical services according to the repository contract.
