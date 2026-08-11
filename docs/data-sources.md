# Data sources

## 正本

Data Platform Standard v1 の正本は `data/earnings_ledger/` です。MCP・Data API・CLIは、この台帳を読む `src/data_platform.py` を共用し、各adapter側で値を再計算しません。

一次情報の採否と接続先は `data/earnings_ledger/source_registry.json` を正準registryとします。UIや検索結果ページを正本としてscrapeしません。取得した候補が一次情報であること、対象期間、公開時刻、会計basis、必須fieldを検証した後だけ `events.ndjson` へ昇格します。

## Data layers

| Layer | 責務 | 主なartifact |
| --- | --- | --- |
| `raw/bronze` | 取得候補、棄却、source state | `rejected.ndjson`, `source_registry.json`, `source_state.json` |
| `normalized/silver` | 正規化済み事実、監査、lineage | `events.ndjson`, `*audit_latest.json`, `lineage_latest.json` |
| `public/gold` | fail-close監査を通った公開snapshot/API | `publication_latest.json`, `site/public/api/**` |

物理directory名をlayer名へ強制的に合わせるのではなく、Data Platform serviceが返す各recordの `data_layer` で機械判定可能にします。

## Provenance contract

主要recordは以下を欠落させません。

`canonical_id`, `schema_version`, `data_layer`, `data_as_of`, `generated_at`, `source_type`, `source_id`, `source_doc_id`, `source_url`, `source_observed_at`, `source_hash`, `freshness`, `stale`, `null_reason`, `derivation_method`, `basis`, `provenance`

`source_hash` は正本artifactのSHA-256です。値が取得できない場合は0・false・空の推定値へ置換せず、recordを空にして `null_reason` を返します。

## External source policy

外部source固有の認証情報はenvironment variableでのみ与えます。repositoryへAPI keyや非公開payloadを保存しません。sourceの追加・変更はregistry、取得adapter、監査、fixtureを同じ変更線で更新し、監査を通らないsourceはpublic/goldへ昇格しません。
