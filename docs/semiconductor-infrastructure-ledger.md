# Semiconductor Infrastructure Ledger

`semiconductor-earnings-model` is the only repository-of-record for semiconductor infrastructure evidence and earnings projections.

Primary Source -> raw archive -> canonical infrastructure ledger -> derived project economics / decision evidence / earnings inputs -> earnings model -> API / Pages / Google Sheets.

Google Sheets is an import/export surface, not the source of truth after migration.

## Canonical ownership

`data/earnings_ledger/` remains the canonical event ledger for newly published earnings disclosures and its fail-close freshness/audit contract is unchanged. `data/canonical/` owns normalized infrastructure facts, CapEx projects, facilities, customer commitments and order/backlog evidence.

## Invariants

Source priority is SEC/EDINET raw filing > company primary IR > existing canonical > imported Google Sheets/XLSX. Matching imports add provenance only. Mismatches never overwrite higher-priority data and stop with a conflict report.

NULL is not zero. Blank cells never become zero; undisclosed/non-applicable are distinct; stale observations keep their original fiscal year; missing periods, units, source identity and native concepts are not guessed. Derived ratios/economics never enter `facts.jsonl`.

## Commands

Import:
```bash
uv run python -m semicon.ingest.google_sheets --spreadsheet-id 1lClRXXTUW8-yJtC_PxwvzQ03llC08nW6ovMzQMk5XDQ
uv run python -m semicon.ingest.google_sheets --spreadsheet-id 1lClRXXTUW8-yJtC_PxwvzQ03llC08nW6ovMzQMk5XDQ --dry-run
```

Archived workbooks use the same parser with `--xlsx /path/to/workbook.xlsx`.

Derived/API/validation:
```bash
uv run python -m semicon.build_derived
uv run python -m semicon.build_api_v2
uv run python -m semicon.validate_canonical
uv run python -m semicon.round_trip
uv run python -m semicon.source_round_trip
uv run python -m pytest -q tests/test_semicon_canonical_ledger.py
```

Google Sheets projection:
```bash
uv run python -m semicon.export.google_sheets --output-json data/derived/google_sheets_projection.json

# Apply regenerated view tabs to a target Sheet. The ledger remains canonical.
GOOGLE_OAUTH_ACCESS_TOKEN=... uv run python -m semicon.export.google_sheets \
  --spreadsheet-id <target-spreadsheet-id> \
  --apply
```

`semicon.round_trip` checks canonical -> generated Sheet projection -> canonical.
`semicon.source_round_trip` independently checks that the archived original live Sheet's
entity/index/CapEx/source semantics survive canonicalization and regeneration.

The deterministic projection contains Company_Master, Annual_Financials, CapEx_Projects, Facilities, Orders_Backlog, Customer_Commitments, Project_Lifecycle, Project_Economics, Decision_Evidence, Sources and Coverage. Authenticated application of this payload to Google Sheets belongs at the connected Google Drive/Sheets boundary.

## Sheet classification

Canonical: Company_Master, Issuer_Master, Latest_CapEx, Annual_Financials, Financials, CapEx_Plans, CapEx_Events, Project_CapEx, CapEx_Projects, Facilities, Orders_Backlog, Main_Customers, Customer_Commitments, Demand_Commitments, Capacity_Metrics.

Derived: Decision_Evidence, Decision_View, Economics_Model, Project_Lifecycle.

Metadata/QA: README, Coverage, Data_Dictionary, Data_Quality, Sources, Ingestion_Status, US_Index_Master, Index_Membership, Decision_Framework.

Presentation: Dashboard.

## Migration source status 2026-09-22

The live workbook has 10 tabs and 328 non-header rows: 142 issuer rows, 162 index-membership rows, five CapEx events and three source rows. Financial/commitment/capacity/decision tabs are header-only.

Google's XLSX export is not byte-stable, so import identity uses a semantic content hash. Current semantic SHA-256 is `a5ab21206c397dcf7d7603bb32c0a8e7cd6636d2b4efedbe3d88ff5c8a79a8dd`; the archived XLSX binary SHA-256 is `101e506d876da0b8794722dd4d99116c2ab91def1c6ed1d44bf6b8a24f631d90`.

The handoff names `semiconductor_capex_database_v0_4.xlsx` with 19 tabs, but the exact binary is not available in the current container or accessible file library. Data existing only there is not fabricated. `data/raw/import_sources.json` records it as missing until the exact workbook can be archived and replayed.
