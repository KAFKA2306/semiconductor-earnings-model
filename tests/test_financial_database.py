from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parents[1]
JSON_PATH = ROOT / "site/public/api/v3/financial-database/index.json"
SQLITE_PATH = ROOT / "site/public/api/v3/financial-database/financial.db"


def load() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_financial_database_contract_and_audit_pass() -> None:
    payload = load()
    assert payload["schema_version"] == "financial-database.v3"
    assert payload["audit"]["status"] == "PASS"
    assert payload["content_hash"]
    assert payload["sqlite_path"] == "financial.db"
    counts = payload["audit"]["counts"]
    assert counts["entities"] == len(payload["entities"])
    assert counts["observations"] == len(payload["observations"])
    assert counts["metrics"] == len(payload["derived_metrics"])
    assert counts["actual_observations"] > 0
    assert counts["concepts_catalogued"] >= 40


def test_observations_are_traceable_unique_and_semantically_typed() -> None:
    payload = load()
    observations = payload["observations"]
    ids = [row["id"] for row in observations]
    assert len(ids) == len(set(ids))
    allowed_types = set(payload["catalog"]["value_types"])
    allowed_tiers = set(payload["catalog"]["source_tiers"])
    entity_ids = {row["id"] for row in payload["entities"]}
    assert all(row["entity_id"] in entity_ids for row in observations)
    assert all(row["value_type"] in allowed_types for row in observations)
    assert all(row["source_tier"] in allowed_tiers for row in observations)
    assert all(str(row["source_url"]).startswith("https://") for row in observations)
    assert all(row["period_type"] in {"annual", "quarter", "duration", "instant", "point_in_time", "unknown"} for row in observations)
    assert all(row["value_type"] == "actual" for row in observations if row["source_tier"] == "primary_regulatory")


def test_fact_estimate_guidance_and_market_classes_remain_separate() -> None:
    payload = load()
    value_types = payload["catalog"]["value_types"]
    assert value_types == [
        "actual",
        "company_guidance",
        "analyst_consensus",
        "internal_estimate",
        "scenario",
        "market_observation",
    ]
    comparisons = set(payload["catalog"]["comparison_types"])
    assert {"yoy", "qoq", "vs_company_guidance", "vs_analyst_consensus", "vs_prior_estimate"} <= comparisons
    recipes = {item["id"] for item in payload["views"]["recipes"]}
    assert {"latest_company_snapshot", "earnings_comparison", "capex_roi_review", "semiconductor_cycle_review", "downside_resilience"} <= recipes


def test_sqlite_mirror_integrity_and_counts() -> None:
    payload = load()
    connection = sqlite3.connect(SQLITE_PATH)
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    expected = {
        "entities": len(payload["entities"]),
        "concepts": len(payload["catalog"]["concepts"]),
        "sources": len(payload["sources"]),
        "observations": len(payload["observations"]),
        "metrics": len(payload["derived_metrics"]),
        "evaluations": len(payload["evaluations"]),
        "evidence_edges": len(payload["evidence_edges"]),
        "audit_issues": len(payload["audit"]["issues"]),
    }
    for table, count in expected.items():
        actual = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert actual == count, (table, actual, count)
    connection.close()


def test_latest_views_do_not_duplicate_entity_concept_pairs() -> None:
    payload = load()
    actual_pairs = [(row["entity_id"], row["concept_id"]) for row in payload["views"]["latest_actuals"]]
    metric_pairs = [(row.get("issuer_id"), row.get("metric_id")) for row in payload["views"]["latest_metrics"]]
    assert len(actual_pairs) == len(set(actual_pairs))
    assert len(metric_pairs) == len(set(metric_pairs))
