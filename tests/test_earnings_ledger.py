from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "earnings_ledger.py"
SPEC = importlib.util.spec_from_file_location("earnings_ledger", MODULE_PATH)
assert SPEC and SPEC.loader
ledger = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ledger
SPEC.loader.exec_module(ledger)


def test_window_boundaries_are_inclusive():
    end = datetime(2026, 8, 8, 4, 0, tzinfo=timezone.utc)
    window = ledger.Window(start=end - timedelta(hours=24), end=end)
    assert ledger.in_window(window.start, window)
    assert ledger.in_window(window.end, window)
    assert not ledger.in_window(window.start - timedelta(microseconds=1), window)


def test_parse_dt_requires_timezone():
    try:
        ledger.parse_dt("2026-08-08T12:00:00")
    except ValueError as exc:
        assert "timezone missing" in str(exc)
    else:
        raise AssertionError("timezone-less timestamps must be rejected")


def test_6k_gate_is_strict():
    good = "<html><body>Quarterly results. Revenue increased and operating income improved.</body></html>"
    bad = "<html><body>Investor presentation about strategy and products.</body></html>"
    assert ledger.looks_like_earnings_6k(good)
    assert not ledger.looks_like_earnings_6k(bad)


def test_tdnet_parser_extracts_time_code_company_title_and_href():
    sample = """
    <table>
      <tr>
        <td class="kjTime">15:30</td>
        <td class="kjCode">80350</td>
        <td class="kjName">東京エレクトロン</td>
        <td class="kjTitle"><a href="140120260808000001.pdf">2027年3月期 第1四半期決算短信</a></td>
        <td>東証</td>
      </tr>
    </table>
    """
    rows = ledger.parse_tdnet(sample)
    assert rows == [
        {
            "time": "15:30",
            "code": "80350",
            "company": "東京エレクトロン",
            "title": "2027年3月期 第1四半期決算短信",
            "href": "140120260808000001.pdf",
        }
    ]


def test_audit_fails_on_future_event_and_duplicate():
    now = datetime(2026, 8, 8, 4, 0, tzinfo=timezone.utc)
    event = {
        "event_id": "x",
        "company_id": "amd",
        "published_at": ledger.iso(now + timedelta(hours=1)),
        "source_url": "https://www.sec.gov/example",
        "document_type": "8-K",
    }
    registry = {"sources": []}
    audit = ledger.audit_ledger(registry, [event, event], [], now, [])
    codes = {issue["code"] for issue in audit["issues"]}
    assert "FUTURE_PUBLISHED_AT" in codes
    assert "DUPLICATE_EVENT_ID" in codes
    assert audit["status"] == "FAIL"


def test_disabled_source_is_a_gap_not_a_collection_failure():
    now = datetime(2026, 8, 8, 4, 0, tzinfo=timezone.utc)
    registry = {"sources": [{"id": "kr", "enabled": False}]}
    audit = ledger.audit_ledger(
        registry,
        [],
        [],
        now,
        [{"source_id": "kr", "status": "disabled"}],
    )
    assert audit["status"] == "PASS"
    assert audit["unsupported_or_disabled_sources"] == ["kr"]
