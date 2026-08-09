from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_earnings_semantic_duplicates.py"
SPEC = importlib.util.spec_from_file_location("audit_earnings_semantic_duplicates", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def sec_event(event_id: str, **overrides):
    row = {
        "event_id": event_id,
        "company_id": "amd",
        "source_adapter": "sec_edgar",
        "report_date": "2026-06-30",
        "document_type": "10-Q",
    }
    row.update(overrides)
    return row


def test_missing_primary_report_date_fails_closed_instead_of_being_silently_skipped():
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
    result = mod.audit([sec_event("a", company_id="", document_type=None)])
    assert result["status"] == "FAIL"
    assert result["unkeyable_sec_events"][0]["missing_fields"] == ["company_id", "document_type"]


def test_one_unkeyable_sec_event_makes_the_whole_gate_fail():
    result = mod.audit([sec_event("a"), sec_event("b", report_date=None)])
    assert result["sec_events_total"] == 2
    assert result["events_with_primary_period_key"] == 1
    assert result["unkeyable_sec_event_count"] == 1
    assert result["status"] == "FAIL"


def test_non_sec_event_remains_outside_this_sec_specific_gate():
    event = {
        "event_id": "tdnet-a",
        "company_id": "tokyo-electron",
        "source_adapter": "tdnet_public",
        "document_type": "TDNET_DISCLOSURE",
        "report_date": "2026-06-30",
    }
    result = mod.audit([event])
    assert result["status"] == "PASS"
    assert result["sec_events_total"] == 0
    assert result["unkeyable_sec_event_count"] == 0
