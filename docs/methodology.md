# Methodology

## 計算境界

Data Platform Standard v1 は以下を混同しません。

1. **Fact** — 一次情報から検証済みで台帳へ受理された事実
2. **Deterministic derived value** — 入力と式から同一結果を再生成できる派生値
3. **Inferred / model output** — LLM・ML・シナリオ等の推論

推論やモデル出力でFactを上書きしません。モデルを追加する場合はmodel/version/run/artifact hashを別系統で保持します。

## Canonical identity

- company: `company:<company_id>`
- earnings event: `earnings-event:<event_id>`
- evidence: `evidence:<event_id>`
- audit: `audit:<artifact>`
- lineage: `lineage:latest`
- publication: `publication:latest`
- quality: `data-quality:latest`

adapterが独自IDを再発番せず、同じ正本からMCP・Data API・CLIが同一 `canonical_id` を返します。

## Deterministic replay

`src/data_platform.py` はread-only projectionです。現在の正本snapshotが同一なら、同一引数から同一JSONを返します。CIは同じtoolを複数回実行しcanonical JSONが一致することを検証します。

lineage manifestに記録されたSHA-256と現在のartifactが異なる場合、それを黙って現在値へ置換しません。`get_data_quality` は `REVISION_CHANGED` として表面化し、point-in-time manifestとcurrent snapshotの違いを明示します。

## Null semantics

値が存在しないことは値0ではありません。

- company/eventが存在しない: `records: []`, `null_reason: "NOT_FOUND"`
- freshness gateを通る公開eventがない: `null_reason: "NO_FRESH_PUBLISHABLE_EVENTS"`
- evidence audit windowに対象がない: `null_reason: "NO_VERIFIED_EVIDENCE_IN_WINDOW"`

比較不能、source不明、basis不明、矛盾は推測補完せず、既存監査/rejected ledgerへ隔離します。

## Shared domain service

正準の読取ロジックは `DataPlatformService` に1回だけ実装します。

- MCP: `src/mcp_server.py`
- REST Data API: `src/data_platform_rest.py`
- CLI: `python -m src.data_platform_cli ...`

各adapterは同じservice methodを呼び、adapter側で財務値・freshness・quality statusを再計算しません。
