# EDINETDB quota owner

## 目的

EDINETDB Freeプランの認証付きリクエストを、複数GitHub repositoryが重複して消費しないための共有取得規約です。

EDINETDB公式ドキュメントではFreeは100 requests/day・3,000 requests/monthで、REST APIとMCPは同一アカウントの制限対象です。複数API keyを使ってもアカウント単位で合算されます。また`search_companies_batch`は複数企業検索を1 callへまとめる用途として提供され、RESTの`GET /v1/companies`は`edinet_code`を最大50件まで1 requestへまとめられます。

一次情報:

- MCP guide: https://edinetdb.jp/docs/mcp-guide
- REST API: https://edinetdb.jp/docs/api
- Integration cookbook: https://edinetdb.jp/docs/cookbook
- Terms: https://edinetdb.jp/legal/terms
- Data sources: https://edinetdb.jp/docs/data-sources

## 規約上の境界

EDINETDB利用規約は、API/MCP responseの全部または大部分をファイルやDBとして第三者へ一括再配布すること、実質的に同等のwrapper/proxy APIを構築することを禁止しています。一方、自身のapplication/dashboard/reportへの組み込みと、性能目的の一時cacheは許可されています。公開serviceでは`Powered by EDINET DB`等の出典表示が必要です。

そのため、このrepositoryは**公開bulk cacheを作りません**。

保持するもの:

- request計画
- request fingerprint
- 成功日時
- raw response SHA-256
- consumerごとに必要fieldだけへ縮小したprojection
- attribution

保持しないもの:

- API key
- raw/full API response
- 全社・全fieldのmirror
- EDINETDBと実質同等の公開API

## 取得フロー

```text
各repositoryの需要
  -> config/edinetdb_quota_plan.json へ集約
  -> URL + paramsをcanonical化
  -> 同一requestをSHA-256 fingerprintでdedupe
  -> company masterは最大50 EDINET codes/requestへbatch
  -> budget gate
  -> EDINETDBをquota-ownerだけがfetch
  -> raw responseはmemory上だけで処理
  -> consumerごとのallow-list fieldsだけproject
  -> projection + hash + ledgerだけcommit
  -> sole HF publisherがprojectionを再検証
  -> private Hugging Face data lakeへpublish + SHA-256 readback
```

## 現在のpilot

確認済みEDINET code:

- Toyota Motor Corporation / トヨタ自動車株式会社: `E02144`
- Kioxia Holdings Corporation / キオクシアホールディングス株式会社: `E35948`

現在の計画は次の3 authenticated requestsだけです。

1. `GET /v1/companies?edinet_code=E02144&edinet_code=E35948`
2. `GET /v1/companies/E02144/financials?...`
3. `GET /v1/companies/E35948/financials?...`

企業マスタを2回呼ばず1回へまとめます。各consumerへは自分が必要とするcompanyだけprojectするため、`factory`へKIOXIA masterを配ることも、semiconductor repoへToyota masterを配ることもしません。

## quota budget

`config/edinetdb_quota_plan.json`で:

- `daily_limit = 100`
- `reserve_requests = 10`
- daily usable budget = 90
- `monthly_limit = 3000`
- `monthly_reserve_requests = 300`
- monthly usable budget = 2700

としています。

planがdaily/monthly usable budgetを超える場合はnetwork access前に失敗します。現行pilotは3 unique authenticated requests/runで、同一日の再実行はmaterialized projectionを再利用します。

## 再利用

同じUTC日で、同じrequest fingerprintが`success`かつ全projection fileが存在する場合、同期を再実行してもEDINETDBを呼びません。`--force`だけが明示的再取得を許可します。

ledgerにはraw bodyを置かず`response_sha256`のみ残します。

## 実行

quotaを使わず計画だけ確認:

```bash
python scripts/edinetdb_quota_owner.py --plan-only
```

実取得:

```bash
export EDINETDB_API_KEY=...
python scripts/edinetdb_quota_owner.py
```

GitHub Actionsでは`EDINETDB_API_KEY`をrepository secretとして登録します。secretが無ければsyncはfetchせず終了します。

## 定期頻度

EDINET DB公式のデータソース説明では、有報取得・変換は**毎日8:00 JST**です。その更新窓の直後に1回だけ同期すれば十分なので、quota ownerは**毎日08:20 JST**に実行します。

さらに、quota plan・consumer registry・quota owner実装・workflow自体が`main`で変更された場合は、そのpush直後にも1回同期します。これにより、新しいconsumer/field契約を追加しても次回定刻まで待たずに検証できます。同一日の同一requestはprojection/ledgerでdedupeされるため、契約変更が既存requestだけなら重複取得を避けます。

速報性が必要なendpointを追加する場合も、まず以下を検討します。

1. 金融庁EDINET API v2等の原典側で変更を検知する
2. EDINETDB callは変更があるcompany/endpointだけに限定する
3. `fields`, `sections`, `limit`, batch指定で1 response当たりの情報密度を最大化する
4. 同じrequestを複数consumerが要求したら1回へdedupeする

## consumerへの反映

projectionの正本はquota ownerのmaterialization境界にだけ置きます。consumer repositoryはEDINET DBへ直接fallbackせず、中央で検証済みのprojection/manifestを参照します。

中央data lake publisherは`config/edinetdb_quota_plan.json`のfield allow-listとprojectionの`records[]`を照合し、許可外field・endpoint drift・未知のconsumer/projection idをfail closedします。公開consumerへはbulk mirrorではなく、そのapplicationが使う限定fieldだけを供給し、UI/READMEに`Powered by EDINET DB`相当の表示を残します。
