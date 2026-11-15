# NANDメモリ株の投資仮説

NAND好況の残存期間と平常化後の株主向けキャッシュフローを逆算し、開示の追加や訂正でどの前提が動くかを確認する。

## 実行

    scripts/equity-brief run --ticker 285A --as-of 2026-11-15 --state /tmp/nand-brief
    scripts/equity-brief replay --ticker 285A --as-of 2026-11-15 --state /tmp/nand-brief --json
    scripts/equity-brief eval --ticker 285A --as-of 2026-11-15 --state /tmp/nand-brief

日付は日本時間のその日末。時刻を指定する場合はオフセット付きISO時刻を使う。時刻未確認の日付資料は日末から採用する。対象は定義ファイルに登録された資料。動的な価格・予想ページは初回取得時のハッシュで保存する。後日の再計算は保存済みスナップショットを使う。

訂正は JSON 配列に source、url、published_at、tier を指定し、run と replay に --corrections で渡す。新しい公開時刻以降に訂正版が効く。元資料と過去の計算結果はハッシュで参照できる。

## 共通処理と銘柄定義

資料の選択、バイト保全、抽出、証拠ID、dbtの実行、保存後の読み戻しをスクリプトで再利用する。NAND固有の表の読み方、会計期間、勘定単位、事業の仮説は config/equity_brief/nand.json と dbt の分析モデルで管理する。成果物には数値の種類、期間、金額単位、原典URL、ページ、ハッシュを含める。シナリオ表は割引率と終価成長率を固定し、現在株価を説明する平常時の年間株主向けCFを逆算する。現金と借入残高は財務情報として併記し、株主向けCFを使う評価に重ねて加算しない。

2026年参照資料

- [金融庁 EDINET API仕様書](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html)
- [JPX 2026年のデータ拡充](https://www.jpx.co.jp/corporate/news/news-releases/6020/20260119.html)
- [DuckDB 2.0.0](https://duckdb.org/release_calendar)
- [pypdf 7.1.0](https://pypi.org/project/pypdf/7.1.0/)
- [評価の設計](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)

## 評価設計の更新

評価は、根拠、数値、時点再現、仮説の反証、実行コストの順に行う。訂正前後と未取得資料のケースは同じCLIで検査する。新しい銘柄へ広げるときは、根拠の所在と仮説が変わる条件を定義し、校正に使った期間と別の期間で検査する。基準を通過した構成は、成功1件当たりのトークン数・処理時間で比較する。定型の日本語短報はテンプレートで作る。

- [Promptfoo 0.123.0](https://github.com/promptfoo/promptfoo/releases)
- [スクリプトを使う評価](https://www.promptfoo.dev/docs/providers/custom-script/)
- [2026年の評価移行ガイド](https://developers.openai.com/cookbook/examples/evaluation/moving-from-openai-evals-to-promptfoo)

## 分析方法を選ぶ基準

通過順は次のとおり。既存版と候補版に同じ資料、時点、シナリオ、評価データを渡す。

1. 証拠の完全性。結論を左右する数値の原典到達率100%。期間、単位、株式分割、連結範囲、資料の版の混同0件。
2. 意思決定への寄与。NAND価格、ビット出荷、SSD構成、設備投資、運転資本、納税時期のどれが変わり、どの条件で仮説が崩れるかを出す。価格を単独で下げるだけのケースと、出荷や構成が同時に変わるケースを分けて検証する。
3. 再計算と転用。入力ハッシュと定義版を固定した再生結果が一致する。別の決算期や銘柄へ広げるときは独立したデータで採点し、抽出・計算の失敗を完了として数える件数を0件にする。
4. 生成と運用の費用。品質が並ぶ候補は、成功1件当たりの全トークン、処理時間の95パーセンタイル、自作の保守範囲の順で比較する。定型実行はモデル0回。解釈が必要な処理を比較する場合はAPIの使用量を記録する。

事業側の出力はNAND契約価格・ビット・原価・供給増計画の変化。投資家向けの出力は好況残存期間別の平常時必要CF。制作者向けの出力は短報と一次資料へ戻れる証拠ID。独立採点と処理時間の比較には同じエントリーポイントを使う。

    scripts/equity-brief replay --as-of 2026-11-15 --state /tmp/nand-brief --json > /tmp/nand-replay.json
    EQUITY_BRIEF_SNAPSHOT=/tmp/nand-replay.json PROMPTFOO_DISABLE_TELEMETRY=1 \
      npx --yes promptfoo@0.123.0 eval -c config/equity_brief/promptfoo.yaml --no-cache

動的なIFISページは当時の数値を返すスナップショットを使う。ライブの認証付きデータ収集とモデルを用いた解釈は個別に検証する。

[2026年の実行環境込み評価](https://developers.openai.com/cookbook/examples/partners/harness_aware_plugin_evals/harness_aware_plugin_evals)
