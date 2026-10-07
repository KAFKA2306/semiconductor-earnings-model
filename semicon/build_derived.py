from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from semicon.ledger import load_jsonl, write_json

ROOT = Path(__file__).resolve().parents[1]

MODEL_ASSUMPTIONS = {
    "simple_payback_years": 5.0,
    "incremental_ebit_margin": 0.25,
    "tax_rate": 0.30,
    "provenance": "analytical assumption migrated from CapEx DB v0.4 handoff; not company guidance",
}


def _amount(plan: dict[str, Any] | None, key: str) -> float | int | None:
    if not isinstance(plan, dict):
        return None
    value = plan.get(key)
    return value if isinstance(value, (int, float)) else None


def build(root: Path = ROOT) -> dict[str, Any]:
    projects = load_jsonl(root / "data/canonical/capex_projects.jsonl")
    facts = load_jsonl(root / "data/canonical/facts.jsonl")
    commitments = load_jsonl(root / "data/canonical/customer_commitments.jsonl")
    backlog = load_jsonl(root / "data/canonical/orders_backlog.jsonl")

    economics = []
    plan_vs_actual = []
    earnings_inputs = []
    decision_evidence = []
    after_tax_margin = MODEL_ASSUMPTIONS["incremental_ebit_margin"] * (1 - MODEL_ASSUMPTIONS["tax_rate"])

    commitments_by_entity: dict[str, int] = {}
    for row in commitments:
        commitments_by_entity[row["entity_id"]] = commitments_by_entity.get(row["entity_id"], 0) + 1
    backlog_by_entity: dict[str, int] = {}
    for row in backlog:
        backlog_by_entity[row["entity_id"]] = backlog_by_entity.get(row["entity_id"], 0) + 1

    for project in projects:
        low = _amount(project.get("capex_plan"), "low")
        high = _amount(project.get("capex_plan"), "high")
        annual_profit_low = None if low is None else low / MODEL_ASSUMPTIONS["simple_payback_years"]
        annual_profit_high = None if high is None else high / MODEL_ASSUMPTIONS["simple_payback_years"]
        required_rev_low = None if annual_profit_low is None else annual_profit_low / after_tax_margin
        required_rev_high = None if annual_profit_high is None else annual_profit_high / after_tax_margin
        economics.append({
            "project_id": project["project_id"],
            "entity_id": project["entity_id"],
            "currency": project.get("currency"),
            "assumptions": MODEL_ASSUMPTIONS,
            "required_annual_revenue_low": required_rev_low,
            "required_annual_revenue_high": required_rev_high,
            "model_status": "derived_not_company_guidance",
        })

        actual = project.get("capex_actual")
        if isinstance(actual, (int, float)) and (low is not None or high is not None):
            midpoint = high if low is None else low if high is None else (low + high) / 2
            plan_vs_actual.append({
                "project_id": project["project_id"],
                "entity_id": project["entity_id"],
                "plan_midpoint": midpoint,
                "actual": actual,
                "variance": actual - midpoint,
                "currency": project.get("currency"),
            })

        before = project.get("capacity_before")
        after = project.get("capacity_after")
        capacity_growth = None
        capacity_unit = str(project.get("capacity_unit") or "").strip().lower()
        capacity_metric = str(project.get("capacity_metric") or "").strip().lower()
        is_physical_capacity = (
            not capacity_unit.startswith("%")
            and "allocation" not in capacity_unit
            and "allocation" not in capacity_metric
        )
        if is_physical_capacity and isinstance(before, (int, float)) and isinstance(after, (int, float)) and before != 0:
            capacity_growth = after / before - 1
        earnings_inputs.append({
            "entity_id": project["entity_id"],
            "project_id": project["project_id"],
            "capacity_growth": capacity_growth,
            "production_start": project.get("production_start"),
            "incremental_units": None,
            "incremental_revenue": None,
            "incremental_margin": None,
            "depreciation_increment": None,
            "working_capital_increment": None,
            "scenario": "unmodeled_until_explicit_driver_inputs",
            "confidence": "insufficient_for_earnings_projection",
        })
        decision_evidence.append({
            "entity_id": project["entity_id"],
            "project_id": project["project_id"],
            "demand_evidence_present": bool(project.get("demand_evidence")),
            "customer_commitment_count": commitments_by_entity.get(project["entity_id"], 0),
            "orders_backlog_rows": backlog_by_entity.get(project["entity_id"], 0),
            "funding_source_present": bool(project.get("funding_source")),
            "execution_start_present": bool(project.get("production_start") or project.get("planned_start")),
            "status": "derived_evidence_presence_only",
        })

    payloads = {
        "project_economics.json": {"schema_version": "project-economics.v1", "assumptions": MODEL_ASSUMPTIONS, "projects": economics},
        "plan_vs_actual.json": {"schema_version": "plan-vs-actual.v1", "rows": plan_vs_actual},
        "earnings_inputs.json": {"schema_version": "earnings-inputs.v1", "inputs": earnings_inputs},
        "decision_evidence.json": {"schema_version": "decision-evidence.v1", "rows": decision_evidence},
    }
    for name, payload in payloads.items():
        write_json(root / "data/derived" / name, payload)
    return {"projects": len(projects), "facts": len(facts), "economics": len(economics), "earnings_inputs": len(earnings_inputs)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(build(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
