# 半導体決算・財務データ研究基盤

[![Publish earnings model](https://github.com/KAFKA2306/semiconductor-earnings-model/actions/workflows/pages.yml/badge.svg)](https://github.com/KAFKA2306/semiconductor-earnings-model/actions/workflows/pages.yml)
[![Audit live semiconductor earnings Pages](https://github.com/KAFKA2306/semiconductor-earnings-model/actions/workflows/live-pages-audit.yml/badge.svg)](https://github.com/KAFKA2306/semiconductor-earnings-model/actions/workflows/live-pages-audit.yml)
[![Data Platform Standard v1](https://github.com/KAFKA2306/semiconductor-earnings-model/actions/workflows/data-platform-standard.yml/badge.svg)](https://github.com/KAFKA2306/semiconductor-earnings-model/actions/workflows/data-platform-standard.yml)

半導体企業の決算、需要、ASP、bit shipment、設備投資、生産能力、財務、会社予想を、一次情報まで追跡できる形でつなぐ研究基盤です。

推測で欠損を埋めず、実績、会社予想、コンセンサス、独自推計、シナリオ、市場観測を分離し、期間、単位、会計basis、出典、計算系譜を保持します。

**公開サイト:** https://kafka2306.github.io/semiconductor-earnings-model/

## まず見る場所

- [ドキュメント索引](docs/README.md)
- [全体アーキテクチャと正本境界](docs/architecture.md)
- [決算開示の正準フロー](docs/canonical-earnings-flow.md)
- [半導体インフラ・CapEx台帳](docs/semiconductor-infrastructure-ledger.md)
- [Financial Database v3](docs/financial-database.md)
- [開発・検証手順](docs/development.md)

公開面では次を入口にします。

- [統合リサーチ画面・財務耐久力比較](https://kafka2306.github.io/semiconductor-earnings-model/resilience/)
- [決算の一次事実台帳](https://kafka2306.github.io/semiconductor-earnings-model/earnings/)
- [需要から利益までの計算モデル](https://kafka2306.github.io/semiconductor-earnings-model/model/)
- [Financial Database v3 JSON](https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/index.json)
- [Financial Database v3 SQLite](https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/financial.db)
- [Research API v2](https://kafka2306.github.io/semiconductor-earnings-model/api/v2/semiconductor-research/index.json)
- [API v1 index](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/index.json)

## 設計の中心

```text
Primary sources
  -> raw / rejected evidence
  -> canonical ledgers
  -> deterministic derived data
  -> audited publication artifacts
  -> API / Pages / Google Sheets / MCP
```

正本は用途ごとに明示します。

- `data/earnings_ledger/`: 新規決算・業績開示の正準 evidence boundary
- `data/canonical/`: CapEx projects、facilities、customer commitments、orders/backlog など半導体インフラ事実の正準データ
- `data/derived/`: 正本から再生成できる派生値。正本を上書きしない
- `site/public/api/**`: 公開projection。手編集で正本化しない
- Google Sheets: import/export と分析ビュー。移行後の正本ではない

詳しい所有関係は [docs/architecture.md](docs/architecture.md) を参照してください。

## データ契約

このリポジトリでは次を不変条件として扱います。

- Actual / Guidance / Consensus / Estimate / Scenario / Market observation を混ぜない
- NULL と 0 を混同しない
- 年次と四半期、期間値と時点値、連結とセグメントを暗黙に混ぜない
- source URL、publication/observation time、period、unit/currency、basis、value type、evidence ID、hash を必要なschemaで保持する
- 派生値は入力証拠と式へ戻れるようにする
- source不明、basis不明、期間不明、単位不明、矛盾は fail closed にする
- API、DB、UIで別々の真実を作らない

エージェントと自動化向けのリポジトリ契約は [AGENTS.md](AGENTS.md) が正本です。

## 主なデータ経路

### 決算開示

```text
first-party disclosure
  -> data/earnings_ledger/events.ndjson
  -> deterministic audit / lineage / publication
  -> DataPlatformService
  -> REST / CLI / MCP / Pages
```

詳細: [docs/canonical-earnings-flow.md](docs/canonical-earnings-flow.md)

### 半導体インフラ・CapEx

```text
SEC / EDINET / company IR / reviewed imports
  -> data/canonical/
  -> semicon.build_derived
  -> API v2 / Google Sheets projection / earnings inputs
```

詳細: [docs/semiconductor-infrastructure-ledger.md](docs/semiconductor-infrastructure-ledger.md)

### 分析DB

Financial Database v3 は、実績、ガイダンス、コンセンサス、市場観測、推計、シナリオ、NAND KPIを意味クラスを保ったまま統合し、JSONとSQLiteへ公開します。

詳細: [docs/financial-database.md](docs/financial-database.md)

## ローカル開始

```bash
uv sync
uv run python -m pytest -q
npm --prefix site ci
GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model \
PUBLIC_BUILD_SHA=local \
npm --prefix site run build
```

データ更新や特定サブシステムの検証は変更範囲ごとに異なります。コマンド一覧は [docs/development.md](docs/development.md) に集約しています。

## ドキュメント方針

ルートREADMEは入口と不変条件だけを持ちます。詳細な設計、運用、取得パイプライン、外部サービス固有の制約、日付付きの調査結果は `docs/` 側で所有します。

新しい説明を追加する前に [docs/README.md](docs/README.md) の「どこに書くか」を確認し、同じ契約を複数ファイルへコピーしないでください。

## 注意

このプロジェクトは財務・業界研究用です。投資助言、売買推奨、将来利益の保証ではありません。
