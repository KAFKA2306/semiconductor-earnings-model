# MCP

## Contract

このrepositoryはModel Context Protocol **2026-07-28** と公式Python SDK v2を基準に、read APIと明示的に有効化するcontrolled ontology actionsを提供します。

- Streamable HTTP endpoint: `POST /mcp`
- stateless HTTP: enabled
- protocol-level session: 依存しない
- capability discovery: `server/discover`
- tool catalog: `tools/list`
- canonical domain service: `src/data_platform.py`

実装: `src/mcp_server.py`

## Tools

| Tool | Purpose |
| --- | --- |
| `search_companies` | company id/name/ticker検索 |
| `get_company_earnings` | companyの最新accepted earnings event |
| `get_earnings_history` | companyのaccepted event履歴 |
| `get_evidence` | event evidenceとevidence audit |
| `get_lineage` | SHA-256 lineage manifest |
| `get_audit_status` | canonical audit群 |
| `get_publication_snapshot` | freshness gate後の公開snapshot |
| `get_data_quality` | audit/publication/lineage quality |
| `get_ontology_definition` | Ontology contract |
| `get_ontology_snapshot` | Object/Link snapshot |
| `search_ontology_objects` | Object検索 |
| `get_ontology_object` | Object 1件取得 |
| `get_ontology_neighbors` | Link traversal |
| `get_ontology_action_status` | Action実行可否・version |
| `get_ontology_action_log` | hash-chained Action Log |
| `execute_ontology_action` | overlay-only Action実行 |
| `rollback_ontology_action` | optimistic-concurrency rollback |

read系は `DataPlatformService` のdeterministic projectionを呼び、MCP側で値を再計算しません。Action系はcanonical sourceを変更せず、監査済みoverlayだけを書き換えます。

## Local run

公式SDK v2を一時environmentで起動する例:

```bash
uv run --with "mcp>=2,<3" python -m src.mcp_server
```

標準bindは `127.0.0.1:8000`、endpointは `/mcp` です。

## Security

- request body上限: 65,536 bytes
- Host/Origin validation: enabled
- local default allowlist: `127.0.0.1:*`, `localhost:*`
- production Host allowlist: `MCP_ALLOWED_HOSTS`
- production Origin allowlist: `MCP_ALLOWED_ORIGINS`
- secrets: environment only
- canonical source: read-only
- controlled actions: default disabled
- action enable gate: `ONTOLOGY_ACTIONS_ENABLED=1`
- actor/role: `ONTOLOGY_ACTION_ACTOR` / `ONTOLOGY_ACTION_ROLE=operator`
- REST action token: `ONTOLOGY_ACTION_TOKEN`
- server: stateless
- rate limit: deployment ingressでclient identityまたはsource IPごとに **60 requests/minute** を既定policyとして強制する

公開hostnameへdeployするときはHost/Origin allowlistを明示し、DNS rebinding保護を無効化しません。rate limitはMCP domain serviceではなくreverse proxy/API gateway等のingress境界で実施します。

## Verification

```bash
uv run python scripts/check_data_platform_standard.py
uv run python -m pytest tests/test_data_platform_standard.py -q
uv run --with "mcp>=2,<3" python scripts/check_mcp_contract.py
```

MCP contract testは `Client(mcp)` のin-memory transportを使い、`server/discover` negotiation、protocol version、`tools/list`、representative tool call、REST/CLI/service parityを確認します。

## Primary specifications

- MCP specification 2026-07-28: https://modelcontextprotocol.io/specification/2026-07-28
- Streamable HTTP: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
- Official Python SDK v2: https://py.sdk.modelcontextprotocol.io/
- Official SDK repository: https://github.com/modelcontextprotocol/python-sdk
