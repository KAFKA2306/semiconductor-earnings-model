# Central data lake

## Contract

`KAFKA2306/semiconductor-earnings-model` is the sole authenticated writer to the private Hugging Face Storage Bucket `k4fka/kafka-data-lake`.

Consumer/source repositories do not receive `HF_TOKEN`, do not register their own Hugging Face Trusted Publisher, and do not write directly to the private bucket. New public `KAFKA2306/*` sources are added only through the central allow-list, so they create no Hugging Face setup work.

The sole writer is `.github/workflows/hf-bucket-smoke.yml`. The filename is intentionally retained because the Hugging Face Trusted Publisher is pinned to that workflow path. It uses GitHub OIDC with `HF_OIDC_RESOURCE=buckets/k4fka/kafka-data-lake`; no long-lived Hugging Face token is stored.

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
6. previews every owned prefix with `hf buckets sync --delete --dry-run`
7. exact-mirrors every owned prefix with `hf buckets sync --delete`
8. runs a second dry-run and fails if any upload/download/delete remains
9. downloads every manifest-listed object and compares SHA-256
10. uploads an immutable run manifest under the central commit SHA plus GitHub run ID/attempt
11. updates `central/manifests/latest.json` only after all data and run-manifest round trips succeed

Transfer commands retry up to three times for transient failures. Data validation failures are not auto-corrected; they fail closed.

Hugging Face Storage Buckets are mutable/non-versioned, so exact-mirror deletion is intentionally restricted to explicit owned data prefixes. `central/manifests/` is never a sync target and is managed separately.

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

Adding another public source requires one explicit `publish_roots` entry in `config/data_lake_publish.json`. No Hugging Face authentication change is required as long as the same central writer and bucket are used.

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
- source path
- remote path
- byte size
- SHA-256

That makes the mutable bucket reproducible from versioned source commits while keeping authentication centralized.
