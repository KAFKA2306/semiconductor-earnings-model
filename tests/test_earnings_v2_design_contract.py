from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "data" / "earnings_ledger" / "schema"
DOC = ROOT / "docs" / "earnings-evidence-ledger-v2.md"

EXPECTED_REJECTIONS = {
    "OUTSIDE_TIME_WINDOW",
    "UNKNOWN_PUBLISHED_TIME",
    "STALE_FISCAL_PERIOD",
    "DUPLICATE",
    "NOT_PRIMARY_SOURCE",
    "FUTURE_EARNINGS_EVENT",
    "REPOST",
    "MISMATCHED_COMPANY",
    "UNVERIFIED_NUMBER",
}


def load(name: str) -> dict:
    return json.loads((SCHEMA / name).read_text(encoding="utf-8"))


def test_event_v2_requires_fiscal_identity_and_evidence_hash():
    schema = load("event-v2.schema.json")
    required = set(schema["required"])
    assert {
        "event_id",
        "company_id",
        "fiscal_year",
        "fiscal_quarter",
        "fiscal_period",
        "period_end",
        "published_at",
        "retrieved_at",
        "source_url",
        "content_sha256",
        "actuals",
        "consensus",
    } <= required
    assert schema["properties"]["freshness"]["const"] == "PASS"
    assert schema["properties"]["fiscal_period"]["pattern"] == "^FY[0-9]{4}Q[1-4]$"


def test_rejection_reasons_are_fixed():
    schema = load("rejection-v2.schema.json")
    assert set(schema["properties"]["reason"]["enum"]) == EXPECTED_REJECTIONS


def test_collection_state_is_last_seen_based():
    schema = load("collection-state-v2.schema.json")
    required = set(schema["properties"]["sources"]["additionalProperties"]["required"])
    assert {
        "last_seen_id",
        "last_seen_published_at",
        "last_attempt_at",
        "last_success_at",
        "last_content_sha256",
    } == required


def test_design_forbids_llm_freshness_and_separates_daily_report():
    text = DOC.read_text(encoding="utf-8")
    assert "AIは最後の要約だけ" in text
    assert "一般Web検索" in text
    assert "07:07 JST" in text
    assert "daily reportでは新規collectionはしない" in text
    assert "event_id = company_id|fiscal_period|document_type" in text
    assert "2025-08-27公表のNVIDIA FY2026Q2" in text
