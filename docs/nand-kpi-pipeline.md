# NAND KPI recurring data pipeline

## Objective

Financial Database v3 regularly stores comparable NAND operating KPIs from official company disclosures:

- NAND ASP change: QoQ, derived YoY, and versus comparable company guidance
- NAND bit-shipment change: QoQ, derived YoY, and versus comparable company guidance

The pipeline does not treat an undisclosed company assumption as zero and does not fill it with an analyst estimate. Missing guidance remains `not_disclosed_or_not_comparable`.

## Data flow

1. `data/financial_db/nand_kpi_sources.json` registers official IR discovery pages, allowed domains, document adapters, fiscal periods, direct source documents, and optional freshness requirements.
2. `scripts/update_nand_kpis.py` checks official pages and documents, extracts disclosed NAND statements, and updates `nand_kpi_observations.json` without deleting prior evidence.
3. Candidate selection is deterministic and independent of dictionary insertion order or URL lexical order. Previously unseen URLs are processed first; then candidates with newer `period_end`, `as_of`, or URL dates; then official-page discovery order.
4. Candidate limits remain resource guards, not silent data loss. Every URL outside the page or document limit is written to `nand_kpi_collection_state.json` with `candidate_limit`, candidate date, and prior-processing status.
5. Every fetched document stores `first_discovered_at`, `last_checked_at`, content SHA256, parse status, observation count, and retry count. Unchanged content is not reparsed.
6. Every qualitative disclosure keeps `reported_text`. A versioned normalization policy converts phrases such as “mid-single-digit” into an explicit interval and adds `normalized_qualitative_band`.
7. `scripts/build_financial_database_with_nand.py` merges the ledger into the existing `observations` schema, derives YoY by compounding four consecutive QoQ intervals, and compares actuals with same-period company guidance only when such guidance exists.
8. JSON and SQLite expose the same rows. `views.nand_kpi_comparisons` gives one comparison record per issuer and quarter.
9. Tests and the live deployment audit reject missing sources, missing original wording, unknown concepts, duplicate IDs, invalid SQLite output, absent public artifacts, stale required observations, or failure to inspect a newly discovered document.

## Candidate priority and state

The collector uses the following priority:

```text
unprocessed URL
  -> newest explicit reporting date
  -> newest date embedded in URL
  -> official page discovery order
  -> previously processed URL
```

The first 40 documents and first 20 intermediate pages after this ordering are checked. The remaining candidates are not discarded; they remain visible under `skipped_documents` or `skipped_pages` in the collection state. On the next run, an unprocessed skipped URL continues to outrank old processed documents.

A document with the same SHA256 and a prior terminal status (`parsed`, `no_kpi`, or `unchanged`) is fetched for change detection but not parsed again. A changed hash is reparsed. A newly discovered document that cannot be fetched or parsed is a fatal collection issue rather than a successful-but-stale run.

## Freshness policy

Sources may declare:

```json
{
  "require_current_observation": true,
  "max_observation_age_days": 180
}
```

For an enforced source, the newest ledger `period_end` must exist and remain within the configured age. `missing` or `stale` status is written to the collection state and stops the scheduled job. Sources without an explicit freshness contract remain `not_enforced`; this avoids asserting that companies which do not disclose comparable NAND KPIs must publish them.

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

The workflow installs `poppler-utils`, checks official sources, validates candidate priority and freshness, rebuilds Financial Database v3, runs the NAND contract tests, and commits only changed source-ledger and collection-state files. The resulting push triggers the GitHub Pages deployment.

## Public outputs

- GitHub Pages: `https://kafka2306.github.io/semiconductor-earnings-model/`
- JSON: `https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/index.json`
- SQLite: `https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/financial.db`

## Project-wide publication rule

Every delivered GitHub project must place its live GitHub Pages URL near the top of `README.md`. `scripts/check_readme_pages_link.py` converts `owner/repository` into the expected Pages URL and fails CI when the labeled link is absent.
