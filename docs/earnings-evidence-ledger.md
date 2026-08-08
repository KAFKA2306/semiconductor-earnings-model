# 一次情報台帳型 Earnings Evidence Ledger

## 1. 目的

朝7時のAIがその場でWeb検索して「24時間以内か」「最新の決算期か」を推測する構成を廃止する。

正準経路は次だけとする。

```text
official primary sources
  -> discover
  -> normalize
  -> freshness gate
  -> validate
  -> immutable event ledger
  -> deterministic QoQ / YoY / surprise
  -> daily Markdown
  -> AI summary
```

AIは最後の要約だけを担当する。候補発見、一次情報判定、`published_at`判定、決算期判定、QoQ/YoY計算、欠損consensus補完には使わない。

## 2. 一次情報

### SEC EDGAR

公式仕様: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

`https://data.sec.gov/submissions/CIK##########.json` を企業別filing discoveryに使う。SECはsubmissions historyとXBRL dataをJSON APIで提供し、submission disseminationに応じてリアルタイム更新する。

### JPX / TDnet

公式仕様: https://www.jpx.co.jp/markets/paid-info-listing/tdnet/02.html

TDnet APIは決算短信系のPDF/XBRLと、銘柄コード・開示日付・開示時刻・資料区分等を提供する。ただし有料契約サービスなので、利用権限とproduction endpointが設定されるまで`enabled=false`でfail-closedとする。

### Company IR

企業IRはSource Registryに公式hostを登録する。企業固有のfiscal-period normalizerが一次資料から期を確定できるまで`enabled=false`とし、URLが公式であることだけを理由にcanonical eventへ昇格させない。

## 3. データ構造

```text
data/earnings/
├── source_registry.json
├── collection_state.json
├── raw/YYYY-MM-DD/
├── inbox/
│   ├── candidates.ndjson
│   └── events.ndjson
├── events.ndjson
├── rejected/YYYY-MM-DD.ndjson
├── reports/YYYY-MM-DD.md
└── schema/
    ├── event.schema.json
    ├── rejection.schema.json
    └── collection-state.schema.json
```

- `raw`: 取得した一次資料のbyte証跡。
- `inbox/candidates.ndjson`: discovery済み、normalization前。
- `inbox/events.ndjson`: deterministic normalizerが作ったvalidator前event。
- `events.ndjson`: validator PASS済みの正準台帳。
- `rejected`: 棄却理由を消さずに残す監査台帳。
- `reports`: 閲覧用。Markdownは正準データではない。

## 4. Source Registry契約

`data/earnings/source_registry.json` に登録され、かつ`enabled=true`のsourceだけが正準化対象になれる。

一般Web検索・ニュース記事・検索結果の日付からcanonical eventを作ることは禁止する。

初期source:

- NVIDIA: SEC submissions enabled / company IR registered but disabled
- AMD: SEC submissions enabled / company IR registered but disabled
- Microsoft: SEC submissions enabled / company IR registered but disabled
- KIOXIA Holdings: company IR / TDnet registered but disabled until normalizer・API entitlementが揃う

## 5. last_seen契約

各sourceについて次を永続化する。

- `last_seen_id`
- `last_seen_published_at`
- `last_attempt_at`
- `last_success_at`
- `last_content_sha256`

SEC discoveryは`last_seen_id`へ到達した時点で過去走査を止める。初回bootstrapも72時間に制限し、全履歴を新着扱いしない。

## 6. 時刻契約

4種類の時刻を混同しない。

| field | 用途 |
|---|---|
| `published_at` | 一次情報の公表時刻。freshness判定の正準時計 |
| `retrieved_at` | collectorが取得した時刻。7時レポートのingestion window |
| `page_updated_at` | ページ更新時刻。公表時刻の代替禁止 |
| `search_result_date` | 検索結果表示の日付。正準データへの利用禁止 |

`published_at`不明は`UNKNOWN_PUBLISHED_TIME`、未来は`FUTURE_EARNINGS_EVENT`、validator window外は`OUTSIDE_TIME_WINDOW`。

## 7. 決算期契約

canonical eventは次を必須にする。

- `company_id`
- `fiscal_year`
- `fiscal_quarter`
- `fiscal_period`
- `period_end`
- `document_type`

一意キーは次。

```text
event_id = company_id|fiscal_period|document_type
```

`fiscal_period`は`FY{fiscal_year}Q{fiscal_quarter}`と一致しなければならない。

SEC filing metadataからfiscal periodを推測して自動昇格させない。企業固有normalizerが決算期を一次資料から確定するまでcandidateは`PENDING`に置く。

このfail-closed境界により、例えば2025年公表の古いNVIDIA FY2026Q2を2026年8月の新着FY2027Q2として扱う経路を物理的に遮断する。

## 8. 数値契約

actual / company guidance / consensusを別レイヤーにする。consensusを取得できない場合は`null`であり、AIで補完しない。

同じ`metric_id + unit + basis`だけを比較し、コードで次を計算する。

```text
QoQ      = current / previous_quarter - 1
YoY      = current / same_quarter_previous_fy - 1
surprise = actual / consensus - 1
```

比較対象欠損または分母0なら`null`。

## 9. rejected ledger

固定enum:

- `OUTSIDE_TIME_WINDOW`
- `UNKNOWN_PUBLISHED_TIME`
- `STALE_FISCAL_PERIOD`
- `DUPLICATE`
- `NOT_PRIMARY_SOURCE`
- `FUTURE_EARNINGS_EVENT`
- `REPOST`
- `MISMATCHED_COMPANY`
- `UNVERIFIED_NUMBER`

棄却は削除せず`data/earnings/rejected/YYYY-MM-DD.ndjson`に残す。

## 10. GitHub Actions

GitHub公式ではscheduled workflowは高負荷時に遅延する場合があり、特に時刻の先頭は高負荷になりやすい。そのため00分を避ける。

- collector: 2時間ごと、17分に実行
- daily report: 毎朝07:07 JST
- daily reportでは新規収集をしない
- reportは前日07:00 JST以上、当日07:00 JST未満に`retrieved_at`が入ったvalidator PASS eventだけを読む

共通setup・test・commitはreusable workflowへ分離する。

GitHub公式仕様:

- schedule: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- schedule delay: https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
- reusable workflows: https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations

## 11. 現在の実装境界

このPRで実装するのは、Source Registry、last_seen state、SEC discovery、raw SHA-256証跡、schema、validator、rejected ledger、deterministic comparison、daily report、CI/Actionsである。

SEC candidateからcanonical earnings eventへ変換する企業別normalizerは別段階とし、未実装の間は`PENDING`のまま保持する。誤った決算を通知するより通知0件を選ぶ。
