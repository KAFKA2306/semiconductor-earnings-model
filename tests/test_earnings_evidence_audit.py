from __future__ import annotations

import importlib.util
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


def test_audit_accepts_valid_primary_content_hash():
    row = {
        "event_id": "evt-1",
        "source_url": "https://www.sec.gov/Archives/example",
        "source_content_sha256": "a" * 64,
        "source_content_bytes": 123,
    }
    assert evidence.audit_evidence([row]) == []


def test_audit_rejects_non_primary_empty_and_bad_hash():
    row = {
        "event_id": "evt-1",
        "source_url": "https://example.com/news",
        "source_content_sha256": "bad",
        "source_content_bytes": 0,
    }
    codes = {issue["code"] for issue in evidence.audit_evidence([row])}
    assert codes == {"INVALID_SOURCE_SHA256", "EMPTY_SOURCE_CONTENT", "NON_PRIMARY_DOMAIN"}


def test_verify_event_hashes_exact_returned_bytes(monkeypatch):
    raw = b"primary-source-body\x00\x01"

    def fake_request(url: str, user_agent: str, retries: int = 3, timeout: int = 30):
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
            "source_url": "https://www.release.tdnet.info/inbs/example.pdf",
        },
        "test-agent",
        datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc),
    )
    assert row["source_content_bytes"] == len(raw)
    assert row["source_content_sha256"] == "f9c05098b6fcacd1e58ad878d5acf94d48dd4f269feb955969c9473f02b16ae6"
    assert row["content_type"] == "application/pdf"
