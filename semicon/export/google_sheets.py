from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
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

    company_headers = [
        "entity_id", "company_name", "aliases", "ticker", "ticker_aliases",
        "security_code", "security_codes", "cik", "edinet_code", "country",
        "currency", "role", "role_aliases", "index_membership",
    ]
    company_rows = []
    for entity in registry.get("entities", []):
        row = dict(entity)
        for field in ("aliases", "ticker_aliases", "security_codes", "role_aliases", "index_membership"):
            row[field] = json.dumps(entity.get(field, []), ensure_ascii=False, sort_keys=True)
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


def _google_json(url: str, token: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Sheets API failed: HTTP {exc.code}: {detail[:1000]}") from exc
    return json.loads(body.decode("utf-8")) if body else {}


def apply_projection(spreadsheet_id: str, projection: dict[str, list[list[Any]]], token: str) -> dict[str, Any]:
    """Replace generated view tabs from canonical data using Google Sheets API v4."""
    sid = urllib.parse.quote(spreadsheet_id, safe="")
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{sid}"
    metadata = _google_json(base + "?fields=sheets.properties.title", token)
    existing = {
        str(sheet.get("properties", {}).get("title"))
        for sheet in metadata.get("sheets", [])
        if sheet.get("properties", {}).get("title")
    }
    missing = [name for name in GENERATED_TABS if name not in existing]
    if missing:
        _google_json(
            base + ":batchUpdate",
            token,
            method="POST",
            payload={"requests": [{"addSheet": {"properties": {"title": name}}} for name in missing]},
        )

    ranges = [f"{name}!A:ZZ" for name in GENERATED_TABS]
    _google_json(base + "/values:batchClear", token, method="POST", payload={"ranges": ranges})

    data = [
        {
            "range": f"{name}!A1",
            "majorDimension": "ROWS",
            "values": projection.get(name, [[]]),
        }
        for name in GENERATED_TABS
    ]
    result = _google_json(
        base + "/values:batchUpdate",
        token,
        method="POST",
        payload={"valueInputOption": "RAW", "includeValuesInResponse": False, "data": data},
    )
    return {
        "spreadsheet_id": spreadsheet_id,
        "tabs_created": missing,
        "tabs_written": list(GENERATED_TABS),
        "updated_cells": result.get("totalUpdatedCells", 0),
        "updated_rows": result.get("totalUpdatedRows", 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Google Sheets views from the canonical infrastructure ledger.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-json", type=Path, default=Path("data/derived/google_sheets_projection.json"))
    parser.add_argument("--spreadsheet-id", help="Target spreadsheet for --apply. The canonical ledger remains the source of truth.")
    parser.add_argument("--apply", action="store_true", help="Replace generated tabs in the target Google Sheet.")
    parser.add_argument("--access-token-env", default="GOOGLE_OAUTH_ACCESS_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")
    if args.apply and not args.spreadsheet_id:
        parser.error("--spreadsheet-id is required with --apply")

    projection = build_projection(args.root)
    summary: dict[str, Any] = {name: max(len(rows) - 1, 0) for name, rows in projection.items()}
    if not args.dry_run:
        write_json(args.output_json, {"schema_version": "google-sheets-projection.v1", "tabs": projection})

    if args.apply:
        token = os.getenv(args.access_token_env) or os.getenv("GOOGLE_SHEETS_BEARER_TOKEN")
        if not token:
            raise SystemExit(
                f"Missing OAuth token. Set {args.access_token_env} or GOOGLE_SHEETS_BEARER_TOKEN with Sheets write scope."
            )
        summary["apply"] = apply_projection(args.spreadsheet_id, projection, token)

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
