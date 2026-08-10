from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_earnings_rejection_reasons.py"
SPEC = importlib.util.spec_from_file_location("audit_earnings_rejection_reasons", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def rejected(
    event_id: str,
    reason: str,
    document_type: str = "4",
    source_adapter: str = "sec_edgar",
):
    row = {
        "schema_version": "earnings-event.v1",
        "event_id": event_id,
        "company_id": "kla",
        "company_name": "KLA",
        "freshness": "REJECTED",
        "rejection_reason": reason,
        "document_type": document_type,
        "published_at": "2026-08-07T20:05:03Z",
        "published_timezone": "UTC",
        "retrieved_at": "2026-08-08T18:59:34Z",
        "source_adapter": source_adapter,
        "source_url": "https://www.sec.gov/Archives/edgar/data/319201/example-index.html",
        "accession_number": "0001193125-26-340226",
        "cik": 319201,
    }
    if source_adapter == "tdnet_public":
        row["source_url"] = "https://www.release.tdnet.info/inbs/example.pdf"
        row["published_timezone"] = "Asia/Tokyo"
        row["security_code"] = "6146"
        row.pop("accession_number", None)
        row.pop("cik", None)
    return row


def test_known_not_earnings_reason_passes():
    result = module.audit_rejections([], [rejected("a", "NOT_EARNINGS_RELATED")])
    assert result["status"] == "PASS"
    assert result["schema_version"] == "earnings-rejection-reason-audit.v2"
    assert result["reason_counts"] == {"NOT_EARNINGS_RELATED": 1}


def test_unknown_reason_fails_closed():
    result = module.audit_rejections([], [rejected("a", "MAYBE_OLD")])
    assert result["status"] == "FAIL"
    assert "UNKNOWN_REJECTION_REASON" in {issue["code"] for issue in result["issues"]}


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


def test_missing_rejection_provenance_field_fails_closed():
    row = rejected("a", "NOT_EARNINGS_RELATED")
    row.pop("company_id")
    result = module.audit_rejections([], [row])
    assert result["status"] == "FAIL"
    assert "MISSING_REJECTION_PROVENANCE_FIELD" in {issue["code"] for issue in result["issues"]}


def test_missing_published_timezone_fails_closed():
    row = rejected("a", "NOT_EARNINGS_RELATED")
    row.pop("published_timezone")
    result = module.audit_rejections([], [row])
    codes = {issue["code"] for issue in result["issues"]}
    assert result["status"] == "FAIL"
    assert "MISSING_REJECTION_PROVENANCE_FIELD" in codes
    assert "REJECTION_PUBLISHED_TIMEZONE_MISMATCH" in codes


def test_source_adapter_domain_mismatch_fails_closed():
    row = rejected("a", "NOT_EARNINGS_RELATED")
    row["source_url"] = "https://example.com/not-primary"
    result = module.audit_rejections([], [row])
    assert result["status"] == "FAIL"
    assert "REJECTION_SOURCE_DOMAIN_MISMATCH" in {issue["code"] for issue in result["issues"]}


def test_retrieved_before_published_fails_closed():
    row = rejected("a", "NOT_EARNINGS_RELATED")
    row["retrieved_at"] = "2026-08-07T19:00:00Z"
    result = module.audit_rejections([], [row])
    assert result["status"] == "FAIL"
    assert "REJECTED_RETRIEVED_BEFORE_PUBLISHED" in {issue["code"] for issue in result["issues"]}


def test_timezone_less_published_at_fails_closed():
    row = rejected("a", "NOT_EARNINGS_RELATED")
    row["published_at"] = "2026-08-07T20:05:03"
    result = module.audit_rejections([], [row])
    assert result["status"] == "FAIL"
    assert "INVALID_REJECTED_PUBLISHED_AT" in {issue["code"] for issue in result["issues"]}


def test_sec_rejection_requires_accession_and_cik():
    row = rejected("a", "NOT_EARNINGS_RELATED")
    row.pop("accession_number")
    result = module.audit_rejections([], [row])
    assert result["status"] == "FAIL"
    assert "MISSING_REJECTION_SOURCE_IDENTITY" in {issue["code"] for issue in result["issues"]}


def test_sec_rejection_timezone_must_be_utc():
    row = rejected("a", "NOT_EARNINGS_RELATED")
    row["published_timezone"] = "America/New_York"
    result = module.audit_rejections([], [row])
    assert result["status"] == "FAIL"
    assert "REJECTION_PUBLISHED_TIMEZONE_MISMATCH" in {issue["code"] for issue in result["issues"]}


def test_tdnet_rejection_requires_security_code_and_primary_domain():
    row = rejected("a", "NOT_EARNINGS_RELATED", document_type="TDNET_DISCLOSURE", source_adapter="tdnet_public")
    result = module.audit_rejections([], [row])
    assert result["status"] == "PASS"
    row.pop("security_code")
    result = module.audit_rejections([], [row])
    assert result["status"] == "FAIL"
    assert "MISSING_REJECTION_SOURCE_IDENTITY" in {issue["code"] for issue in result["issues"]}


def test_tdnet_rejection_timezone_must_be_asia_tokyo():
    row = rejected("a", "NOT_EARNINGS_RELATED", document_type="TDNET_DISCLOSURE", source_adapter="tdnet_public")
    row["published_timezone"] = "UTC"
    result = module.audit_rejections([], [row])
    assert result["status"] == "FAIL"
    assert "REJECTION_PUBLISHED_TIMEZONE_MISMATCH" in {issue["code"] for issue in result["issues"]}
