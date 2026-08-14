# Sandisk Investor Day 2026 × EDINET半導体50社 再検証

観測時刻: 2026-08-14T10:07:00+09:00  
対象Issue: https://github.com/KAFKA2306/semiconductor-earnings-model/issues/106

## 結論

Sandiskが2026年8月13日に公表したFY2028-FY2030長期財務モデルの中核は公式一次情報で確認できた。公式表現は、売上成長率を **mid-to-high teens, consistent with bit growth**、非GAAP粗利益率を約80%、非GAAP営業利益率を約75%、営業費用を売上比約5%、調整後FCFマージンを約50%、事業投資後の超過キャッシュを100%株主還元とするもの。15-19%という数値レンジへの置換は行わず、会社の原文表現を保持する。

NBMは8顧客と締結済みで、FY2027のbit shipmentsの約50%、FY2028の約3分の2をカバーする見通し。契約要素として committed volumes、minimum financial guaranteesを伴うenforceable contractual frameworks、structured pricingが明示されている。

FY2026 Q4の公式実績は売上89.65億ドル、GAAP粗利益率84.6%、GAAP営業利益70.37億ドル、GAAP純利益69.03億ドル。前年Q4は売上19.01億ドル、GAAP粗利益率26.2%、GAAP営業利益1,800万ドルだった。

技術面ではBiCS9 QLCを実績あるBiCS8 arrayとBiCS10-based CMOS waferの組合せとして説明し、BiCS10 QLCはBiCS8比60%のbit-density increaseを掲げる。enterprise datacenter flash TAMは2030年1.2 zettabytesとする。

HBFの最初の標準仕様について、SK hynix公式発表日は **2026年8月4日**。最大512GB、最大3.0TB/s、UCIeを掲げ、GoogleとTenstorrentの参加を明記している。したがって「8月3日公開」は修正対象。

## 市場価格の扱い

投稿に含まれるSNDK/MU/WDC/LRCXの瞬間株価・同日騰落率は、発行体IRやEDINETの一次財務証拠とは別の市場観測である。本データセットには混在させない。必要な場合は取引所・市場データソースから別snapshotとして取得する。

## EDINET DB 50社比較

既存の `config/investor2_kioxia_semiconductor_universe_50_2026-08-12.json` と同じ条件を再実行した。

- business tag: `semiconductor`
- revenue > 0
- delisted除外
- revenue降順
- limit 50

2026-08-14時点の候補は51社。上位50社は既存ユニバースと一致し、51位で上限外となるのはQDレーザ（E35542）。50社それぞれについて最新FYの revenue / operating income / net income / total assets / net assets / operating CF / capex / ROE / equity ratio / EPS / DPS をEDINET DB MCPから取得した。欠損値はnullのまま保持する。

完全な機械可読データ:
`data/financial_analysis/sandisk-investor-day-2026-edinet-semiconductor-50.json`

## 一次情報

- Sandisk Investor Day: https://investor.sandisk.com/events/event-details/2026-sandisk-investor-day
- Sandisk long-term model release: https://investor.sandisk.com/news-releases/news-release-details/sandisk-details-growth-strategy-and-long-term-financial-model
- Sandisk FY2026 Q4: https://investor.sandisk.com/news-releases/news-release-details/sandisk-reports-fiscal-fourth-quarter-2026-financial-results
- SK hynix HBF FMS 2026: https://news.skhynix.com/en/hbf-at-fms-2026/
- SK hynix/Sandisk HBF standardization: https://news.skhynix.com/en/sk-hynix-and-sandisk-begin-global-standardization-ofnext-generation-memory-hbf/
- EDINET portal: https://disclosure2.edinet-fsa.go.jp/
