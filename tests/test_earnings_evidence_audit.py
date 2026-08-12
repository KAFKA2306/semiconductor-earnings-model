from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_earnings_evidence.py"
SPEC = importlib.util.spec_from_file_location("audit_earnings_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evidence
SPEC.loader.exec_module(evidence)


def test_select_window_events_is_strict_and_pass_only():
    state = {
        "window_start": "2026-08-07T09:00:00Z",
        "window_end": "2026-08-08T09:00:00Z",
    }
    rows = [
        {"event_id": "a", "freshness": "PASS", "published_at": "2026-08-07T09:00:00Z"},
        {"event_id": "b", "freshness": "PASS", "published_at": "2026-08-08T09:00:00Z"},
        {"event_id": "c", "freshness": "REJECTED", "published_at": "2026-08-08T08:00:00Z"},
        {"event_id": "d", "freshness": "PASS", "published_at": "2026-08-07T08:59:59Z"},
    ]
    selected = evidence.select_window_events(rows, state)
    assert [row["event_id"] for row in selected] == ["a", "b"]


def test_required_verified_metric_event_survives_window_rollover():
    state = {
        "window_start": "2026-08-11T09:00:00Z",
        "window_end": "2026-08-12T09:00:00Z",
    }
    rows = [
        {"event_id": "old-metric", "freshness": "PASS", "published_at": "2026-08-07T20:06:32Z"},
        {"event_id": "current", "freshness": "PASS", "published_at": "2026-08-12T08:00:00Z"},
        {"event_id": "rejected", "freshness": "REJECTED", "published_at": "2026-08-07T20:06:32Z"},
    ]
    selected = evidence.select_window_events(rows, state, {"old-metric", "rejected"})
    assert [row["event_id"] for row in selected] == ["old-metric", "current"]


def test_required_metric_ids_only_come_from_clean_pass_document():
    clean = {
        "status": "PASS",
        "issues": [],
        "metrics": [{"event_id": "evt-1"}, {"event_id": "evt-2"}],
    }
    assert evidence.required_metric_event_ids(clean) == {"evt-1", "evt-2"}
    dirty = {**clean, "issues": ["bad"]}
    assert evidence.required_metric_event_ids(dirty) == set()


def test_reusable_evidence_requires_same_event_and_valid_digest():
    event = {"event_id": "evt-1", "company_id": "lam-research", "document_type": "10-K"}
    proof = {
        "event_id": "evt-1",
        "company_id": "lam-research",
        "document_type": "10-K",
        "status": "PASS",
        "source_content_sha256": "a" * 64,
        "source_content_bytes": 123,
    }
    assert evidence.reusable_evidence(event, proof) is True
    assert evidence.reusable_evidence(event, {**proof, "company_id": "other"}) is False
    assert evidence.reusable_evidence(event, {**proof, "source_content_sha256": "bad"}) is False


def test_audit_accepts_valid_primary_content_hash():
    row = {
        "event_id": "evt-1",
        "evidence_url": "https://data.sec.gov/submissions/CIK0000002488.json",
        "evidence_scope": "SEC_SUBMISSIONS_JSON",
        "source_content_sha256": "a" * 64,
        "source_content_bytes": 123,
    }
    assert evidence.audit_evidence([row]) == []


def test_audit_rejects_non_primary_empty_and_bad_hash():
    row = {
        "event_id": "evt-1",
        "evidence_url": "https://example.com/news",
        "evidence_scope": "UNKNOWN",
        "source_content_sha256": "bad",
        "source_content_bytes": 0,
    }
    codes = {issue["code"] for issue in evidence.audit_evidence([row])}
    assert codes == {
        "INVALID_SOURCE_SHA256",
        "EMPTY_SOURCE_CONTENT",
        "NON_PRIMARY_DOMAIN",
        "INVALID_EVIDENCE_SCOPE",
    }


def test_tdnet_verify_event_hashes_exact_returned_bytes(monkeypatch):
    raw = b"primary-source-body\x00\x01"

    def fake_request(url: str, user_agent: str, retries: int = 1, timeout: int = 30):
        assert url == "https://www.release.tdnet.info/inbs/example.pdf"
        assert user_agent == "test-agent"
        return raw, "application/pdf"

    monkeypatch.setattr(evidence, "request_bytes", fake_request)
    row = evidence.verify_event(
        {
            "event_id": "evt-2",
            "company_id": "tokyo-electron",
            "document_type": "TDNET_DISCLOSURE",
            "published_at": "2026-08-08T06:30:00Z",
            "source_adapter": "tdnet_public",
            "source_url": "https://www.release.tdnet.info/inbs/example.pdf",
        },
        "test-agent",
        datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc),
    )
    assert row["evidence_scope"] == "TDNET_DISCLOSURE_DOCUMENT"
    assert row["source_content_bytes"] == len(raw)
    assert row["source_content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert row["content_type"] == "application/pdf"


def test_sec_verify_event_hashes_submissions_and_checks_accession(monkeypatch):
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000707549-26-000037"],
            }
        }
    }
    raw = json.dumps(payload).encode("utf-8")

    def fake_request(url: str, user_agent: str, retries: int = 1, timeout: int = 30):
        assert url == "https://data.sec.gov/submissions/CIK0000707549.json"
        return raw, "application/json"

    monkeypatch.setattr(evidence, "request_bytes", fake_request)
    row = evidence.verify_event(
        {
            "event_id": "evt-sec",
            "company_id": "lam-research",
            "document_type": "10-K",
            "published_at": "2026-08-07T20:06:32Z",
            "source_adapter": "sec_edgar",
            "source_url": "https://www.sec.gov/Archives/example-index.html",
            "cik": 707549,
            "accession_number": "0000707549-26-000037",
        },
        "test-agent",
        datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc),
    )
    assert row["evidence_scope"] == "SEC_SUBMISSIONS_JSON"
    assert row["evidence_url"] == "https://data.sec.gov/submissions/CIK0000707549.json"
    assert row["source_content_sha256"] == hashlib.sha256(raw).hexdigest()
