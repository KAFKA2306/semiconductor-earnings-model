# Architecture

## Purpose

この文書は、リポジトリ全体の「どこが正本で、何が派生で、どこから公開されるか」を1か所で定義します。

各サブシステム固有の詳細は専用docへ委譲します。

## System flow

```text
Primary sources
  |
  +-> earnings disclosures
  |     -> data/earnings_ledger/
  |     -> audit / lineage / publication
  |     -> DataPlatformService
  |     -> REST / CLI / MCP / Pages
  |
  +-> infrastructure / CapEx / facilities / commitments
  |     -> data/registry/ + data/canonical/
  |     -> data/derived/
  |     -> API v2 / Google Sheets projection / earnings inputs
  |
  +-> reviewed analytical inputs
        -> financial database build inputs
        -> Financial Database v3
        -> JSON / SQLite / analytical views
```

公開surfaceは正本ではありません。正本または監査済みbuild inputから再生成できることを前提にします。

## Canonical ownership

| Boundary | Role | Canonical status |
| --- | --- | --- |
| `data/earnings_ledger/` | 新規決算・業績開示、rejected evidence、audit、lineage、publication state | 決算evidenceの正本 |
| `data/registry/` | entity identityなど半導体インフラ側のregistry | registry owner |
| `data/canonical/` | infrastructure facts、events、CapEx projects、facilities、orders/backlog、customer commitments | 半導体インフラ事実の正本 |
| `data/derived/` | project economics、decision evidence、earnings inputs等 | 再生成可能な派生層 |
| `data/financial_db/` | 分析DB用catalog、review済みmanual observation等 | その入力クラスに限定した所有。決算ledgerやinfrastructure ledgerを置換しない |
| `site/public/api/**` | 静的公開API | projection |
| `site/` Pages | 人間向けUI | projection |
| Google Sheets | import/export、分析ビュー | projection |
| Hugging Face data lake | versioned sourceからpublishされるcentral storage | publication/storage boundary |

### Earnings ownership

`data/earnings_ledger/` は新規に公表された決算・業績関連evidenceの正準境界です。

受理、棄却、監査、レポート生成の詳細は [canonical-earnings-flow.md](canonical-earnings-flow.md) を参照してください。

Data Platform Standard v1 のread pathは `src/data_platform.py` の `DataPlatformService` に集約し、REST、CLI、MCP adapter側で財務値やquality statusを再計算しません。

関連:
- [data-sources.md](data-sources.md)
- [methodology.md](methodology.md)
- [data-quality.md](data-quality.md)
- [mcp.md](mcp.md)

### Semiconductor infrastructure ownership

`data/canonical/` は設備投資、施設、顧客コミットメント、受注残などの半導体インフラevidenceを所有します。

`semicon.build_derived`、API v2、Google Sheets projectionはこのcanonical layerを読む側です。

Google Sheetsから取り込んだ値も、source priority、単位、期間、provenanceを確認してcanonicalへ受理された後は、Sheet自体を正本として扱いません。

詳細は [semiconductor-infrastructure-ledger.md](semiconductor-infrastructure-ledger.md) を参照してください。

## Value classes

次の値種別は意味的に分離します。

- reported actual
- company guidance
- analyst consensus
- market observation
- deterministic derived value
- internal estimate
- scenario
- model output

派生値、推計、scenario、model outputで一次Factを上書きしません。

Financial Database v3の詳細な意味モデルは [financial-database.md](financial-database.md) を参照してください。

## Data lifecycle

### 1. Acquire

一次資料、公式API、許諾済みprovider、review済みimportから候補を取得します。

UI検索結果や二次まとめを、一次Factの代用として正本化しません。

### 2. Normalize

entity、concept、period、period type、scope、unit、currency、basis、value type、source identityを明示します。

不明な値を推測で補いません。

### 3. Accept or reject

正本へ入れる前にschemaとsource条件を検証します。

受理できない候補は、owner subsystemが定めるrejected/conflict pathへ残し、値だけを黙って捨てたり補完したりしません。

### 4. Derive

派生値は入力evidenceとformulaを保持し、正本Factと別レイヤーに保存します。

### 5. Audit

schema、source、period、unit、basis、freshness、lineage、hashなどをdeterministicに検証します。

failed auditを見栄えのために通過させません。

### 6. Publish

JSON、SQLite、Pages、Google Sheets、MCP、data lakeへprojectionします。

公開成功とmerge成功は別のpostconditionです。必要なworkflowではlive artifactを再検証します。

## Null and conflict semantics

NULLは0ではありません。

missing、not disclosed、not comparable、stale、ambiguous、rejected、conflictingは、owner schemaで区別します。

次は推測しません。

- missing financial value
- fiscal period
- accounting basis
- consensus
- provenance
- source identity
- currency
- scale

異なるsourceが競合した場合は、source priorityとowner contractに従い、低優先sourceで高優先sourceを上書きしません。

## Interfaces

| Interface | Owner implementation | Rule |
| --- | --- | --- |
| Data Platform service | `src/data_platform.py` | canonical read logic |
| REST | `src/data_platform_rest.py` | service adapter |
| CLI | `src/data_platform_cli.py` | service adapter |
| MCP | `src/mcp_server.py` | service adapter |
| Infrastructure API | `semicon/build_api_v2.py` | canonical infrastructure projection |
| Sheets export | `semicon/export/google_sheets.py` | canonical infrastructure projection |
| Pages | `site/` | audited/public data projection |

adapter独自の再計算で別の真実を作らないことが共通ルールです。

## Change rule

データ契約を変更する場合は、docだけを変更して完了にしません。

必要に応じて同じ変更線で次を更新します。

```text
schema / registry
-> ingest or normalization code
-> audit
-> tests
-> generated artifact
-> API / UI projection
-> documentation
```

変更範囲別の検証は [development.md](development.md) を参照してください。
