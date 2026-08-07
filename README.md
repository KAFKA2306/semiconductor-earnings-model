# 半導体決算・財務データ研究基盤

**公開サイト:** https://kafka2306.github.io/semiconductor-earnings-model/

企業の決算資料、規制開示、業界KPIを、期間・単位・情報種別・出典を保ったまま収集し、半導体企業の利益、財務耐久力、設備投資、需要、NAND市況を検証するための研究基盤です。

実績、会社予想、アナリスト予想、独自推計、シナリオ、株価観測を混ぜず、すべての計算を元データまで追跡できる形で公開します。

## 最初に見るページ

- [統合リサーチ画面・財務耐久力比較](https://kafka2306.github.io/semiconductor-earnings-model/resilience/)
- [決算の一次事実台帳](https://kafka2306.github.io/semiconductor-earnings-model/earnings/)
- [需要から利益までの計算モデル](https://kafka2306.github.io/semiconductor-earnings-model/model/)
- [信用需給・デレバレッジAPI](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/market-positioning/index.json)
- [Financial Database v3 JSON](https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/index.json)
- [Financial Database v3 SQLite](https://kafka2306.github.io/semiconductor-earnings-model/api/v3/financial-database/financial.db)
- [Research API v2](https://kafka2306.github.io/semiconductor-earnings-model/api/v2/semiconductor-research/index.json)
- [API v1 index](https://kafka2306.github.io/semiconductor-earnings-model/api/v1/index.json)

## このプロジェクトで扱う内容

- 売上高、営業利益、営業CF、設備投資、FCF、現金、負債、利益剰余金
- 四半期成長率、利益率、年次推移、CAGR、変動性
- 流動性、負債負担、下振れ時の資金耐久力
- データセンター設備投資、減価償却、電力容量、受注残
- NANDのASP、ビット出荷量、在庫日数、稼働率、製造能力
- HBM、先端パッケージ、ウェハ能力などの業界KPI
- 日本の個別信用倍率、韓国の信用融資・反対売買、世界半導体月次売上
- 市場価格、時価総額、企業価値、予想PER、コンセンサス
- 会社予想と実績、予想と独自シナリオの差分

## 主要な分析経路

### `/earnings/`

開示された売上高、営業利益、営業CF、設備投資、期間、XBRLタグ、提出書類URLを保存する一次事実台帳です。

### `/resilience/`

四半期の成長性と収益性、年次のFCF・流動性・負債、同業中央値、下振れシナリオ、データ品質フラグを統合した比較画面です。

### `/model/`

既知の入力、計算式、中間値、未知の変数、最終判断を分離し、需要から利益までの計算境界を示します。

### `/api/v1/market-positioning/`

J-Quants、韓国の公共データポータル、SIA公式リリースから、信用需給、強制デレバレッジ、世界半導体売上を定期取得します。J-Quantsの生データは公開せず、信用倍率などの派生分析値だけを保存します。

### `/api/v3/financial-database/`

実績、ガイダンス、コンセンサス、市場観測、推計、シナリオ、NAND KPIを別の値種別として保持する再利用可能な分析DBです。

## データモデル

1. **Entity** — 企業、証券、ティッカー、CIK、同業グループ
2. **Concept** — 財務項目、業界KPI、会社予想、市場観測、計算指標
3. **Observation** — 値、単位、対象期間、観測日、改訂、出典
4. **Source** — 規制開示、会社IR、許諾された予想、市場データ、モデル
5. **Derived metric** — 計算式と入力証拠を持つ派生値
6. **Evaluation** — 判定ルール、閾値、結果、根拠指標
7. **Evidence edge** — 計算・判定から元データへの系譜
8. **Audit issue** — 欠損、古さ、競合、形式不良、根拠不足

年次と四半期、期間値と時点値、連結とセグメントを暗黙に混ぜません。

## 金額単位の契約

`/earnings/` が読む金額factと派生四半期値は、すべて明示的な `unit` を持ちます。HTML生成へ渡す正準単位は **base USD (`unit: "USD"`)** です。`USD_million`、`USD_billion`、`JPY`、`JPY_million`、`JPY_billion` は入力・fixtureで識別可能ですが、そのままHTMLへ流しません。

- `USD_million` は `value × 1,000,000`、`USD_billion` は `value × 1,000,000,000` でbase USDへ正規化します。
- JPYをUSDへ換算する場合は、観測日・出典を持つ明示的な `JPY_per_USD` を入力し、`JPY / JPY_per_USD` で換算します。暗黙の為替レートや固定レートは使いません。
- SEC Companyfacts由来の金額はAPIのunit配列から `USD` のfactだけを採用し、表示時に `$...B` へ縮尺する処理とデータ単位を分離します。
- `site/scripts/audit-units.mjs` はAstro buildの前に一次API、半導体利益API、需要APIの比較対象を監査し、欠損unit、未対応unit、million/billionの未正規化、JPYの未換算を検出したら非0終了します。
- 単位換算の純関数とfail-closed動作は `npm --prefix site run test:unit-audit` で検証します。

SECのEDGAR XBRL GuideはUSD金額のunitを `iso4217:USD` とし、「thousands/millions of USD」のようなunit自体を定義しないよう要求しています。そのため本リポジトリでも、SEC由来データはbase USDを正準形とし、million/billionは表示・外部入力側のscaleとしてのみ扱います。

## NAND KPIの扱い

NAND ASPとビット出荷量は、次を明示して保存します。

- 前四半期比の実績
- 4四半期を複利計算した前年同期比
- 比較可能な会社想定との差
- 会社が使用した原文表現
- 数値非開示または比較不能の状態

比較可能な開示がない場合は、差分を推測せず`not_disclosed_or_not_comparable`として残します。

関連資料:

- [信用需給・強制デレバレッジ取得パイプライン](docs/market-positioning-pipeline.md)
- [NAND KPI recurring pipeline](docs/nand-kpi-pipeline.md)
- [Kioxia / NAND sector CapEx audit](docs/reports/semiconductor/2026-07-30-kioxia-nand-sector-capex.md)
- [Financial database operating contract](docs/financial-database.md)
- [Metric catalog](data/financial_db/metric_catalog.json)

## 更新と公開の流れ

```text
一次資料を取得
  → 期間・タグ・単位を正規化
  → 派生指標を計算
  → 同業比較・シナリオ評価
  → 出典・計算系譜を監査
  → JSON / SQLite / Web画面を生成
  → GitHub Pages公開後に実URLを再検証
```

取得失敗、期間の古さ、根拠のない値、壊れた証拠リンク、DB監査エラー、SQLite不整合、テスト失敗、公開後検証失敗がある場合はデプロイを停止します。

機械可読な定義:

- [Financial research ontology](data/ontology/financial_research_ontology.json)
- [Cross-project ontology](ontology/project.yaml)

## ローカル検証

```bash
uv sync
: "${SEC_USER_AGENT:?set SEC_USER_AGENT to identify the real operator/contact}"
uv run python scripts/build_primary_api.py
uv run python scripts/build_semiconductor_profit_api.py
uv run python scripts/build_semiconductor_resilience_api_v2.py
uv run python scripts/build_semiconductor_research_api.py
uv run python scripts/finalize_semiconductor_research_api.py
uv run python scripts/build_demand_api.py
uv run python scripts/update_nand_kpis.py --offline
uv run python scripts/update_market_positioning.py
uv run python scripts/build_financial_database_with_nand.py
uv run python scripts/check_readme_pages_link.py
uv run python scripts/build_model_snapshot.py
uv run python scripts/run_quant_audit.py data/quant_audit/semiconductor_latest.json --output site/public/data/quant-audit.json
uv run python -m pytest -q
npm --prefix site ci
npm --prefix site run test:unit-audit
GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model PUBLIC_BUILD_SHA=local npm --prefix site run build
```

`SEC_USER_AGENT`には実際の運用者を識別できる連絡情報を設定してください。信用需給の認証済み取得には、`JQUANTS_API_KEY`と`DATA_GO_KR_SERVICE_KEY`も設定します。

## 注意

このプロジェクトは財務・業界研究用です。投資助言、売買推奨、将来利益の保証ではありません。

**README最終監査:** 2026-08-07
