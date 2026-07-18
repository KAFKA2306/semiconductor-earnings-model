import json
from pathlib import Path

from src.quant_audit_graph import run_audit, stable_hash


def snapshot() -> dict:
    path = Path(__file__).parents[1] / "data/quant_audit/semiconductor_20260718.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_same_snapshot_is_reproducible():
    first = run_audit(snapshot(), "run-a")
    second = run_audit(snapshot(), "run-b")
    assert stable_hash(first) == stable_hash(second)
    assert first["snapshot_hash"] == second["snapshot_hash"]


def test_base_case_matches_published_scenario():
    result = run_audit(snapshot())
    base = next(row for row in result["scenarios"] if row["name"] == "base")
    assert base["effective_investment_growth"] == 32.6
    assert base["revenue_growth_range"] == [19.5, 26.0]
    assert base["operating_earnings_growth_range"] == [19.5, 26.0]


def test_input_update_changes_snapshot_and_metrics():
    original = snapshot()
    updated = snapshot()
    updated["sources"][0]["operating_cash_flow"] = 27.032
    first = run_audit(original)
    second = run_audit(updated)
    assert first["snapshot_hash"] != second["snapshot_hash"]
    assert first["normalized"]["operating_cash_flow_total"] != second["normalized"]["operating_cash_flow_total"]
