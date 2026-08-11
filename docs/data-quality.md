# Data quality and correction policy

## Quality gates

`get_data_quality` は次の正準artifactを結合します。

- `*audit_latest.json`: schema、period、source、accounting basis等のdeterministic audit
- `publication_latest.json`: freshnessと公開可否
- `lineage_latest.json`: artifact pathとSHA-256

一次監査またはpublication auditがPASSでない場合は `status: BLOCKED` とします。source不明、basis不明、矛盾、必須artifact欠落はfail-closeで扱います。

lineage manifestはpoint-in-time証拠です。manifest生成後に正本artifactが更新された場合、current hashがmanifest hashと異なること自体はデータ破損と断定せず `LINEAGE_REVISION_CHANGED` として返します。新しいlineageを生成するまで古いmanifestを現在snapshotの証拠として偽装しません。

## Correction policy

誤りを修正する場合は、公開JSONだけを手編集しません。

1. source/evidenceまたは正規化ロジックを修正する
2. canonical ledgerと監査を再生成する
3. lineageのSHA-256を再生成する
4. publication snapshot/APIを再生成する
5. CIでservice・REST・CLI・MCP parityとdeterministic replayを確認する

correctionで値が不明になった場合は `null_reason` を付けてnull状態へ戻し、過去値や0で穴埋めしません。

## CI contract

`.github/workflows/data-platform-standard.yml` は以下をfail-closeで検証します。

- provenance fieldの完全性
- `source_hash` と正本artifact SHA-256の一致
- data layerの列挙値
- null semantics
- deterministic replay
- REST / CLI / canonical service parity
- MCP `server/discover` による2026-07-28 negotiation
- `tools/list` の8 tool完全一致
- MCP tool callとcanonical serviceのparity

MCP固有テストは公式Python SDK v2を一時environmentへ解決して実行し、repositoryの既存locked environmentを不必要に変更しません。
