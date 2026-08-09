from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_earnings_semantic_duplicates.py"
SPEC = importlib.util.spec_from_file_location("audit_earnings_semantic_duplicates", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def sec_event(event_id: str, report_date: str | None = "2026-06-30", document_type: str = "10-Q"):
    return {
        "event_id": event_id,
        "company_id": "amd",
        "source_adapter": "sec_edgar",
        "report_date": report_date,
        "document_type": document_type,
    }


def test_semantic_key_uses_primary_report_date_without_fiscal_inference():
    assert mod.semantic_key(sec_event("a")) == "amd|2026-06-30|10-Q"


def test_same_company_period_and_document_type_fails_even_with_different_event_ids():
    result = mod.audit([sec_event("a"), sec_event("b")])
    assert result["status"] == "FAIL"
    assert result["duplicate_count"] == 1
    assert result["duplicates"][0]["code"] == "DUPLICATE_SEMANTIC_EARNINGS_EVENT"


def test_different_document_types_are_not_collapsed():
    result = mod.audit([sec_event("a", document_type="8-K"), sec_event("b", document_type="10-Q")])
    assert result["status"] == "PASS"
    assert result["duplicate_count"] == 0


def test_missing_primary_report_date_fails_closed_without_inference():
    result = mod.audit([sec_event("a", report_date=None)])
    assert result["status"] == "FAIL"
    assert result["events_with_primary_period_key"] == 0
    assert result["unkeyable_sec_event_count"] == 1
    assert result["unkeyable_sec_events"][0] == {
        "code": "UNKEYABLE_SEC_EARNINGS_EVENT",
        "event_id": "a",
        "missing_fields": ["report_date"],
    }


def test_missing_company_and_document_type_are_reported_without_inference():
    event = sec_event("a")
    event["company_id"] = ""
    event["document_type"] = None
    result = mod.audit([event])
    assert result["status"] == "FAIL"
    assert result["unkeyable_sec_events"][0]["missing_fields"] == ["company_id", "document_type"]


def test_non_sec_event_is_outside_this_gate():
    event = {
        "event_id": "tdnet-a",
        "company_id": "tokyo-electron",
        "source_adapter": "tdnet_public",
        "document_type": "TDNET_DISCLOSURE",
        "report_date": "2026-06-30",
    }
    result = mod.audit([event])
    assert mod.semantic_key(event) is None
    assert result["status"] == "PASS"
    assert result["sec_events_total"] == 0
    assert result["unkeyable_sec_event_count"] == 0
