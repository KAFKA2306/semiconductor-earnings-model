from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "normalize_earnings_periods.py"
SPEC = importlib.util.spec_from_file_location("normalize_earnings_periods", MODULE_PATH)
assert SPEC and SPEC.loader
periods = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(periods)


def sec_row(**overrides):
    row = {
        "event_id": "e1",
        "company_id": "lam-research",
        "source_adapter": "sec_edgar",
        "document_type": "10-K",
        "freshness": "PASS",
        "report_date": "2026-06-28",
        "published_at": "2026-08-07T20:06:32Z",
        "accession_number": "0000707549-26-000037",
    }
    row.update(overrides)
    return row


def test_sec_report_date_becomes_period_end_without_quarter_inference():
    item = periods.normalize_period(sec_row())
    assert item is not None
    assert item["period_end"] == "2026-06-28"
    assert item["accession_number"] == "0000707549-26-000037"
    assert item["fiscal_year"] is None
    assert item["fiscal_quarter"] is None
    assert item["normalization_status"] == "PRIMARY_PERIOD_END_ONLY"


def test_non_sec_period_is_not_guessed():
    row = {
        "event_id": "e2",
        "company_id": "tokyo-electron",
        "source_adapter": "tdnet_public",
        "document_type": "TDNET_DISCLOSURE",
        "title": "2027年3月期 第1四半期決算短信",
    }
    assert periods.normalize_period(row) is None


def test_non_10k_10q_sec_form_is_not_normalized():
    assert periods.normalize_period(sec_row(document_type="8-K")) is None


def test_missing_sec_report_date_fails_closed_for_eligible_form():
    result = periods.audit([sec_row(event_id="e3", report_date=None)])
    assert result["status"] == "FAIL"
    assert result["issues"][0]["code"] == "INVALID_PRIMARY_PERIOD"


def test_invalid_primary_period_fails_closed():
    result = periods.audit([sec_row(event_id="e4", report_date="2026-02-30")])
    assert result["status"] == "FAIL"
    assert result["issues"][0]["code"] == "INVALID_PRIMARY_PERIOD"


def test_non_pass_freshness_fails_closed():
    result = periods.audit([sec_row(event_id="e5", freshness="FAIL")])
    assert result["status"] == "FAIL"
    assert "freshness is not PASS" in result["issues"][0]["detail"]


def test_missing_accession_fails_closed():
    result = periods.audit([sec_row(event_id="e6", accession_number=None)])
    assert result["status"] == "FAIL"
    assert "missing SEC accession_number" in result["issues"][0]["detail"]


def test_period_end_after_publication_fails_closed():
    result = periods.audit([
        sec_row(event_id="e7", report_date="2026-08-08", published_at="2026-08-07T23:59:59Z")
    ])
    assert result["status"] == "FAIL"
    assert "report_date is after published_at" in result["issues"][0]["detail"]


def test_timezone_naive_publication_fails_closed():
    result = periods.audit([sec_row(event_id="e8", published_at="2026-08-07T20:06:32")])
    assert result["status"] == "FAIL"
    assert "timezone-naive" in result["issues"][0]["detail"]


def test_duplicate_normalized_event_fails_closed():
    row = sec_row(event_id="e9")
    result = periods.audit([row, row])
    assert result["status"] == "FAIL"
    assert any(issue["code"] == "DUPLICATE_NORMALIZED_EVENT" for issue in result["issues"])
