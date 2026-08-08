from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "earnings_ledger.py"
spec = importlib.util.spec_from_file_location("earnings_ledger", MODULE_PATH)
assert spec and spec.loader
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


def registry() -> dict:
    return {
        "companies": [
            {
                "company_id": "NVDA",
                "legal_name": "NVIDIA Corporation",
                "sources": [
                    {
                        "source_id": "nvda-sec-submissions",
                        "source_type": "SEC",
                        "enabled": True,
                        "allowed_hosts": ["sec.gov"],
                    }
                ],
            }
        ]
    }


def event(**overrides) -> dict:
    base = {
        "event_id": "NVDA|FY2027Q2|10-Q",
        "company_id": "NVDA",
        "company": "NVIDIA Corporation",
        "fiscal_year": 2027,
        "fiscal_quarter": 2,
        "fiscal_period": "FY2027Q2",
        "period_end": "2026-07-26",
        "event_type": "earnings_release",
        "document_type": "10-Q",
        "published_at": "2026-08-07T20:10:00-04:00",
        "retrieved_at": "2026-08-08T09:17:00+09:00",
        "source_id": "nvda-sec-submissions",
        "source_type": "SEC",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1045810/example/nvda.htm",
        "content_sha256": "a" * 64,
        "actuals": [{"metric_id": "revenue", "value": 120.0, "unit": "USD", "basis": "GAAP"}],
        "consensus": [{"metric_id": "revenue", "value": 110.0, "unit": "USD", "basis": "GAAP", "provider": "FactSet", "as_of": "2026-08-07T15:00:00-04:00"}],
    }
    base.update(overrides)
    return base


def validate(candidate: dict):
    return ledger.validate_event(
        candidate,
        registry(),
        window_start=datetime.fromisoformat("2026-08-07T07:00:00+09:00"),
        window_end=datetime.fromisoformat("2026-08-08T07:00:00+09:00"),
        now=datetime.fromisoformat("2026-08-08T07:00:00+09:00"),
        existing_event_ids=set(),
    )


def test_stale_nvidia_fy2026_q2_is_rejected_before_ai():
    candidate = event(
        event_id="NVDA|FY2026Q2|10-Q",
        fiscal_year=2026,
        fiscal_period="FY2026Q2",
        period_end="2025-07-27",
        published_at="2025-08-27T16:10:00-04:00",
    )
    ok, reason, _ = validate(candidate)
    assert not ok
    assert reason == "OUTSIDE_TIME_WINDOW"


def test_third_party_url_cannot_be_promoted():
    ok, reason, _ = validate(event(source_url="https://example.com/nvidia-earnings"))
    assert not ok
    assert reason == "NOT_PRIMARY_SOURCE"


def test_period_key_mismatch_is_rejected():
    ok, reason, _ = validate(event(event_id="NVDA|FY2026Q2|10-Q"))
    assert not ok
    assert reason == "STALE_FISCAL_PERIOD"


def test_qoq_yoy_and_consensus_surprise_are_deterministic():
    history = [
        event(event_id="NVDA|FY2026Q2|10-Q", fiscal_year=2026, fiscal_period="FY2026Q2", period_end="2025-07-27", published_at="2025-08-27T16:10:00-04:00", actuals=[{"metric_id": "revenue", "value": 80.0, "unit": "USD", "basis": "GAAP"}], consensus=None),
        event(event_id="NVDA|FY2027Q1|10-Q", fiscal_quarter=1, fiscal_period="FY2027Q1", period_end="2026-04-26", published_at="2026-05-20T16:10:00-04:00", actuals=[{"metric_id": "revenue", "value": 100.0, "unit": "USD", "basis": "GAAP"}], consensus=None),
    ]
    result = ledger.calculate_comparisons(event(), history)["revenue"]
    assert result["qoq"] == 0.2
    assert result["yoy"] == 0.5
    assert result["surprise"] == round(120 / 110 - 1, 12)


def test_missing_consensus_stays_null():
    candidate = event(consensus=None)
    result = ledger.calculate_comparisons(candidate, [])
    assert candidate["consensus"] is None
    assert result["revenue"]["surprise"] is None
