# Documentation

このディレクトリは、`semiconductor-earnings-model` の設計、データ契約、運用手順、個別パイプラインの正本を整理します。

ルート [README](../README.md) は入口です。詳細仕様はここに置き、同じ契約をREADMEへ複製しません。

## 読む順番

1. [Architecture](architecture.md) - システム全体、正本境界、projectionの関係
2. [Canonical earnings flow](canonical-earnings-flow.md) - 新規決算開示の受理、棄却、監査、公開
3. [Semiconductor Infrastructure Ledger](semiconductor-infrastructure-ledger.md) - CapEx、施設、顧客コミットメント、Google Sheets移行
4. [Financial Database v3](financial-database.md) - 分析DBの意味モデルと公開形式
5. [Development](development.md) - ローカル実行、変更範囲別の検証

## ドキュメント地図

| 分類 | ドキュメント | 所有する内容 |
| --- | --- | --- |
| 全体設計 | [architecture.md](architecture.md) | 正本、派生、公開面、サービス境界 |
| 決算台帳 | [canonical-earnings-flow.md](canonical-earnings-flow.md) | earnings ledgerのproduction lineとfailure ownership |
| データ取得 | [data-sources.md](data-sources.md) | source registry、data layer、provenance |
| 計算規約 | [methodology.md](methodology.md) | Fact / derived / inferred の境界、deterministic replay |
| 品質 | [data-quality.md](data-quality.md) | quality gate、correction policy、CI contract |
| 分析DB | [financial-database.md](financial-database.md) | Financial Database v3のschemaと追加ルール |
| 半導体インフラ | [semiconductor-infrastructure-ledger.md](semiconductor-infrastructure-ledger.md) | `data/canonical/`、CapEx、Google Sheets projection |
| MCP | [mcp.md](mcp.md) | MCP endpoint、tool contract |
| NAND | [nand-kpi-pipeline.md](nand-kpi-pipeline.md) | NAND KPI収集と更新 |
| 市場需給 | [market-positioning-pipeline.md](market-positioning-pipeline.md) | 信用需給、デレバレッジ、SIA等 |
| Factor Lab | [factor-lab.md](factor-lab.md) | factor研究パイプライン |
| Data lake | [central-data-lake.md](central-data-lake.md) | Hugging Face bucketの認証・公開境界 |
| EDINET DB | [edinetdb-consumer-registry.md](edinetdb-consumer-registry.md) | consumer registry |
| EDINET DB | [edinetdb-quota-owner.md](edinetdb-quota-owner.md) | quota ownershipと取得制約 |
| 公開規約 | [project-publication-standard.md](project-publication-standard.md) | project publicationの最小契約 |
| 調査記録 | [reports/](reports/) | 日付付き調査、監査、個別テーマの記録 |

## どこに書くか

新しい内容は次の基準で配置します。

| 内容 | 配置 |
| --- | --- |
| プロジェクトの目的、入口、主要リンク | ルート `README.md` |
| リポジトリ全体の正本境界 | `docs/architecture.md` |
| 決算開示の受理・監査・公開契約 | `docs/canonical-earnings-flow.md` |
| source、provenance、data layer | `docs/data-sources.md` |
| 計算・null・replayの意味規約 | `docs/methodology.md` |
| quality gate、訂正手順 | `docs/data-quality.md` |
| 特定pipelineの取得・運用 | 対応する `*-pipeline.md` |
| 外部サービス固有の認証・quota | サービス固有doc |
| 一時点の調査結果、比較、監査結果 | `docs/reports/` |
| エージェント実行規則 | ルート `AGENTS.md` |

## 重複を増やさないルール

1. 契約にはowner docを1つ決める。
2. 別docでは契約本文をコピーせず、owner docへリンクする。
3. 現在値や日付付き状況は設計docへ埋め込み続けず、必要なら `docs/reports/` へ分離する。
4. generated JSON、SQLite、Pages、Google Sheetsを仕様の正本にしない。
5. コマンドは可能な限り [development.md](development.md) に集約し、個別docにはその領域固有の最小コマンドだけを残す。
6. ファイル名だけで責務が分からない新規docを増やさない。

## 変更時チェック

docsだけの変更でも、リンク先や公開URLを変えた場合は [development.md](development.md) のdocs/publication checksを実行します。データ契約を変更した場合はdocs変更として扱わず、対応するschema、code、tests、CIも同じ変更線で更新します。
