from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from semicon.ledger import load_json, load_jsonl, write_json

ROOT = Path(__file__).resolve().parents[2]

GENERATED_TABS = (
    "Company_Master", "Annual_Financials", "CapEx_Projects", "Facilities",
    "Orders_Backlog", "Customer_Commitments", "Project_Lifecycle",
    "Project_Economics", "Decision_Evidence", "Sources", "Coverage",
)


def _rows(headers: list[str], records: list[dict[str, Any]]) -> list[list[Any]]:
    return [headers] + [[record.get(header) for header in headers] for record in records]


def build_projection(root: Path = ROOT) -> dict[str, list[list[Any]]]:
    registry = load_json(root / "data/registry/entities.json", {"entities": []}) or {"entities": []}
    facts = load_jsonl(root / "data/canonical/facts.jsonl")
    projects = load_jsonl(root / "data/canonical/capex_projects.jsonl")
    facilities = load_jsonl(root / "data/canonical/facilities.jsonl")
    backlog = load_jsonl(root / "data/canonical/orders_backlog.jsonl")
    commitments = load_jsonl(root / "data/canonical/customer_commitments.jsonl")
    events = load_jsonl(root / "data/canonical/events.jsonl")
    economics = (load_json(root / "data/derived/project_economics.json", {}) or {}).get("projects", [])
    decision = (load_json(root / "data/derived/decision_evidence.json", {}) or {}).get("rows", [])

    company_headers = ["entity_id", "company_name", "ticker", "security_code", "cik", "edinet_code", "country", "currency", "role", "index_membership"]
    company_rows = []
    for entity in registry.get("entities", []):
        row = dict(entity)
        row["index_membership"] = json.dumps(entity.get("index_membership", []), ensure_ascii=False, sort_keys=True)
        company_rows.append(row)

    fact_headers = ["fact_id", "entity_id", "metric", "value", "unit", "period_start", "period_end", "fiscal_year", "period_type", "source_system", "source_doc_id", "source_url", "native_concept", "quality_flag", "null_reason"]
    project_headers = ["project_id", "event_id", "event_type", "entity_id", "project_name", "product", "technology", "facility_id", "location", "announcement_date", "period_start", "period_end", "capex_plan_low", "capex_plan_high", "capex_actual", "currency", "capacity_metric", "capacity_before", "capacity_after", "capacity_change", "capacity_unit", "planned_start", "production_start", "demand_evidence", "customer_commitment", "funding_source", "status", "source_system", "source_doc_id", "source_url", "quality_flag"]
    project_rows = []
    for item in projects:
        row = dict(item)
        plan = item.get("capex_plan") or {}
        row["capex_plan_low"] = plan.get("low") if isinstance(plan, dict) else None
        row["capex_plan_high"] = plan.get("high") if isinstance(plan, dict) else None
        row["event_id"] = item.get("event_id") or item.get("project_id")
        project_rows.append(row)

    facility_headers = ["facility_id", "entity_id", "facility_name", "location", "country", "prefecture", "municipality", "book_value_total", "buildings", "machinery", "land", "land_area_m2", "employees", "fiscal_year", "source_doc_id", "source_url", "quality_flag"]
    backlog_headers = ["record_id", "entity_id", "fiscal_year", "segment", "orders_received", "order_backlog", "currency", "source_doc_id", "source_url", "quality_flag"]
    commitment_headers = ["commitment_id", "entity_id", "customer_name", "commitment_type", "amount", "volume", "period_start", "period_end", "contract_status", "evidence_text", "source_doc_id", "source_url", "quality_flag"]
    event_headers = ["event_id", "entity_id", "event_type", "announcement_date", "period_start", "period_end", "project_name", "status", "evidence_text", "source_doc_id", "source_url", "quality_flag"]
    economics_headers = ["project_id", "entity_id", "currency", "required_annual_revenue_low", "required_annual_revenue_high", "model_status"]
    decision_headers = ["entity_id", "project_id", "demand_evidence_present", "customer_commitment_count", "orders_backlog_rows", "funding_source_present", "execution_start_present", "status"]

    source_rows: list[dict[str, Any]] = []
    seen_sources: set[tuple[str, str]] = set()
    for entity in registry.get("entities", []):
        for membership in entity.get("index_membership", []) or []:
            source_url = membership.get("source_url")
            if not source_url:
                continue
            source_doc_id = "index:" + "|".join(
                str(value or "")
                for value in (
                    membership.get("index_name"),
                    membership.get("as_of_date"),
                    membership.get("security_ticker_or_code"),
                )
            )
            key = (source_doc_id, str(source_url))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            source_rows.append({
                "source_doc_id": source_doc_id,
                "source_url": source_url,
                "source_system": "official_index_or_imported_index_source",
                "quality_flag": membership.get("verification_status"),
            })
    for dataset in (facts, projects, facilities, backlog, commitments, events):
        for row in dataset:
            key = (str(row.get("source_doc_id") or ""), str(row.get("source_url") or ""))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            source_rows.append({
                "source_doc_id": key[0] or None,
                "source_url": key[1] or None,
                "source_system": row.get("source_system"),
                "quality_flag": row.get("quality_flag"),
            })

    coverage = [
        ["dataset", "row_count"],
        ["entities", len(registry.get("entities", []))], ["facts", len(facts)],
        ["events", len(events)], ["capex_projects", len(projects)],
        ["facilities", len(facilities)], ["orders_backlog", len(backlog)],
        ["customer_commitments", len(commitments)],
    ]
    return {
        "Company_Master": _rows(company_headers, company_rows),
        "Annual_Financials": _rows(fact_headers, facts),
        "CapEx_Projects": _rows(project_headers, project_rows),
        "Facilities": _rows(facility_headers, facilities),
        "Orders_Backlog": _rows(backlog_headers, backlog),
        "Customer_Commitments": _rows(commitment_headers, commitments),
        "Project_Lifecycle": _rows(event_headers, events),
        "Project_Economics": _rows(economics_headers, economics),
        "Decision_Evidence": _rows(decision_headers, decision),
        "Sources": _rows(["source_doc_id", "source_url", "source_system", "quality_flag"], source_rows),
        "Coverage": coverage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Google Sheets view payload from canonical ledger.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-json", type=Path, default=Path("data/derived/google_sheets_projection.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    projection = build_projection(args.root)
    summary = {name: max(len(rows) - 1, 0) for name, rows in projection.items()}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    if not args.dry_run:
        write_json(args.output_json, {"schema_version": "google-sheets-projection.v1", "tabs": projection})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
