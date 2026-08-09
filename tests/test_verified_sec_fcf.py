from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_verified_sec_fcf.py"
SPEC = importlib.util.spec_from_file_location("extract_verified_sec_fcf", MODULE_PATH)
assert SPEC and SPEC.loader
fcf = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fcf
SPEC.loader.exec_module(fcf)

NOW = datetime(2026, 8, 9, 18, 0, tzinfo=timezone.utc)


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
        "published_at": "2026-08-09T17:00:00Z",
    }
    row.update(overrides)
    return row


def fact(value: int, **overrides):
    row = {
        "accn": "0000001234-26-000001",
        "form": "10-Q",
        "start": "2026-01-01",
        "end": "2026-06-30",
        "val": value,
        "filed": "2026-08-09",
        "fy": 2026,
        "fp": "Q2",
    }
    row.update(overrides)
    return row


def payload(ocf_facts=None, capex_facts=None):
    gaap = {}
    if ocf_facts is not None:
        gaap[fcf.OCF_CONCEPT] = {"units": {"USD": ocf_facts}}
    if capex_facts is not None:
        gaap[fcf.CAPEX_CONCEPT] = {"units": {"USD": capex_facts}}
    return {"facts": {"us-gaap": gaap}}


def test_exact_inputs_are_derived_and_explicitly_non_gaap():
    result = fcf.audit([event()], {1234: payload([fact(500)], [fact(125)])}, NOW)
    assert result["status"] == "PASS"
    assert result["verified_metrics_total"] == 1
    metric = result["metrics"][0]
    assert metric["value"] == 375
    assert metric["accounting_basis"] == "derived-non-gaap"
    assert metric["inputs"]["operating_cash_flow"]["concept"] == fcf.OCF_CONCEPT
    assert metric["inputs"]["capital_expenditures"]["concept"] == fcf.CAPEX_CONCEPT


def test_event_older_than_24_hours_is_skipped():
    stale = event(published_at=(NOW - timedelta(hours=24, microseconds=1)).isoformat())
    result = fcf.audit([stale], {}, NOW)
    assert result["status"] == "PASS"
    assert result["eligible_events_total"] == 0
    assert result["stale_events_skipped_total"] == 1
    assert result["metrics"] == []


def test_exact_24_hour_boundary_is_live():
    boundary = event(published_at=(NOW - timedelta(hours=24)).isoformat())
    result = fcf.audit([boundary], {1234: payload([fact(500)], [fact(125)])}, NOW)
    assert result["status"] == "PASS"
    assert result["verified_metrics_total"] == 1


def test_future_event_fails_closed():
    future = event(published_at=(NOW + timedelta(seconds=1)).isoformat())
    result = fcf.audit([future], {}, NOW)
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"FUTURE_PUBLISHED_AT"}


def test_missing_ocf_concept_fails_closed():
    result = fcf.audit([event()], {1234: payload(None, [fact(125)])}, NOW)
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"NO_STANDARD_FCF_INPUT_CONCEPT"}


def test_missing_capex_fact_fails_closed():
    result = fcf.audit([event()], {1234: payload([fact(500)], [])}, NOW)
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"NO_VERIFIED_FCF_INPUT_FACT"}


def test_mismatched_periods_fail_closed():
    result = fcf.audit(
        [event()],
        {1234: payload([fact(500)], [fact(125, start="2026-04-01")])},
        NOW,
    )
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"FCF_INPUT_PERIOD_MISMATCH"}


def test_ambiguous_ocf_duration_fails_closed():
    result = fcf.audit(
        [event()],
        {1234: payload([fact(500), fact(500, start="2026-04-01")], [fact(125)])},
        NOW,
    )
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"AMBIGUOUS_FCF_INPUT_FACT"}


def test_wrong_accession_is_not_accepted():
    result = fcf.audit(
        [event()],
        {1234: payload([fact(500, accn="other")], [fact(125)])},
        NOW,
    )
    assert result["status"] == "FAIL"
    assert "NO_VERIFIED_FCF_INPUT_FACT" in {i["code"] for i in result["issues"]}


def test_timezone_less_published_at_fails_closed():
    result = fcf.audit([event(published_at="2026-08-09T17:00:00")], {}, NOW)
    assert result["status"] == "FAIL"
    assert {i["code"] for i in result["issues"]} == {"INVALID_PUBLISHED_AT"}
