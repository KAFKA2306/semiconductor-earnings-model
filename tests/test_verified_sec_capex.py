from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_verified_sec_capex.py"
SPEC = importlib.util.spec_from_file_location("extract_verified_sec_capex", MODULE_PATH)
assert SPEC and SPEC.loader
capex = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capex
SPEC.loader.exec_module(capex)

NOW = datetime(2026, 8, 9, 15, 0, tzinfo=timezone.utc)


def event(**overrides):
    row = {
        "event_id": "evt",
        "company_id": "example",
        "ticker": "EX",
        "cik": 1234,
        "accession_number": "0000001234-26-000001",
        "report_date": "2026-06-30",
        "document_type": "10-Q",
        "source_adapter": "sec_edgar",
        "freshness": "PASS",
        "published_at": "2026-08-09T14:00:00Z",
    }
    row.update(overrides)
    return row


def payload(facts):
    return {
        "facts": {
            "us-gaap": {
                capex.CAPEX_CONCEPT: {"units": {"USD": facts}}
            }
        }
    }


def fact(**overrides):
    row = {
        "accn": "0000001234-26-000001",
        "form": "10-Q",
        "start": "2026-01-01",
        "end": "2026-06-30",
        "val": 125000000,
        "filed": "2026-08-09",
        "fy": 2026,
        "fp": "Q2",
    }
    row.update(overrides)
    return row


def test_exact_standard_capex_fact_is_persisted():
    result = capex.audit([event()], {1234: payload([fact()])}, NOW)
    assert result["status"] == "PASS"
    assert result["verified_metrics_total"] == 1
    metric = result["metrics"][0]
    assert metric["concept"] == "PaymentsToAcquirePropertyPlantAndEquipment"
    assert metric["period_start"] == "2026-01-01"
    assert metric["period_end"] == "2026-06-30"
    assert metric["duration_days"] == 181
    assert metric["value"] == 125000000


def test_event_older_than_24_hours_is_skipped_without_fetch_requirement():
    stale = event(published_at=(NOW - timedelta(hours=24, microseconds=1)).isoformat())
    result = capex.audit([stale], {}, NOW)
    assert result["status"] == "PASS"
    assert result["eligible_events_total"] == 0
    assert result["stale_events_skipped_total"] == 1
    assert result["metrics"] == []


def test_exact_24_hour_boundary_is_live():
    boundary = event(published_at=(NOW - timedelta(hours=24)).isoformat())
    result = capex.audit([boundary], {1234: payload([fact()])}, NOW)
    assert result["status"] == "PASS"
    assert result["verified_metrics_total"] == 1


def test_future_event_fails_closed():
    future = event(published_at=(NOW + timedelta(seconds=1)).isoformat())
    result = capex.audit([future], {}, NOW)
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"FUTURE_PUBLISHED_AT"}


def test_missing_standard_concept_fails_closed():
    result = capex.audit([event()], {1234: {"facts": {"us-gaap": {}}}}, NOW)
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"NO_STANDARD_CAPEX_CONCEPT"}


def test_different_duration_contexts_are_ambiguous_even_if_value_matches():
    result = capex.audit(
        [event()],
        {1234: payload([fact(), fact(start="2026-04-01")])},
        NOW,
    )
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"AMBIGUOUS_STANDARD_CAPEX_FACT"}


def test_wrong_accession_is_not_accepted():
    result = capex.audit([event()], {1234: payload([fact(accn="other")])}, NOW)
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"NO_VERIFIED_STANDARD_CAPEX_FACT"}


def test_timezone_less_published_at_fails_closed():
    result = capex.audit([event(published_at="2026-08-09T14:00:00")], {}, NOW)
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"INVALID_PUBLISHED_AT"}
