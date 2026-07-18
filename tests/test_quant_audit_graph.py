import json
from pathlib import Path

from src.quant_audit_graph import run_audit, stable_hash


def snapshot() -> dict:
    path = Path(__file__).parents[1] / "data/quant_audit/semiconductor_latest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_same_snapshot_is_reproducible():
    first = run_audit(snapshot(), "run-a")
    second = run_audit(snapshot(), "run-b")
    assert stable_hash(first) == stable_hash(second)
    assert first["snapshot_hash"] == second["snapshot_hash"]


def test_snapshot_contains_exact_primary_values():
    snap = snapshot()
    assert len(snap["sources"]) == 6
    assert len({(row["period_start"], row["period_end"]) for row in snap["sources"]}) == 1
    assert all(isinstance(row["operating_cash_flow_usd"], int) for row in snap["sources"])
    assert all(isinstance(row["capital_expenditures_usd"], int) for row in snap["sources"])
    assert all(row["operating_cash_flow_source_url"].startswith("https://www.sec.gov/") for row in snap["sources"])


def test_normalization_does_not_mix_capex_concepts():
    result = run_audit(snapshot())
    normalized = result["normalized"]
    assert "capital_expenditures_total_usd" not in normalized
    assert "residual_cash_flow_usd" not in normalized
    assert normalized["capital_expenditures_fact_tag_count"] == 2
    assert result["audit"]["verdict"] == "observed_with_limits"


def test_input_update_changes_snapshot_and_metrics():
    original = snapshot()
    updated = snapshot()
    updated["sources"][0]["operating_cash_flow_usd"] += 1
    first = run_audit(original)
    second = run_audit(updated)
    assert first["snapshot_hash"] != second["snapshot_hash"]
    assert first["normalized"]["operating_cash_flow_total_usd"] != second["normalized"]["operating_cash_flow_total_usd"]


def test_missing_primary_field_blocks_the_graph():
    invalid = snapshot()
    invalid["sources"][0].pop("capital_expenditures_fact_tag")
    result = run_audit(invalid)
    assert result["status"] == "blocked"
    assert result["audit"]["valid_input"] is False
    assert any("primary fields" in error for error in result["audit"]["errors"])


def test_ambiguous_period_blocks_the_graph():
    invalid = snapshot()
    invalid["sources"][1]["period_end"] = "2026-03-30"
    result = run_audit(invalid)
    assert result["status"] == "blocked"
    assert "sources must cover one common reported period" in result["audit"]["errors"]
