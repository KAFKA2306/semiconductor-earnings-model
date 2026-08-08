from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "normalize_earnings_periods.py"
SPEC = importlib.util.spec_from_file_location("normalize_earnings_periods", MODULE_PATH)
assert SPEC and SPEC.loader
periods = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(periods)


def test_sec_report_date_becomes_period_end_without_quarter_inference():
    row = {
        "event_id": "e1",
        "company_id": "lam-research",
        "source_adapter": "sec_edgar",
        "document_type": "10-K",
        "report_date": "2026-06-28",
    }
    item = periods.normalize_period(row)
    assert item is not None
    assert item["period_end"] == "2026-06-28"
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


def test_missing_sec_report_date_stays_missing():
    row = {
        "event_id": "e3",
        "company_id": "amd",
        "source_adapter": "sec_edgar",
        "document_type": "8-K",
        "report_date": None,
    }
    assert periods.normalize_period(row) is None


def test_invalid_primary_period_fails_closed():
    result = periods.audit([
        {
            "event_id": "e4",
            "company_id": "nvidia",
            "source_adapter": "sec_edgar",
            "document_type": "10-Q",
            "report_date": "2026-02-30",
        }
    ])
    assert result["status"] == "FAIL"
    assert result["issues"][0]["code"] == "INVALID_PRIMARY_PERIOD"


def test_duplicate_normalized_event_fails_closed():
    row = {
        "event_id": "e5",
        "company_id": "micron",
        "source_adapter": "sec_edgar",
        "document_type": "10-Q",
        "report_date": "2026-05-28",
    }
    result = periods.audit([row, row])
    assert result["status"] == "FAIL"
    assert any(issue["code"] == "DUPLICATE_NORMALIZED_EVENT" for issue in result["issues"])
