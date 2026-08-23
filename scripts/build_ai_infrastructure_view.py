#!/usr/bin/env python3
"""Merge stored AI infrastructure evidence into one reusable view."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DOMAIN_BY_CONCEPT = {
    "data_center_compute_revenue": "compute",
    "data_center_networking_revenue": "network",
    "data_center_ssd_revenue": "memory",
    "energy_capacity_added": "power",
    "capital_expenditures": "capital_investment",
    "cash_paid_for_property_plant_equipment": "capital_investment",
}


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["observations"]


def validate_comparability(rows: list[dict]) -> None:
    """Fail closed if SEC cash PP&E is mislabeled as company total CapEx."""
    for row in rows:
        if row.get("sec_concept") == "PaymentsToAcquirePropertyPlantAndEquipment":
            if row.get("concept_id") != "cash_paid_for_property_plant_equipment":
                raise ValueError(
                    f"{row.get('id')}: SEC cash PP&E must not use a total-capex concept"
                )
        if row.get("concept_id") == "capital_expenditures" and row.get("source_tier") == "primary_regulatory":
            raise ValueError(
                f"{row.get('id')}: primary regulatory cash-flow fact cannot be total CapEx"
            )


def build(manual_path: Path, sec_path: Path, output_dir: Path) -> None:
    rows = [*load(manual_path), *load(sec_path)]
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate AI infrastructure observation id")
    validate_comparability(rows)
    rows.sort(key=lambda row: (row["period_end"], row["entity"], row["concept_id"], row["id"]))
    domains = sorted({DOMAIN_BY_CONCEPT.get(row["concept_id"], "other") for row in rows})
    companies = sorted({row["entity"] for row in rows})
    periods = sorted({row["period_end"] for row in rows})
    actual = [row for row in rows if row["value_type"] == "actual"]
    guidance = [row for row in rows if row["value_type"] == "company_guidance"]
    output = {
        "schema_version": "ai-infrastructure-view.v2",
        "comparison_rule": "Only observations with the same concept_id, unit and compatible period definition may be compared. SEC PaymentsToAcquirePropertyPlantAndEquipment is cash PP&E and is not interchangeable with company-reported total CapEx.",
        "observations": rows,
    }
    coverage = {
        "observation_count": len(rows),
        "company_count": len(companies),
        "companies": companies,
        "period_start": periods[0],
        "period_end": periods[-1],
        "actual_count": len(actual),
        "guidance_count": len(guidance),
        "domains": domains,
        "domain_counts": {
            domain: sum(DOMAIN_BY_CONCEPT.get(row["concept_id"], "other") == domain for row in rows)
            for domain in domains
        },
    }
    required = {"compute", "memory", "network", "power"}
    if len(companies) < 10 or not required.issubset(domains):
        raise ValueError(f"coverage incomplete: companies={len(companies)}, domains={domains}")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", type=Path, default=Path("data/financial_db/ai_infrastructure_observations.json"))
    parser.add_argument("--sec", type=Path, default=Path("data/financial_db/ai_infrastructure_sec_capex.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("api/v1/ai-infrastructure"))
    args = parser.parse_args()
    build(args.manual, args.sec, args.output_dir)


if __name__ == "__main__":
    main()
