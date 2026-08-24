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

Hugging Face authentication exists only in the central publisher. External public source repositories are read with anonymous HTTPS `git clone`.

The clone command disables Git credential helpers and interactive credential prompts. `actions/checkout` also runs with `persist-credentials: false`. Therefore a source that stops being publicly readable fails the publisher instead of silently introducing a per-repository token or secret.

Generic cross-repository bundle sources remain constrained by the central allow-list. Specialized generated datasets use their own explicit configuration contract. For the investor2 Yahoo cache, source repository and source ref are declared in `config/investor2_yahoo_market_cache.json`; every generated snapshot records the exact 40-character source commit SHA in provenance.

## Autonomous operation

The central publisher runs:

- every two hours
- immediately when a local allow-listed source or publishing contract changes
- manually as a diagnostic path

Pull requests run only the unprivileged validation job. Hugging Face OIDC write permission exists only on the non-PR publish job.

Each publish run:

1. validates the publish policy and regression tests
2. clones remote public allow-listed repositories without credentials
3. builds the generic bundle only from `config/data_lake_publish.json`
4. rejects EDINET DB fields/endpoints not present in the quota-owner allow-list
5. proves OIDC write/read access with a synthetic object and removes it, then confirms cleanup
6. processes the configured investor2 Yahoo market-cache base and safe completed-year extension
7. previews every owned prefix with `hf buckets sync --delete --dry-run`
8. exact-mirrors every owned prefix with `hf buckets sync --delete`
9. runs a second dry-run and fails if any upload/download/delete remains
10. downloads every manifest-listed object and compares SHA-256
11. uploads an immutable run manifest under the central commit SHA plus GitHub run ID/attempt
12. updates `central/manifests/latest.json` only after all data and run-manifest round trips succeed

Transfer commands retry for transient failures only where the owning path explicitly defines a retry contract. Yahoo collection paging, batching, pauses, attempts, exponential-backoff base, and download timeout are declared in the market-cache configuration rather than hidden in collector code. Exhaustion still fails closed. Data validation failures are not auto-corrected.

Hugging Face Storage Buckets are mutable/non-versioned, so exact-mirror deletion is intentionally restricted to explicit owned data prefixes. `central/manifests/` is never a sync target and is managed separately.

## Investor2 Yahoo market cache

`KAFKA2306/investor2` owns market-data collection and consumption code, but it has no Hugging Face credential and performs no remote write. Its `scripts/alphazerobeta_build_market_snapshot.py` is runtime-contract driven: regions, date range, benchmark, storage identity, writer identity, pagination, batching, pauses, retries, backoff, timeout, and output path are explicit inputs. It does not carry a production region list, benchmark, date range, or collection-tuning default.

The production values live in one file: `config/investor2_yahoo_market_cache.json`. The current production contract selects the Japan Yahoo universe, `1306.T` benchmark, the existing base range, the private bucket namespaces, source repository/ref, collection parameters, annual extension release rule, and audit evidence target. Those are deployment choices, not reusable-code assumptions.

A generated immutable snapshot contains:

- `universe.parquet`
- `benchmark.parquet`
- `prices/<region>/part-*.parquet`
- `manifest.json` with byte sizes, SHA-256 hashes, fetch time, source/storage contracts, universe counts, and the collection contract

The authenticated central publisher owns the storage transition. The configured base completion marker is currently:

```text
hf://buckets/k4fka/kafka-data-lake/
  central/investor2/private/yahoo-market-cache/v1/manifest.json
```

Completed calendar-year additions use the configured extension namespace and do not rewrite prior immutable bytes:

```text
central/investor2/private/yahoo-market-cache/extensions/v1/<year>/
```

If an existing immutable manifest matches the configured market/storage contract, the publisher reuses it without calling Yahoo. Existing snapshots created before `collection_contract` was introduced remain readable and verifiable; newly generated snapshots must record and match the full collection contract. If a required snapshot is absent, the publisher clones the configured investor2 source/ref, passes every runtime value explicitly, validates every local object, syncs only the owned prefix, verifies convergence, downloads the published bytes again, compares every declared size/SHA-256, and uploads `manifest.json` last. A partial upload therefore cannot be mistaken for a completed cache.

Market-cache evidence workflows read base prefix, audit evidence prefix, canonical manifest SHA, writer identity, and evidence issue from the same configuration rather than duplicating those values in workflow YAML. The central authenticated bucket remains a workflow-level infrastructure boundary and is checked against the dataset configuration before use.

### Failure diagnostics

Production run `32641969253` established a concrete dependency failure mode: the publisher installed plain `yfinance`, while the builder called `yfinance.download(..., repair=True)`. The repair path required SciPy, so 3,830 discovered Japan symbols produced empty price batches with `ModuleNotFoundError: No module named 'scipy'`; `1306.T` failed for the same reason and the snapshot aborted before HF cache publication.

The central workflow now installs the declared `yfinance[repair]` extras. The source-side builder also emits structured JSON diagnostics and fails before Yahoo collection when the `repair=True` runtime is incomplete. Diagnostic events identify dependency preflight, universe page/offset/retry, price-batch context and row counts, benchmark phase, exception class/message, elapsed time, and final snapshot summary. A future runtime dependency failure must therefore be attributable before thousands of symbols are processed.

The configured cache is reusable frozen market-data input, not historical point-in-time index-membership evidence. Exact AlphaZeroBeta paper reproduction still needs the paper's historical constituent and vendor feature contracts separately.

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

Adding another public source requires one explicit `publish_roots` entry in `config/data_lake_publish.json`. No Hugging Face authentication change is required as long as the same central writer and bucket are used. Specialized private generated datasets use separately owned prefixes and explicit contracts while preserving the same sole-writer/OIDC/readback boundary.

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
            prices/<region>/part-*.parquet
          extensions/
            v1/<year>/
          evidence/
            v1/<manifest-sha>/cache_stats.json
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
