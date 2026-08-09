from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_daily_earnings_report.py"
SPEC = importlib.util.spec_from_file_location("build_daily_earnings_report", MODULE_PATH)
assert SPEC and SPEC.loader
report = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = report
SPEC.loader.exec_module(report)


def event(event_id: str, company: str, published_at: str) -> dict:
    return {
        "event_id": event_id,
        "company_id": company.lower().replace(" ", "-"),
        "company_name": company,
        "document_type": "10-Q",
        "published_at": published_at,
        "source_url": "https://www.sec.gov/Archives/example",
        "title": "10-Q filing",
        "freshness": "PASS",
    }


def test_report_window_is_0700_jst_and_end_exclusive():
    start, end = report.report_window(datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc))
    assert end.astimezone(report.JST).isoformat() == "2026-08-09T07:00:00+09:00"
    assert start.astimezone(report.JST).isoformat() == "2026-08-08T07:00:00+09:00"
    rows = [
        event("start", "AMD", "2026-08-07T22:00:00Z"),
        event("end", "NVIDIA", "2026-08-08T22:00:00Z"),
    ]
    selected = report.select_events(rows, start, end)
    assert [row["event_id"] for row in selected] == ["start"]


def test_stale_nvidia_fixture_is_not_promoted_to_daily_report():
    start, end = report.report_window(datetime(2026, 8, 9, 0, 7, tzinfo=timezone.utc))
    rows = [
        event("stale-nvidia", "NVIDIA", "2026-05-21T20:00:00Z"),
        event("fresh-amd", "AMD", "2026-08-08T12:00:00Z"),
    ]
    selected = report.select_events(rows, start, end)
    assert [row["event_id"] for row in selected] == ["fresh-amd"]


def test_non_pass_event_fails_closed():
    start, end = report.report_window(datetime(2026, 8, 9, 0, 7, tzinfo=timezone.utc))
    row = event("bad", "AMD", "2026-08-08T12:00:00Z")
    row["freshness"] = "REJECTED"
    try:
        report.select_events([row], start, end)
    except RuntimeError as exc:
        assert "freshness PASS" in str(exc)
    else:
        raise AssertionError("non-PASS accepted event must fail closed")


def test_audit_fail_stops_report():
    try:
        report.validate_audit(
            {"status": "FAIL", "issues": [], "run_at": "2026-08-08T20:00:00Z"}
        )
    except RuntimeError as exc:
        assert "not PASS" in str(exc)
    else:
        raise AssertionError("failed ledger audit must stop daily report")


def test_collector_and_daily_report_workflows_are_separated():
    collector = (ROOT / ".github/workflows/earnings-ledger-update.yml").read_text(
        encoding="utf-8"
    )
    daily = (ROOT / ".github/workflows/earnings-daily-report.yml").read_text(
        encoding="utf-8"
    )
    assert "Discard collector-generated report artifacts" in collector
    assert 'cron: "7 7 * * *"' in daily
    assert 'timezone: "Asia/Tokyo"' in daily
    assert "SEC_USER_AGENT" not in daily
    assert "scripts/earnings_ledger.py" not in daily
