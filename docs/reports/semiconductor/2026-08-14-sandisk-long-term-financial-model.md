# Sandisk FY2028-FY2030 長期財務モデル

正準データ: `data/financial_analysis/sandisk-long-term-financial-model-2026.json`

## 会社開示として画像・分析に使える項目

- 対象期間: FY2028-FY2030
- 売上成長率: **mid-to-high teens, consistent with bit growth**
- 非GAAP粗利益率: **約80%**
- 非GAAP営業利益率: **約75%**
- 営業費用: **売上高の約5%**
- 調整後フリーキャッシュフローマージン: **約50%**
- 事業への再投資後の超過キャッシュ: **100%株主還元**
- NBM: **8顧客**、FY2027 bit shipmentsの約50%、FY2028の約3分の2をカバー

## 画像生成ルール

会社開示画像では、公式一次情報にない年次売上高、年次FCF、WACC、terminal growth、EV、株価目標を補完しない。独自推計を作る場合は `issuer_guidance` と混ぜず、`estimate` または `scenario` として別データ・別表示にする。

売上成長率の `mid-to-high teens` は、15-19%などの数値レンジへ変換しない。

## 一次情報

- Sandisk Investor Day: https://investor.sandisk.com/events/event-details/2026-sandisk-investor-day
- Sandisk long-term financial model release: https://investor.sandisk.com/news-releases/news-release-details/sandisk-details-growth-strategy-and-long-term-financial-model

## Provenance

一次情報再検証: https://github.com/KAFKA2306/semiconductor-earnings-model/issues/106  
画像生成用正準化: https://github.com/KAFKA2306/semiconductor-earnings-model/issues/110
