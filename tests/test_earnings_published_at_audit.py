from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_earnings_published_at.py"
SPEC = importlib.util.spec_from_file_location("audit_earnings_published_at", MODULE_PATH)
assert SPEC and SPEC.loader
published = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(published)


def payload(acceptance: str = "2026-08-07T20:06:32.000Z"):
    return {
        "filings": {
            "recent": {
                "accessionNumber": ["0000707549-26-000037"],
                "acceptanceDateTime": [acceptance],
            }
        }
    }


def event(published_at: str = "2026-08-07T20:06:32Z"):
    return {
        "event_id": "event-1",
        "company_id": "lam-research",
        "source_adapter": "sec_edgar",
        "cik": 707549,
        "accession_number": "0000707549-26-000037",
        "published_at": published_at,
    }


def test_exact_sec_acceptance_timestamp_passes():
    result = published.audit([event()], {707549: payload()})
    assert result["status"] == "PASS"
    assert result["items"][0]["delta_seconds"] == 0
    assert result["issues"] == []


def test_timezone_equivalent_timestamp_passes():
    result = published.audit([event("2026-08-07T16:06:32-04:00")], {707549: payload()})
    assert result["status"] == "PASS"
    assert result["items"][0]["ledger_published_at_utc"] == "2026-08-07T20:06:32Z"


def test_one_second_mismatch_fails_closed():
    result = published.audit([event("2026-08-07T20:06:33Z")], {707549: payload()})
    assert result["status"] == "FAIL"
    assert result["issues"][0]["code"] == "SEC_PUBLISHED_AT_MISMATCH"
    assert result["issues"][0]["delta_seconds"] == 1


def test_missing_accession_fails_closed():
    row = event()
    row["accession_number"] = None
    result = published.audit([row], {707549: payload()})
    assert result["status"] == "FAIL"
    assert result["issues"][0]["code"] == "MISSING_SEC_ACCESSION"


def test_accession_missing_from_primary_payload_fails_closed():
    result = published.audit([event()], {707549: {"filings": {"recent": {"accessionNumber": [], "acceptanceDateTime": []}}}})
    assert result["status"] == "FAIL"
    assert result["issues"][0]["code"] == "ACCESSION_NOT_FOUND_IN_SEC_RECENT"


def test_non_sec_event_is_not_reinterpreted_as_sec_timestamp():
    row = {"event_id": "tdnet-1", "source_adapter": "tdnet", "published_at": "2026-08-08T06:30:00Z"}
    result = published.audit([row], {})
    assert result["status"] == "PASS"
    assert result["sec_events_total"] == 0
    assert result["non_sec_events_not_independently_reverified"] == 1
