# EDINETDB consumer registry

## Contract

EDINET DBへの認証付きアクセスは `KAFKA2306/semiconductor-earnings-model` だけが所有します。consumer repositoryはEDINET DBへ直接fallbackせず、必要な場合だけquota ownerが生成したconsumer-specific projectionを読みます。

一次情報:

- https://edinetdb.jp/docs/mcp-guide
- https://edinetdb.jp/docs/api
- https://edinetdb.jp/legal/terms

EDINET DB Freeの上限は100 requests/day、3,000 requests/monthです。このrepositoryでは外部・対話利用の余地を残すため、自己管理上限を日次90、月次2,700に設定しています。これはprovider上限そのものではなく、このquota ownerが自分で使ってよい上限です。

## Registry

正本は `config/edinetdb_consumer_registry.json` です。

- `quota_owner`: EDINET DBへ認証付きfetchできる唯一のrepository
- `projection_only`: quota ownerが作った限定projectionだけ利用可能
- `not_applicable`: 現在のcontractではEDINET DB依存を作らない

現在:

- quota owner: `KAFKA2306/semiconductor-earnings-model`
- projection only: `KAFKA2306/factory`, `KAFKA2306/investor2`
- not applicable: `KAFKA2306/books`, `KAFKA2306/WealthAudit`, `KAFKA2306/pal-atlas`, `KAFKA2306/cast_event_cal`, `KAFKA2306/vrc_cast_event_calender`

`not_applicable` repositoryを `config/edinetdb_quota_plan.json` のconsumerへ追加するとCIがfail-closeします。必要性が発生した場合は、先にregistryを根拠付きで `projection_only` へ変更し、既存requestと同一method/path/paramsならfetch数を増やさずprojectionだけ追加します。

## Quota reservation

実fetchは `scripts/edinetdb_quota_guard.py` を必ず通します。

ネットワークアクセス前に、その実行が最大何requestを消費し得るかを計算し、`data/edinetdb_quota/usage.json`へ予約します。予約はnetwork errorや途中失敗でも消費済みとして残す保守的な会計です。これにより `--force` の繰り返しで同じfingerprintを再取得しても、利用回数が見えなくなることを防ぎます。

`--plan-only` はnetwork accessもquota reservationも行いません。

## EDINET DBを使わないrepository

Data Platform Standard / MCP標準を採用することと、EDINET DBをdata sourceとして使うことは別です。books、WealthAudit、pal-atlas、cast event系はそれぞれの正本データに対してMCP/provenanceを実装し、上場企業財務がcontract上必要になるまでEDINET DB consumerにはしません。
