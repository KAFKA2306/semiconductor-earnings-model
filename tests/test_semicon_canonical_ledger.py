from __future__ import annotations

from pathlib import Path

from semicon.build_derived import build as build_derived
from semicon.export.google_sheets import build_projection
from semicon.ingest.google_sheets import build_import, classify_sheet, persist_import
from semicon.ledger import DERIVED_METRICS, dedupe_or_conflict, write_json
from semicon.round_trip import validate_round_trip
from semicon.source_round_trip import validate_source_round_trip
from semicon.validate_canonical import validate


def empty_root(tmp_path: Path) -> Path:
    write_json(tmp_path / "data/primary/entities.json", {"entities": []})
    return tmp_path


def snapshot() -> dict:
    return {
        "schema_version": "google-sheets-raw.v1",
        "spreadsheet_id": "test-sheet",
        "source_name": "google_sheets",
        "imported_at": "2026-09-22T00:00:00Z",
        "source_sha256": "abc123",
        "sheets": [
            {"name": "Company_Master", "rows": [
                ["entity_id", "company_name", "ticker", "country", "currency"],
                ["US:AAA", "AAA Corp", "AAA", "US", "USD"],
            ]},
            {"name": "Annual_Financials", "rows": [
                ["entity_id", "period_start", "period_end", "fiscal_year", "period_type", "currency", "revenue_mm", "capex_mm", "free_cash_flow_mm", "source_url", "source_doc_id", "native_concept"],
                ["US:AAA", "2025-01-01", "2025-12-31", "FY2025", "FY", "USD", 1000, 0, 120, "https://www.sec.gov/example", "0001", "Revenue"],
                ["US:AAA", "2024-01-01", "2024-12-31", "FY2024", "FY", "USD", 900, None, 100, "https://www.sec.gov/example2", "0002", "Revenue"],
            ]},
            {"name": "CapEx_Projects", "rows": [
                ["project_id", "event_id", "event_type", "entity_id", "project_name", "announcement_date", "capex_plan_low", "capex_plan_high", "currency", "capacity_before", "capacity_after", "capacity_unit", "status", "source_url", "source_doc_id"],
                ["P1", "E1", "capacity_expansion", "US:AAA", "Fab A", "2026-01-01", 100, 120, "USD", 1, 2, "x", "announced", "https://example.com/ir", "ir-1"],
            ]},
            {"name": "Facilities", "rows": [
                ["facility_id", "entity_id", "facility_name", "country", "fiscal_year", "source_url", "source_doc_id"],
                ["F1", "US:AAA", "Fab A", "US", "FY2025", "https://example.com/10k", "10k-1"],
            ]},
            {"name": "Orders_Backlog", "rows": [
                ["record_id", "entity_id", "fiscal_year", "segment", "orders_received", "order_backlog", "currency", "source_url", "source_doc_id"],
                ["B1", "US:AAA", "FY2025", "semiconductor", 50, 70, "USD", "https://example.com/10k", "10k-1"],
            ]},
            {"name": "Customer_Commitments", "rows": [
                ["commitment_id", "entity_id", "customer_name", "commitment_type", "amount", "period_start", "period_end", "source_url", "source_doc_id"],
                ["C1", "US:AAA", "Customer X", "long_term_agreement", 20, "2026-01-01", "2028-12-31", "https://example.com/lta", "lta-1"],
            ]},
            {"name": "Economics_Model", "rows": [["entity_id", "required_revenue"], ["US:AAA", 137]]},
        ],
    }


def test_all_handoff_tabs_classify():
    canonical = {"Company_Master", "Latest_CapEx", "CapEx_Plans", "Project_CapEx", "Facilities", "Orders_Backlog", "Main_Customers"}
    derived = {"Decision_Evidence", "Economics_Model", "Project_Lifecycle"}
    metadata = {"README", "Coverage", "Data_Dictionary", "Sources", "US_Index_Master", "Ingestion_Status", "Decision_Framework", "Data_Quality"}
    assert all(classify_sheet(name) == "canonical" for name in canonical)
    assert all(classify_sheet(name) == "derived" for name in derived)
    assert all(classify_sheet(name) == "metadata" for name in metadata)
    assert classify_sheet("Dashboard") == "presentation"


def test_null_is_not_zero_and_derived_does_not_enter_canonical(tmp_path: Path):
    root = empty_root(tmp_path)
    report, payload = build_import(snapshot(), root=root)
    facts = payload["facts"]
    assert report["invalid_rows"] == 0
    assert any(f["metric"] == "capex" and f["value"] == 0 for f in facts)
    assert not any(f["metric"] == "capex" and f["period_end"] == "2024-12-31" for f in facts)
    assert not any(f["metric"] in DERIVED_METRICS for f in facts)


def test_duplicate_adds_provenance_but_conflict_stops():
    base = {
        "fact_id": "f1", "entity_id": "US:AAA", "metric": "revenue", "value": 100, "unit": "USD_million",
        "period_start": "2025-01-01", "period_end": "2025-12-31", "native_concept": "Revenue",
        "source_system": "sec_edgar", "provenance": [{"import_source": "sec_edgar"}],
    }
    same = {**base, "source_system": "google_sheets", "provenance": [{"import_source": "google_sheets"}]}
    merged, dupes, conflicts = dedupe_or_conflict("fact", [base], [same])
    assert dupes == 1 and not conflicts and len(merged[0]["provenance"]) == 2
    _, _, conflicts = dedupe_or_conflict("fact", [base], [{**same, "value": 101}])
    assert len(conflicts) == 1 and "existing_priority=1" in conflicts[0].reason


def test_round_trip_and_validation(tmp_path: Path):
    root = empty_root(tmp_path)
    report, payload = build_import(snapshot(), root=root)
    assert report["conflicts"] == 0 and report["invalid_rows"] == 0
    persist_import(snapshot(), payload, root=root)
    build_derived(root)
    projection = build_projection(root)
    assert {"Company_Master", "Annual_Financials", "CapEx_Projects", "Facilities", "Orders_Backlog", "Customer_Commitments"}.issubset(projection)
    result = validate(root)
    assert result["status"] == "PASS", result
    round_trip = validate_round_trip(root)
    assert round_trip["status"] == "PASS", round_trip


def test_archived_live_google_sheet_is_replayable():
    root = Path(__file__).resolve().parents[1]
    matches = list((root / "data/raw/google_sheets_import").glob("*/**/source.xlsx"))
    if not matches:
        return
    from semicon.ingest.google_sheets import parse_xlsx_bytes
    snap = parse_xlsx_bytes(matches[0].read_bytes(), spreadsheet_id="replay", imported_at="1970-01-01T00:00:00Z")
    assert len(snap["sheets"]) == 10
    assert sum(max(len(s["rows"]) - 1, 0) for s in snap["sheets"]) == 328


def test_replay_same_sheet_row_does_not_multiply_provenance(tmp_path: Path):
    root = empty_root(tmp_path)
    first = snapshot()
    report, payload = build_import(first, root=root)
    assert report["conflicts"] == 0
    persist_import(first, payload, root=root)

    second = snapshot()
    second["imported_at"] = "2026-09-22T09:00:00Z"
    report2, payload2 = build_import(second, root=root)
    assert report2["conflicts"] == 0
    event = next(row for row in payload2["events"] if row["event_id"] == "E1")
    project = next(row for row in payload2["projects"] if row["project_id"] == "P1")
    assert len(event["provenance"]) == 1
    assert len(project["provenance"]) == 1


def test_source_url_generates_stable_primary_document_identity(tmp_path: Path):
    root = empty_root(tmp_path)
    source = snapshot()
    # Remove an explicit document id while retaining the primary source URL.
    header = source["sheets"][2]["rows"][0]
    row = source["sheets"][2]["rows"][1]
    row[header.index("source_doc_id")] = None
    report, payload = build_import(source, root=root)
    assert report["conflicts"] == 0
    event = next(row for row in payload["events"] if row["event_id"] == "E1")
    project = next(row for row in payload["projects"] if row["project_id"] == "P1")
    assert event["source_doc_id"].startswith("urlsha256:")
    assert project["source_doc_id"] == event["source_doc_id"]
    assert event["provenance"][0]["import_record_id"] == "gsheet:test-sheet:CapEx_Projects:2"


def test_live_source_semantics_survive_regeneration():
    root = Path(__file__).resolve().parents[1]
    matches = list((root / "data/raw/google_sheets_import").glob("*/**/source.xlsx"))
    if not matches:
        return
    result = validate_source_round_trip(root)
    assert result["status"] == "PASS", result
