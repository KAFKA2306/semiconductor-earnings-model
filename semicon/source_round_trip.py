from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from semicon.export.google_sheets import build_projection
from semicon.ingest.google_sheets import DEFAULT_SPREADSHEET_ID, parse_xlsx_bytes
from semicon.ledger import blank_to_none, normalize_header

ROOT = Path(__file__).resolve().parents[1]


def _dict_rows(rows: list[list[Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    headers = [normalize_header(value) for value in rows[0]]
    out: list[dict[str, Any]] = []
    for raw in rows[1:]:
        row = {
            headers[i]: blank_to_none(raw[i] if i < len(raw) else None)
            for i in range(len(headers))
            if headers[i]
        }
        if any(value is not None for value in row.values()):
            out.append(row)
    return out


def _sheet(snapshot: dict[str, Any], name: str) -> list[dict[str, Any]]:
    for sheet in snapshot.get("sheets", []):
        if normalize_header(sheet.get("name")) == normalize_header(name):
            return _dict_rows(sheet.get("rows") or [])
    return []


def _projection_rows(projection: dict[str, list[list[Any]]], name: str) -> list[dict[str, Any]]:
    return _dict_rows(projection.get(name, []))


def _norm(value: Any) -> str | None:
    value = blank_to_none(value)
    return None if value is None else str(value)


def validate_source_round_trip(root: Path = ROOT) -> dict[str, Any]:
    matches = sorted((root / "data/raw/google_sheets_import" / DEFAULT_SPREADSHEET_ID).glob("*/source.xlsx"))
    if not matches:
        return {"status": "FAIL", "errors": ["archived source.xlsx not found"], "checks": {}}

    source_path = matches[-1]
    snapshot = parse_xlsx_bytes(
        source_path.read_bytes(),
        spreadsheet_id=DEFAULT_SPREADSHEET_ID,
        imported_at="1970-01-01T00:00:00Z",
        source_name="google_sheets",
    )
    projection = build_projection(root)
    errors: list[str] = []
    checks: dict[str, int] = {}

    # 1) Every source issuer must survive in regenerated Company_Master.
    source_entities = _sheet(snapshot, "Issuer_Master")
    projected_entities = {
        str(row.get("entity_id")): row
        for row in _projection_rows(projection, "Company_Master")
        if row.get("entity_id") is not None
    }
    for row in source_entities:
        entity_id = _norm(row.get("issuer_id") or row.get("entity_id"))
        target = projected_entities.get(entity_id or "")
        if target is None:
            errors.append(f"missing projected entity:{entity_id}")
            continue
        comparisons = {
            "company_name": (row.get("company_name"), target.get("company_name")),
            "country": (row.get("country"), target.get("country")),
            "currency": (row.get("reporting_currency") or row.get("currency"), target.get("currency")),
            "role": (row.get("primary_role"), target.get("role")),
        }
        for field, (before, after) in comparisons.items():
            if _norm(before) != _norm(after):
                errors.append(f"entity:{entity_id}:{field}:{before!r}!={after!r}")
    checks["source_entities"] = len(source_entities)

    # 2) Index membership is canonicalized into Company_Master.index_membership.
    membership_index: dict[str, set[tuple[str | None, str | None, str | None, str | None]]] = {}
    for entity_id, row in projected_entities.items():
        raw = row.get("index_membership")
        try:
            memberships = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except json.JSONDecodeError:
            memberships = []
        membership_index[entity_id] = {
            (
                _norm(item.get("index_name")),
                _norm(item.get("as_of_date")),
                _norm(item.get("security_ticker_or_code")),
                _norm(item.get("source_url")),
            )
            for item in memberships
        }
    source_memberships = _sheet(snapshot, "Index_Membership")
    for row in source_memberships:
        entity_id = _norm(row.get("issuer_id") or row.get("entity_id"))
        signature = (
            _norm(row.get("index_name")),
            _norm(row.get("as_of_date")),
            _norm(row.get("security_ticker_or_code")),
            _norm(row.get("source_url")),
        )
        if signature not in membership_index.get(entity_id or "", set()):
            errors.append(f"missing index membership:{entity_id}:{signature}")
    checks["source_index_memberships"] = len(source_memberships)

    # 3) Every CapEx event must survive in lifecycle and project views with key quantitative fields.
    lifecycle = {
        str(row.get("event_id")): row
        for row in _projection_rows(projection, "Project_Lifecycle")
        if row.get("event_id") is not None
    }
    projects = {
        str(row.get("event_id") or row.get("project_id")): row
        for row in _projection_rows(projection, "CapEx_Projects")
        if row.get("event_id") is not None or row.get("project_id") is not None
    }
    source_events = _sheet(snapshot, "CapEx_Events")
    for row in source_events:
        event_id = _norm(row.get("event_id"))
        event = lifecycle.get(event_id or "")
        project = projects.get(event_id or "")
        if event is None:
            errors.append(f"missing lifecycle event:{event_id}")
            continue
        if project is None:
            errors.append(f"missing capex project:{event_id}")
            continue
        for field, before, after in (
            ("entity_id", row.get("issuer_id"), event.get("entity_id")),
            ("announcement_date", row.get("announced_date"), event.get("announcement_date")),
            ("project_name", row.get("project_name"), event.get("project_name")),
            ("status", row.get("status"), event.get("status")),
            ("source_url", row.get("source_url"), event.get("source_url")),
            ("capex_plan_low", row.get("amount_low_local_mm"), project.get("capex_plan_low")),
            ("capex_plan_high", row.get("amount_high_local_mm"), project.get("capex_plan_high")),
            ("currency", row.get("currency"), project.get("currency")),
            ("capacity_metric", row.get("capacity_metric"), project.get("capacity_metric")),
            ("capacity_before", row.get("capacity_current"), project.get("capacity_before")),
            ("capacity_after", row.get("capacity_target"), project.get("capacity_after")),
            ("capacity_unit", row.get("capacity_unit"), project.get("capacity_unit")),
        ):
            if _norm(before) != _norm(after):
                errors.append(f"event:{event_id}:{field}:{before!r}!={after!r}")
    checks["source_capex_events"] = len(source_events)

    # 4) Original source URLs, including index-source URLs, must survive in regenerated Sources.
    source_urls = {
        _norm(row.get("source_url"))
        for sheet_name in ("Index_Membership", "CapEx_Events", "Sources")
        for row in _sheet(snapshot, sheet_name)
        if _norm(row.get("source_url"))
    }
    projected_urls = {
        _norm(row.get("source_url"))
        for row in _projection_rows(projection, "Sources")
        if _norm(row.get("source_url"))
    }
    missing_urls = sorted(url for url in source_urls if url not in projected_urls)
    for url in missing_urls:
        errors.append(f"missing regenerated source_url:{url}")
    checks["source_urls"] = len(source_urls)

    # Header-only canonical/derived tabs must not gain fabricated source records during migration.
    for tab in ("Financials", "Demand_Commitments", "Capacity_Metrics", "Decision_View"):
        count = len(_sheet(snapshot, tab))
        if count:
            errors.append(f"unexpected non-header source rows in {tab}:{count}")
        checks[f"source_{normalize_header(tab)}_rows"] = count

    return {
        "status": "PASS" if not errors else "FAIL",
        "source_archive": str(source_path.relative_to(root)),
        "checks": checks,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = validate_source_round_trip(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
