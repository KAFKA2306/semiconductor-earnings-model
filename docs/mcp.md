# MCP

## Contract

このrepositoryはModel Context Protocol **2026-07-28** と公式Python SDK v2を基準に、read-only MCP serverを提供します。

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

いずれも `DataPlatformService` のread-only projectionを呼び、MCP側で値を再計算しません。

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
- tools: read-only
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
