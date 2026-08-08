# Earnings Evidence Ledger v2 — 一次情報台帳設計

## 0. 現行v1との差分

2026-08-08時点のmainには、SEC EDGAR / TDnetを24時間窓で2時間ごとに収集し、採用・棄却・監査・Markdownを保存するv1がある。

v2では、これを「毎回24時間を再検索するcollector」から「sourceごとのlast_seenを持つimmutable evidence ledger」へ移行する。

| 項目 | v1 | v2 target |
|---|---|---|
| discovery | 毎回`now-24h..now`を再走査 | Source Registry + `last_seen_id` |
| raw evidence | URL中心 | raw bytes + SHA-256 + retrieved_at |
| fiscal period | `report_date`中心 | FY/FQ/period_endを必須化 |
| event key | source filing hash | `company_id|fiscal_period|document_type` |
| comparisons | なし | QoQ/YoYをledger JOINでコード計算 |
| consensus | なし | actual/guidance/consensus分離、欠損はnull |
| rejected | 単一ledger、理由が可変 | 固定enum + 日付別ledger |
| report | 2時間ごとのcollectと同時生成 | 07:00 JST cutoff後に別jobで生成 |
| AI | downstream運用説明のみ | validator PASS済みeventだけを要約 |

## 1. 正準フロー

```text
official primary sources
  -> discover
  -> persist raw evidence
  -> normalize
  -> freshness gate
  -> validate
  -> canonical events.ndjson
  -> deterministic QoQ / YoY / surprise
  -> 07:00 JST daily Markdown
  -> AI summary
```

AIは最後の要約だけを担当する。候補発見、一次情報判定、`published_at`判定、fiscal period判定、QoQ/YoY計算、欠損consensus補完には使わない。

## 2. Source Registry

正準化できるsourceはSource Registryに登録され、`enabled=true`でなければならない。

一般Web検索、ニュース記事、検索結果の日付はcanonical eventへ直接昇格できない。

### SEC EDGAR

公式仕様: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

`data.sec.gov/submissions/CIK##########.json`をdiscoveryに利用する。submissions/XBRL JSONはSECがリアルタイム更新する一次データである。

### JPX / TDnet

公式仕様: https://www.jpx.co.jp/markets/paid-info-listing/tdnet/02.html

TDnet APIは決算短信系PDF/XBRLと、銘柄コード・開示日付・開示時刻・資料区分等を提供する。契約・利用権限が必要なため、API adapterはentitlementが確認できるまでfail-closedで無効化する。無料のTDnet公開画面を使用する場合も、`published_at`はTDnet表示の開示時刻だけを採用し、検索結果日付等を代用しない。

## 3. データ構造

```text
data/earnings_ledger/
├── source_registry.json
├── collection_state.json
├── raw/YYYY-MM-DD/
│   └── <source>-<document-id>.<ext>
├── inbox/
│   ├── candidates.ndjson
│   └── events.ndjson
├── events.ndjson
├── rejected/YYYY-MM-DD.ndjson
├── reports/YYYY-MM-DD.md
└── schema/
    ├── event-v2.schema.json
    ├── rejection-v2.schema.json
    └── collection-state-v2.schema.json
```

- `raw`: 取得した一次資料そのもの。SHA-256をevent/candidateへ記録する。
- `candidates`: discovery済み、fiscal period未確定でも保存可能。
- `inbox/events`: deterministic normalizerが生成したvalidator前event。
- `events.ndjson`: validator PASSだけ。正準台帳。
- `rejected`: 削除せず、棄却理由を日付別に保存。
- `reports`: 閲覧用。Markdownは正準データではない。

## 4. last_seen契約

sourceごとに以下を永続化する。

```text
last_seen_id
last_seen_published_at
last_attempt_at
last_success_at
last_content_sha256
```

SECは`last_seen_id`へ到達したら走査を停止する。初回bootstrapは有限期間に制限し、全履歴を新着扱いしない。

`last_seen`は「検索結果の最新」ではなく、一次source上で処理済みのdocument identityを指す。

## 5. 時刻契約

| field | 意味 | 使用可否 |
|---|---|---|
| `published_at` | 一次情報の公表時刻 | freshness判定の正準時計 |
| `retrieved_at` | collector取得時刻 | ingestion window / audit |
| `page_updated_at` | ページ更新時刻 | 公表時刻の代替禁止 |
| `search_result_date` | 検索結果表示日 | 正準データ利用禁止 |

`published_at`不明は`UNKNOWN_PUBLISHED_TIME`、未来は`FUTURE_EARNINGS_EVENT`、validator window外は`OUTSIDE_TIME_WINDOW`。

## 6. fiscal period / event identity

canonical eventは以下を必須にする。

```text
company_id
company
fiscal_year
fiscal_quarter
fiscal_period
period_end
event_type
document_type
```

一意キー:

```text
event_id = company_id|fiscal_period|document_type
```

`fiscal_period == FY{fiscal_year}Q{fiscal_quarter}`を機械検証する。

SECの`filingDate`やファイル名だけからfiscal periodを推測してcanonical eventへ昇格させない。企業固有normalizerが一次資料のperiod end / fiscal labelを確定できない場合はcandidateを`PENDING`に残す。

### 必須回帰fixture

2025-08-27公表のNVIDIA FY2026Q2を、2026-08-08のFY2027Q2として扱う候補はAIに届く前に棄却されなければならない。

## 7. actual / guidance / consensus

3種類を混ぜない。

- `actuals`: 一次資料から検証済み実績
- `guidance`: 会社が明示した予想
- `consensus`: 外部consensus providerの別レイヤー

consensusが取得できなければ`null`。AI補完は禁止。

同一`metric_id + unit + basis`だけを比較し、コードで計算する。

```text
QoQ      = current / previous_quarter - 1
YoY      = current / same_quarter_previous_fy - 1
surprise = actual / consensus - 1
```

比較対象欠損または分母0なら`null`。

## 8. rejected ledger enum

```text
OUTSIDE_TIME_WINDOW
UNKNOWN_PUBLISHED_TIME
STALE_FISCAL_PERIOD
DUPLICATE
NOT_PRIMARY_SOURCE
FUTURE_EARNINGS_EVENT
REPOST
MISMATCHED_COMPANY
UNVERIFIED_NUMBER
```

アダプター内部の詳細理由（例: fetch failure / not earnings related）は`detail`へ入れ、正準`reason`は上記enumへマッピングする。

## 9. GitHub Actions

### collector

- 2時間ごと。
- `00`分を避け、`17`分などへずらす。
- `discover -> raw persist -> normalize -> validate -> store`のみ。
- report生成・AI要約はしない。
- source障害は既存canonical ledgerを書き換えずfail closed。
- 一時障害は最大3回まで再試行する。

### daily report

- 毎朝07:07 JST。
- 07:00 JSTでwindowを閉じる。
- 前回07:00以降にGitHubへ蓄積され、validator PASSのeventだけ読む。
- 新規collectionはしない。
- deterministic Markdownを生成する。

### reusable workflow

共通setup、contract test、commit/rebase/retryをreusable workflowへ集約する。

GitHub公式仕様:

- schedule: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- scheduled workflow delay: https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
- reusable workflows: https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations

## 10. 移行順序

1. v2 schemaとSource Registry契約をCIへ追加。
2. `collection_state.json`とraw evidence保存を追加。
3. SEC discoveryをlast_seen方式へ変更。
4. 企業別fiscal-period normalizerを追加。
5. v2 validatorを通過したeventだけを`events.ndjson`へ保存。
6. QoQ/YoY/consensus layerを追加。
7. 2時間collectorと07:07 reportを分離。
8. v1のcombined scheduleを停止。
9. 24時間以上のshadow runでv1/v2差分を監査。
10. v2を正準化し、v1を削除。

## 11. merge gate

以下を満たすまでv2を正準化しない。

- 古いNVIDIA fiscal period誤採用fixtureがPASS。
- third-party URLをcanonical eventへ昇格できない。
- sourceごとのlast_seenが永続化される。
- raw evidenceのSHA-256がcanonical eventから追跡できる。
- FY/FQ/period_end不一致がfail closed。
- QoQ/YoYがコード計算される。
- consensus欠損がnullのまま維持される。
- collectorと07:07 reportが別workflow。
- v2 CI成功。
