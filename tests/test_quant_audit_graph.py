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


def test_base_case_matches_published_scenario():
    result = run_audit(snapshot())
    base = next(row for row in result["scenarios"] if row["name"] == "base")
    snap = snapshot()
    expected_investment = (1 + snap["scenarios"][1]["ocf_growth"]) * (1 - snap["scenarios"][1]["fcf_reserve"] + snap["scenarios"][1]["external_financing"]) / snap["model_base_ratio"] - 1
    assert base["effective_investment_growth"] == round(expected_investment * 100, 1)
    assert base["revenue_growth_range"] == [round(expected_investment * beta * 100, 1) for beta in snap["beta_range"]]
    assert base["operating_earnings_growth_range"] == base["revenue_growth_range"]


def test_snapshot_uses_primary_facts_without_proxy_fields():
    snap = snapshot()
    assert len(snap["sources"]) == 6
    assert len({(row["period_start"], row["period_end"]) for row in snap["sources"]}) == 1
    assert all(row["operating_cash_flow_fact_tag"] for row in snap["sources"])
    assert all(row["capital_expenditures_fact_tag"] for row in snap["sources"])
    assert all("capex_proxy" not in row for row in snap["sources"])


def test_input_update_changes_snapshot_and_metrics():
    original = snapshot()
    updated = snapshot()
    updated["sources"][0]["operating_cash_flow"] = 27.032
    first = run_audit(original)
    second = run_audit(updated)
    assert first["snapshot_hash"] != second["snapshot_hash"]
    assert first["normalized"]["operating_cash_flow_total"] != second["normalized"]["operating_cash_flow_total"]


def test_missing_primary_field_blocks_the_graph():
    invalid = snapshot()
    invalid["sources"][0].pop("capital_expenditures_fact_tag")
    result = run_audit(invalid)
    assert result["status"] == "blocked"
    assert result["audit"]["valid_input"] is False
    assert any("primary fields" in error for error in result["audit"]["errors"])
