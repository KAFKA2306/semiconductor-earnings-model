# Central data lake

## Contract

`KAFKA2306/semiconductor-earnings-model` is the sole authenticated writer to the private Hugging Face Storage Bucket `k4fka/kafka-data-lake`.

Consumer repositories do not receive `HF_TOKEN`, do not register their own Hugging Face Trusted Publisher, and do not write directly to the private bucket. New consumers therefore do not create new Hugging Face setup work.

The sole writer is `.github/workflows/hf-bucket-smoke.yml`. The filename is intentionally retained because the Hugging Face Trusted Publisher is pinned to that workflow path. It uses GitHub OIDC with `HF_OIDC_RESOURCE=buckets/k4fka/kafka-data-lake`; no long-lived Hugging Face token is stored.

Primary references:

- https://huggingface.co/docs/hub/en/trusted-publishers
- https://huggingface.co/docs/hub/storage-buckets
- https://docs.github.com/en/actions/reference/security/oidc

## Autonomous operation

The central publisher runs:

- every two hours
- immediately when an allow-listed projection or the publishing contract changes
- manually only as an optional diagnostic path

Each run:

1. validates the publish policy and regression tests
2. builds a bundle only from `config/data_lake_publish.json`
3. rejects unexpected/raw EDINET DB top-level fields fail-closed
4. proves OIDC write/read access with a synthetic object and removes it
5. uploads each allow-listed object
6. downloads every uploaded object and compares SHA-256
7. uploads an immutable run manifest keyed by the Git commit SHA
8. updates `central/manifests/latest.json` only after the run manifest round-trip succeeds

Transfer commands retry up to three times for transient failures. Data validation failures are not auto-corrected; they fail closed.

## Current allow-list

The initial source is `data/edinetdb_projections/**/*.json` only. EDINET DB full/raw API responses remain forbidden by the quota-owner contract. Each accepted projection must use `edinetdb.consumer-projection.v1`, preserve provider attribution, request fingerprint, response SHA-256 and contain only the established projection envelope plus allow-listed record fields created by the quota owner.

Adding another source requires one explicit `publish_roots` entry in `config/data_lake_publish.json`. No Hugging Face authentication change is required as long as the same central writer and bucket are used.

## Storage layout

```text
hf://buckets/k4fka/kafka-data-lake/
  central/
    edinetdb/
      projections/
        <owner>__<repo>/
          <projection>.json
    manifests/
      runs/<git-sha>.json
      latest.json
```

The manifest records source repository, Git revision, source path, remote path, byte size and SHA-256 for every published object.
