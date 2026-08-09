from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_earnings_ledger_publication.py"
SPEC = importlib.util.spec_from_file_location("earnings_publication", MODULE_PATH)
assert SPEC and SPEC.loader
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)


def test_require_pass_rejects_failed_audit():
    try:
        publication.require_pass("x", {"status": "FAIL", "issues": []})
    except SystemExit as exc:
        assert "not PASS" in str(exc)
    else:
        raise AssertionError("failed audit must stop publication")


def test_require_pass_rejects_issues_even_without_status():
    try:
        publication.require_pass("x", {"issues": [{"code": "BAD"}]})
    except SystemExit as exc:
        assert "contains issues" in str(exc)
    else:
        raise AssertionError("audit issues must stop publication")


def test_publication_freshness_boundary_is_exactly_24_hours():
    run_at = datetime(2026, 8, 9, 2, 0, tzinfo=timezone.utc)
    on_boundary = {"event_id": "x", "published_at": (run_at - timedelta(hours=24)).isoformat()}
    expired = {
        "event_id": "y",
        "published_at": (run_at - timedelta(hours=24, microseconds=1)).isoformat(),
    }
    assert publication.is_fresh_for_publication(on_boundary, run_at)
    assert not publication.is_fresh_for_publication(expired, run_at)


def test_publication_rejects_future_event():
    run_at = datetime(2026, 8, 9, 2, 0, tzinfo=timezone.utc)
    event = {"event_id": "future", "published_at": (run_at + timedelta(seconds=1)).isoformat()}
    try:
        publication.is_fresh_for_publication(event, run_at)
    except SystemExit as exc:
        assert "future event" in str(exc)
    else:
        raise AssertionError("future events must fail closed")


def test_current_ledger_build_is_fail_closed_and_primary_only():
    payload = publication.build_publication()
    assert payload["audit_status"] == "PASS"
    assert payload["contract"] == {
        "primary_sources_only": True,
        "freshness_gate_hours": 24,
        "publication_rechecks_freshness": True,
        "fail_closed": True,
        "unverified_values_published": False,
    }
    assert payload["accepted_events_total"] == len(payload["events"])
    assert payload["ledger_accepted_events_total"] == (
        payload["accepted_events_total"] + payload["expired_events_total"]
    )
    assert all(event["freshness"] == "PASS" for event in payload["events"])
    assert all(event["source_url"].startswith("https://") for event in payload["events"])


def test_publication_contains_no_financial_value_fields():
    payload = publication.build_publication()
    forbidden = {"revenue", "eps", "operating_income", "guidance", "consensus"}
    for event in payload["events"]:
        assert forbidden.isdisjoint(event)
