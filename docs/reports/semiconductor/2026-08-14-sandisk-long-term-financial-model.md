# Sandisk FY2028-FY2030 長期財務モデル — 成長指標監査版

正準データ: `data/financial_analysis/sandisk-long-term-financial-model-2026.json`

## 結論

Sandiskの「成長率」は一つの系列として扱わない。

- **売上高成長率**: FY2028-FY2030の会社長期モデルは **`mid-to-high teens, consistent with bit growth`**。これは issuer long-term model target として保持する。
- **bit growth**: 売上高成長率のqualifierとして言及されているが、現行の一次情報captureだけでは、market bit demand / production bits / shipped bits のどのscopeかを固定しない。数値も補完しない。
- **四半期実績**: Q3 FY2026売上は **$5.95B、QoQ +97%、YoY +251%**。これは実績四半期のrateであり、FY2028-FY2030の長期モデルと同じ成長率ではない。
- **成長driver**: Q3 FY2026の会社説明は **高付加価値顧客へのmix shift** と **higher pricing** を含む。売上成長をbit数量だけに帰属させない。

## 成長指標の型

| 項目 | Metric | Scope | Unit | Period | Rate basis | Value type |
|---|---|---|---|---|---|---|
| 長期売上成長 | revenue_growth | Sandisk consolidated revenue | percent | FY2028-FY2030 | issuer_long_term_model_target | issuer_guidance |
| bit growth relation | bit_growth | 未確認 | percent_change | FY2028-FY2030 | 未確認 | issuer_qualifier |
| Q3 FY2026売上QoQ | revenue_growth | Sandisk consolidated revenue | percent | Q3 FY2026 | QoQ | actual |
| Q3 FY2026売上YoY | revenue_growth | Sandisk consolidated revenue | percent | Q3 FY2026 | YoY | actual |
| NBM FY2027 coverage | contracted_bit_shipment_coverage | FY2027 Sandisk bit shipments | percent_of_bit_shipments | FY2027 | share | issuer_guidance |
| NBM FY2028 coverage | contracted_bit_shipment_coverage | FY2028 Sandisk bit shipments | share_of_bit_shipments | FY2028 | share | issuer_guidance |

**QoQ / YoY / CAGR / issuer long-term model target は相互変換しない。** CAGRと明示されていない値をCAGRと表記しない。

## 会社開示として分析に使える長期項目

- 対象期間: FY2028-FY2030
- 売上成長率: **mid-to-high teens, consistent with bit growth**
- 非GAAP粗利益率: **約80% of revenue**
- 非GAAP営業利益率: **約75% of revenue**
- 営業費用: **売上高の約5%**
- 調整後フリーキャッシュフローマージン: **約50% of revenue**
- 事業への再投資後の超過キャッシュ: **100%株主還元**
- NBM: **8顧客**、FY2027 Sandisk bit shipmentsの約50%、FY2028 Sandisk bit shipmentsの約3分の2をカバー

## 投資判断で見る順序

1. **Volume** — Sandisk bit shipmentsが伸びているか。market demandやproduction bitsと混同しない。
2. **Price** — ASP上昇/低下が売上にどう寄与したか。
3. **Mix** — Datacenter・高付加価値顧客へのmix shiftが売上と粗利をどう変えたか。
4. **Margins** — 粗利率・営業利益率が長期モデルへ収束しているか。
5. **FCF** — 調整後FCFマージンの再現性があるか。
6. **Durability** — NBM coverageと最低金融保証付き契約が需要・価格の耐久性へつながっているか。

## 画像・ページ生成ルール

会社開示の表示では、公式一次情報にない年次売上高、年次FCF、WACC、terminal growth、EV、株価目標を補完しない。

特に以下を禁止する。

- `mid-to-high teens` を15-19%等の任意レンジへ数値化する
- issuer long-term model targetをYoY/CAGRへ勝手に読み替える
- `consistent with bit growth` からbit growthのscopeや数値を推測する
- 売上成長をbit growth単独の寄与として表示する
- actual / issuer guidance / independent scenarioを同じ系列・同じ色・同じlabelで混ぜる

## 一次情報

- Sandisk Investor Day: https://investor.sandisk.com/events/event-details/2026-sandisk-investor-day
- Sandisk long-term financial model release: https://investor.sandisk.com/news-releases/news-release-details/sandisk-details-growth-strategy-and-long-term-financial-model
- Sandisk Q3 FY2026 results: https://investor.sandisk.com/news-releases/news-release-details/sandisk-reports-fiscal-third-quarter-2026-financial-results
- SEC Exhibit 99.1: https://www.sec.gov/Archives/edgar/data/2023554/000162828026028879/sndkq3-26ex991xpressrelease.htm

## Provenance

- 一次情報再検証: https://github.com/KAFKA2306/semiconductor-earnings-model/issues/106
- 画像生成用正準化: https://github.com/KAFKA2306/semiconductor-earnings-model/issues/110
- 成長指標の再型付け / 投資方針ページ刷新: https://github.com/KAFKA2306/semiconductor-earnings-model/issues/113
