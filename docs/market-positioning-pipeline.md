# 信用需給・強制デレバレッジ取得パイプライン

## 目的

キオクシア型の「業績・値上げが継続する一方、レバレッジ投資家の強制売却で株価だけが極端に下がる局面」を再現可能に検出するため、信用残高、韓国市場の信用融資・反対売買、世界半導体売上を同じ監査可能な台帳へ保存します。

## 正準データ源

| 地域・指標 | 正準元 | 取得方式 | 認証 |
|---|---|---|---|
| 日本の個別信用買残・売残 | J-Quants API V2 `/markets/margin-interest` | REST API | `JQUANTS_API_KEY` |
| 日本の株価・出来高 | J-Quants API V2 `/equities/bars/daily` | REST API | `JQUANTS_API_KEY` |
| 韓国の信用融資残高 | data.go.kr 金融投資協会統計 `/getGrantingOfCreditBalanceInfo` | REST API | `DATA_GO_KR_SERVICE_KEY` |
| 韓国の預り金・未収金・反対売買 | 同 `/getSecuritiesMarketTotalCapitalInfo` | REST API | `DATA_GO_KR_SERVICE_KEY` |
| 世界半導体月次売上 | SIAの公式Market Dataリリース（WSTS集計） | 公式HTML | 不要 |

Yahoo!ファイナンス、掲示板、検索結果の抜粋は正準値にしません。KRX Data Marketplaceは有用ですが、文書化された公開APIを確認できるまで、内部OTP・ブラウザ用エンドポイントを自動化しません。

## データ契約

各観測は次を必須とします。

- `source_id`
- `entity`
- `metric`
- `observed_date`
- `value`
- `unit`
- `frequency`
- `quality`
- `source_url`
- `fetched_at`
- `raw_sha256`

取得に失敗した値を0や推定値で補いません。既存の正常な観測を保持し、`collection_state.json`へ失敗理由を保存します。

## 派生指標

### 日本の信用倍率

```text
信用倍率 = 信用買残株数 / 信用売残株数
```

J-Quants V2の`LongVol`を買残、`ShrtVol`を売残として計算します。売残が0の場合は無限大を保存せず、派生値を欠損とします。加えて、買残の前週比、買残を直近20観測日の平均出来高で割った処分必要日数、暦年最初の終値を100とする株価指数を計算します。J-Quantsの生の株価・出来高・信用残高はリポジトリへ保存しません。

### 韓国のレバレッジ

```text
信用融資・預り金比率 = 信用融資残高 / 投資家預り金
60観測ピークからの整理率 = 1 - 当日信用融資残高 / 過去60観測の最大残高
```

休場日の架空行は作らず、公式応答にある基準日だけを使います。

### ロスカット強度

```text
反対売買5観測平均 = 直近5公表日の反対売買額の平均
```

「雰囲気」をニュース件数で代用せず、実際の反対売買額を主系列にします。

### セクター売上

SIA公式リリース内で、対象月、年、世界売上額（十億米ドル）が同じ文に明記された場合だけ採用します。WSTS/SIAが用いる3か月移動平均をそのまま保存し、隣接月から前月比を派生計算します。

## 出力

- 正準台帳: `data/market_positioning/observations.json`（J-Quantsの生データは保存せず、派生指標だけを保存）
- 取得状態: `data/market_positioning/collection_state.json`
- 情報源台帳: `data/market_positioning/source_registry.json`
- 公開API: `site/public/api/v1/market-positioning/index.json`

## CI

`.github/workflows/market-positioning-update.yml` は次に実行します。

- 平日07:30 JST: 韓国統計と海外月次リリースの反映
- 平日18:30 JST: JPX当日データ公開後の反映
- 手動実行
- 関連コードのPull Request検証

取得、派生計算、テストが成功した場合だけ台帳と公開APIをコミットします。

## GitHub Actions Secrets

Repository settingsのActions secretsへ次を登録します。

- `JQUANTS_API_KEY`
- `DATA_GO_KR_SERVICE_KEY`

秘密情報が未登録の場合、その情報源だけを`disabled_missing_secret`として記録します。SIAの公開系列とテストは継続します。

## ローカル実行

```bash
export JQUANTS_API_KEY='...'
export DATA_GO_KR_SERVICE_KEY='...'
uv run python scripts/update_market_positioning.py --strict
uv run python -m pytest tests/test_market_positioning_pipeline.py -q
```
