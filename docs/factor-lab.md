# Factor Lab v1

## Purpose

Financial Database v3 の観測値を、将来リターンとの関係を再現可能に検証する層です。

流れは次のとおりです。

```text
Financial Database v3
  -> point-in-time factor panel
  -> forward returns (1m / 3m / 6m / 12m)
  -> Pearson IC / Rank IC
  -> quantile returns
  -> top-minus-bottom spread
  -> IC stability
  -> site/public/api/v3/factor-lab/index.json
```

この層は売買推奨を生成しません。統計的な関係、標本数、時系列安定性、証拠線を公開します。

## Anti-leakage contract

Factor Lab は決算期末日を「市場がその値を知っていた日」と扱いません。

- SEC 等の規制開示は `filed_at` を優先します。
- 市場観測は `observed_at` を優先します。
- 規制開示に公開時点がない場合は、その観測を因子候補から除外します。
- 月末パネルは、その月末までに既知だった最新値だけを使用します。
- 将来リターンの始値は `as_of` より前の価格を使いません。

## Semantic boundaries

以下を同じ因子として暗黙に混ぜません。

- actual / company guidance / analyst consensus / market observation
- concept
- unit / currency
- annual / quarter / instant
- consolidated / segment
- segment name

因子名はこれらの意味境界を含む signature です。たとえば USD 四半期売上と JPY 年次売上は別因子です。

## Metrics

各 factor × horizon について次を出力します。

- pooled Pearson IC
- pooled Spearman Rank IC
- cross-sectional Rank IC mean / standard deviation
- Rank IC information ratio
- Rank IC t-statistic
- Rank IC positive ratio
- quantile mean returns
- quantile monotonicity
- top-minus-bottom return spread
- cross-section count / sample size

相関が高いだけでは採用根拠にしません。分位の単調性、複数時点での再現性、標本数を同時に確認します。

## Market data

ライブ更新では Financial Database v3 の entity を Yahoo symbol へ明示的に変換し、Yahoo Finance / yfinance の終値を実行時だけ取得します。

生の価格系列は公開リポジトリへ保存しません。公開するのは forward return、因子統計、使用 symbol、取得データの SHA-256 です。

現在の symbol rule:

- `US:*` -> entity ticker
- `JP:3436` -> `3436.T`
- entity id が国コード形式でなくても `exchange: TSE ...` なら `ticker.T`
- `KR:000660` -> `000660.KS`
- entity id が国コード形式でなくても `exchange: Korea Exchange` なら `ticker.KS`
- `exchange` が Kosdaq なら `ticker.KQ`
- `TW:2330` -> `2330.TW`

市場 suffix は entity id だけで推測せず、利用できる場合は exchange metadata を優先します。未知の市場は裸の数字 ticker に変換せず、明示 mapping / exchange rule を追加します。

## OSS review

Factor research の既存 OSS として Microsoft Qlib を確認しています。Qlib は大規模な学習・backtest 基盤として有力ですが、本リポジトリではまず既存の provenance / semantic boundary / fail-closed 契約を維持する小さな標準ライブラリエンジンを採用します。

Factor Lab の入出力は独立しているため、将来 Qlib adapter を追加しても Financial Database v3 の正本は変更しません。

## Run

純粋計算:

```bash
uv run python scripts/factor_inputs.py \
  --financial-db site/public/api/v3/financial-database/index.json \
  --output /tmp/factor-input.json

uv run python scripts/factor_lab.py \
  --factors /tmp/factor-input.json \
  --prices /tmp/prices.json \
  --output /tmp/factor-lab.json
```

ライブ市場データ:

```bash
uv run --with pandas --with "yfinance[repair]" python scripts/build_factor_lab_live.py \
  --financial-db site/public/api/v3/financial-database/index.json \
  --output site/public/api/v3/factor-lab/index.json
```

検証:

```bash
uv run python -m pytest tests/test_factor_lab.py -q
```

## Automation

`.github/workflows/factor-lab-update.yml` が次を担当します。

1. Financial Database v3 を同じ canonical pipeline から再構築
2. point-in-time factor panel を生成
3. 市場価格を runtime memory に取得
4. 1m / 3m / 6m / 12m forward return を生成
5. IC / Rank IC / quantile test を一括計算
6. raw price を保存せず Factor Lab JSON だけを commit
7. その commit を既存 GitHub Pages pipeline が公開