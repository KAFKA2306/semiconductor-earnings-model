# Central data lake

## Contract

`KAFKA2306/semiconductor-earnings-model` is the sole authenticated writer to the private Hugging Face Storage Bucket `k4fka/kafka-data-lake`.

Consumer/source repositories do not receive `HF_TOKEN`, do not register their own Hugging Face Trusted Publisher, and do not write directly to the private bucket. New public `KAFKA2306/*` sources are added only through the central allow-list or an explicitly owned central publisher path, so they create no Hugging Face setup work.

The sole writer is `.github/workflows/hf-bucket-smoke.yml`. The established workflow path is retained to avoid changing the already-proven OIDC boundary. It uses GitHub OIDC with `HF_OIDC_RESOURCE=buckets/k4fka/kafka-data-lake`; no long-lived Hugging Face token is stored.

Primary references:

- https://huggingface.co/docs/hub/en/trusted-publishers
- https://huggingface.co/docs/hub/storage-buckets
- https://docs.github.com/en/actions/reference/security/oidc

## Authentication boundary

Hugging Face authentication exists only in the central publisher. External source repositories are read with anonymous HTTPS `git clone` from their `main` branch.

The clone command disables Git credential helpers and interactive credential prompts. `actions/checkout` also runs with `persist-credentials: false`. Therefore a source that stops being publicly readable fails the publisher instead of silently introducing a per-repository token or secret.

Remote repositories are fail-closed to the `KAFKA2306/<repo>` namespace and `ref=main`. Every copied file records both the source repository and the exact 40-character source commit SHA in the manifest.

## Autonomous operation

The central publisher runs:

- every two hours
- immediately when a local allow-listed source or the publishing contract changes
- manually only as an optional diagnostic path

Pull requests run only the unprivileged validation job. Hugging Face OIDC write permission exists only on the non-PR publish job.

Each publish run:

1. validates the publish policy and regression tests
2. clones remote public allow-listed repositories without credentials
3. builds a bundle only from `config/data_lake_publish.json`
4. rejects EDINET DB fields/endpoints not present in the quota-owner allow-list
5. proves OIDC write/read access with a synthetic object and removes it, then confirms cleanup
6. creates the immutable investor2 Japan Yahoo market cache only when its remote completion manifest is absent
7. previews every owned prefix with `hf buckets sync --delete --dry-run`
8. exact-mirrors every owned prefix with `hf buckets sync --delete`
9. runs a second dry-run and fails if any upload/download/delete remains
10. downloads every manifest-listed object and compares SHA-256
11. uploads an immutable run manifest under the central commit SHA plus GitHub run ID/attempt
12. updates `central/manifests/latest.json` only after all data and run-manifest round trips succeed

Transfer commands retry up to three times for transient failures where the owning path provides retries. Yahoo screener rate limits are handled inside `investor2` with bounded exponential backoff; exhaustion still fails closed. Data validation failures are not auto-corrected.

Hugging Face Storage Buckets are mutable/non-versioned, so exact-mirror deletion is intentionally restricted to explicit owned data prefixes. `central/manifests/` is never a sync target and is managed separately.

## One-shot investor2 Yahoo market cache

`KAFKA2306/investor2` owns the market-data collection and consumption code, but it has no Hugging Face credential and performs no remote write. `scripts/alphazerobeta_build_market_snapshot.py` discovers all equities returned by Yahoo Finance for region `jp`, downloads daily history from `2004-01-01` through `2024-12-31`, downloads `1306.T` as the broad Japan benchmark proxy, and emits a local immutable snapshot containing:

- `universe.parquet`
- `benchmark.parquet`
- `prices/jp/part-*.parquet`
- `manifest.json` with byte sizes, SHA-256 hashes, fetch time, Japan ticker count and source contract

The authenticated central publisher owns only the storage transition. `scripts/publish_investor2_yahoo_market_cache.py` checks this completion marker first:

```text
hf://buckets/k4fka/kafka-data-lake/
  central/investor2/private/yahoo-market-cache/v1/manifest.json
```

The earlier worldwide bootstrap attempt failed during Yahoo discovery before any market-cache sync began, so this prefix had no completed or partial snapshot from that run and is reused for the narrower Japan contract. The manifest itself fail-closes the contract to `regions=["jp"]`, `benchmark=1306.T`, the declared date range, writer repository, bucket and prefix.

If the manifest already exists and validates as the canonical immutable Japan `investor2.market-snapshot.v2` snapshot, the publisher exits with `SKIP_ALREADY_PUBLISHED` and does not call Yahoo. If absent, it clones the exact current `investor2/main`, runs the one-shot builder with the storage prefix passed explicitly, validates every local object, syncs only the owned cache prefix, verifies convergence, downloads the published bytes again, compares every declared size/SHA-256, and uploads `manifest.json` last. The manifest therefore acts as the completion marker; a partial upload cannot be mistaken for a completed cache.

### Failure diagnostics

Production run `32641969253` established a concrete dependency failure mode: the publisher installed plain `yfinance`, while the builder called `yfinance.download(..., repair=True)`. The repair path required SciPy, so 3,830 discovered Japan symbols produced empty price batches with `ModuleNotFoundError: No module named 'scipy'`; `1306.T` failed for the same reason and the snapshot aborted before HF cache publication.

The central workflow now installs the declared `yfinance[repair]` extras. The source-side builder also emits structured JSON diagnostics and fails before Yahoo collection when the `repair=True` runtime is incomplete. Diagnostic events identify the dependency preflight, universe page/offset/retry, price batch context and row counts, benchmark phase, exception class/message, elapsed time, and final snapshot summary. A future runtime dependency failure must therefore be attributable before thousands of symbols are processed.

The cache is a reusable frozen Japan market-data input, not historical point-in-time index-membership evidence. Exact AlphaZeroBeta paper reproduction still needs the paper's historical constituent and vendor feature contracts separately.

## Current allow-list

### Local central sources

- `data/edinetdb_projections/**/*.json` → `central/edinetdb/projections/`
- `data/earnings_ledger/**/*.{json,ndjson,md}` → `central/semiconductor/earnings-ledger/`
- `data/financial_db/**/*.json` → `central/finance/semiconductor/`

EDINET DB full/raw API responses remain forbidden by the quota-owner contract. Each accepted projection must use `edinetdb.consumer-projection.v1`; both its endpoint and nested record fields must match `config/edinetdb_quota_plan.json`.

### Public cross-repository sources

- `KAFKA2306/factory:data/**/*.{json,jsonl}` → `central/factory/`
- `KAFKA2306/books:data/` canonical catalog / Kindle normalized records / ISBN overlay only → `central/books/`
- `KAFKA2306/cast_event_cal:public/` canonical event snapshot artifacts only → `central/events/`

`books` deliberately excludes legacy base64 compatibility fragments, enrichment state/report scratch outputs and templates. The allow-list follows the canonical files documented by the books repository.

Events are read from `KAFKA2306/cast_event_cal`, not `vrc_cast_event_calender`, because the latter explicitly identifies itself as a projection/deploy-only repository and identifies `cast_event_cal` as the canonical source.

Adding another public source requires one explicit `publish_roots` entry in `config/data_lake_publish.json`. No Hugging Face authentication change is required as long as the same central writer and bucket are used. Specialized private generated datasets such as the one-shot investor2 Yahoo market cache use a separately owned prefix and must preserve the same sole-writer/OIDC/readback contract.

## Storage layout

```text
hf://buckets/k4fka/kafka-data-lake/
  central/
    edinetdb/
      projections/
    semiconductor/
      earnings-ledger/
    finance/
      semiconductor/
    investor2/
      private/
        yahoo-market-cache/
          v1/
            manifest.json
            universe.parquet
            benchmark.parquet
            prices/jp/part-*.parquet
    factory/
    books/
    events/
    manifests/
      runs/<central-git-sha>/<github-run-id>-<attempt>.json
      latest.json
```

The manifest records, for every published root and object:

- source repository
- exact source Git revision
- source path or generated-object identity
- remote path
- byte size
- SHA-256

That makes the mutable bucket reproducible or independently auditable from versioned source commits while keeping authentication centralized.
