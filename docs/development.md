# Development and verification

この文書は、READMEに散在していたローカル実行・検証コマンドをまとめます。

リポジトリ全体の契約は [../AGENTS.md](../AGENTS.md)、正本境界は [architecture.md](architecture.md) を先に確認してください。

## Setup

```bash
uv sync
npm --prefix site ci
```

SECへアクセスする処理では、実運用者を識別できるUser-Agentを設定します。

```bash
: "${SEC_USER_AGENT:?set SEC_USER_AGENT to identify the real operator/contact}"
```

認証済みの市場需給取得には必要に応じて `JQUANTS_API_KEY`、`DATA_GO_KR_SERVICE_KEY` を環境変数で設定します。

## Fast checks by change type

### Documentation and public links

```bash
uv run python scripts/check_readme_pages_link.py
```

READMEやPagesの導線、公開URL、site-side contentへ影響する場合はsite buildも実行します。

```bash
GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model \
PUBLIC_BUILD_SHA=local \
npm --prefix site run build
```

### Canonical earnings / Data Platform

```bash
uv run python scripts/check_data_platform_standard.py
uv run --with "mcp>=2,<3" python scripts/check_mcp_contract.py
uv run python -m pytest -q \
  tests/test_earnings_ledger.py \
  tests/test_data_platform_standard.py
```

変更内容に応じてearnings lineage、publication、rejection、period、accounting-basis関連テストも追加します。

### Semiconductor infrastructure / CapEx canonical ledger

```bash
uv run python -m semicon.validate_canonical
uv run python -m semicon.round_trip
uv run python -m semicon.source_round_trip
uv run python -m pytest -q tests/test_semicon_canonical_ledger.py
```

派生/APIを変更した場合:

```bash
uv run python -m semicon.build_derived
uv run python -m semicon.build_api_v2
```

### Financial Database v3

```bash
uv run python scripts/build_financial_database_with_nand.py
uv run python -m pytest -q tests/test_financial_database.py
```

### NAND KPI

```bash
uv run python scripts/update_nand_kpis.py --offline
uv run python -m pytest -q tests/test_nand_kpi_pipeline.py
```

### Market positioning

外部認証なしで検証できる範囲を優先し、取得ロジック変更時は対応テストを実行します。

```bash
uv run python -m pytest -q tests/test_market_positioning_pipeline.py
```

認証情報が揃っている環境で実データ更新を行う場合:

```bash
uv run python scripts/update_market_positioning.py
```

### Unit contract

```bash
npm --prefix site run test:unit-audit
```

## Full local verification

広い変更、merge前の総合確認、複数データ経路へまたがる変更では次を基準にします。

```bash
uv run python scripts/build_primary_api.py
uv run python scripts/build_semiconductor_profit_api.py
uv run python scripts/build_semiconductor_resilience_api_v2.py
uv run python scripts/build_semiconductor_research_api.py
uv run python scripts/finalize_semiconductor_research_api.py
uv run python scripts/build_demand_api.py
uv run python scripts/update_nand_kpis.py --offline
uv run python scripts/build_financial_database_with_nand.py
uv run python scripts/check_readme_pages_link.py
uv run python scripts/build_model_snapshot.py
uv run python scripts/run_quant_audit.py \
  data/quant_audit/semiconductor_latest.json \
  --output site/public/data/quant-audit.json
uv run python scripts/check_data_platform_standard.py
uv run --with "mcp>=2,<3" python scripts/check_mcp_contract.py
uv run python -m pytest -q
npm --prefix site ci
npm --prefix site run test:unit-audit
GITHUB_REPOSITORY=KAFKA2306/semiconductor-earnings-model \
PUBLIC_BUILD_SHA=local \
npm --prefix site run build
```

`update_market_positioning.py` は認証済み外部sourceを使うため、必要なcredentialがある環境で実行します。

## Google Sheets infrastructure projection

Import:

```bash
uv run python -m semicon.ingest.google_sheets --spreadsheet-id <spreadsheet-id> --dry-run
uv run python -m semicon.ingest.google_sheets --spreadsheet-id <spreadsheet-id>
```

Projection:

```bash
uv run python -m semicon.export.google_sheets \
  --output-json data/derived/google_sheets_projection.json
```

Apply:

```bash
GOOGLE_OAUTH_ACCESS_TOKEN=... \
uv run python -m semicon.export.google_sheets \
  --spreadsheet-id <target-spreadsheet-id> \
  --apply
```

Google Sheetsはprojectionです。適用前後でcanonical ledgerの所有関係を変えません。

## Verification principles

- commandのexit codeだけで成功としない
- owner artifact、audit、manifest/hash、API、live surfaceなどbusiness postconditionを確認する
- generated fileを直接修正して正本変更の代用にしない
- testを通すためにdata-integrity gateを弱めない
- missing、stale、ambiguous、conflicting dataを0や推測値へ変換しない
- mergeとreleaseを別々に検証する
