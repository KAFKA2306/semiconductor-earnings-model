from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_earnings_rejection_reasons.py"
SPEC = importlib.util.spec_from_file_location("audit_earnings_rejection_reasons", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def rejected(event_id: str, reason: str, document_type: str = "4", source_adapter: str = "sec_edgar"):
    return {
        "event_id": event_id,
        "freshness": "REJECTED",
        "rejection_reason": reason,
        "document_type": document_type,
        "source_adapter": source_adapter,
    }


def test_known_not_earnings_reason_passes():
    result = module.audit_rejections([], [rejected("a", "NOT_EARNINGS_RELATED")])
    assert result["status"] == "PASS"
    assert result["reason_counts"] == {"NOT_EARNINGS_RELATED": 1}


def test_unknown_reason_fails_closed():
    result = module.audit_rejections([], [rejected("a", "MAYBE_OLD")])
    assert result["status"] == "FAIL"
    assert {issue["code"] for issue in result["issues"]} == {"UNKNOWN_REJECTION_REASON"}


def test_accepted_and_rejected_collision_fails():
    accepted = [{"event_id": "same"}]
    result = module.audit_rejections(accepted, [rejected("same", "NOT_EARNINGS_RELATED")])
    assert result["status"] == "FAIL"
    assert "EVENT_ACCEPTED_AND_REJECTED" in {issue["code"] for issue in result["issues"]}


def test_source_fetch_failed_only_allowed_for_6k():
    result = module.audit_rejections([], [rejected("a", "SOURCE_FETCH_FAILED", document_type="8-K")])
    assert result["status"] == "FAIL"
    assert "SOURCE_FETCH_FAILED_REASON_FORM_MISMATCH" in {issue["code"] for issue in result["issues"]}


def test_unverified_6k_only_allowed_for_6k():
    result = module.audit_rejections([], [rejected("a", "UNVERIFIED_6K", document_type="10-Q")])
    assert result["status"] == "FAIL"
    assert "UNVERIFIED_6K_REASON_FORM_MISMATCH" in {issue["code"] for issue in result["issues"]}


def test_duplicate_rejected_event_id_fails():
    rows = [
        rejected("dup", "NOT_EARNINGS_RELATED"),
        rejected("dup", "NOT_EARNINGS_RELATED"),
    ]
    result = module.audit_rejections([], rows)
    assert result["status"] == "FAIL"
    assert "DUPLICATE_REJECTED_EVENT_ID" in {issue["code"] for issue in result["issues"]}
