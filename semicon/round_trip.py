from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from semicon.export.google_sheets import build_projection
from semicon.ingest.google_sheets import build_import
from semicon.ledger import canonical_key, load_jsonl, write_json

ROOT = Path(__file__).resolve().parents[1]


def _projection_snapshot(projection: dict[str, list[list[Any]]], spreadsheet_id: str = "canonical-regenerated") -> dict[str, Any]:
    body = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "google-sheets-raw.v1",
        "spreadsheet_id": spreadsheet_id,
        "source_name": "google_sheets",
        "imported_at": "1970-01-01T00:00:00Z",
        "source_sha256": hashlib.sha256(body).hexdigest(),
        "sheets": [{"name": name, "classification": "projection", "rows": rows} for name, rows in projection.items()],
    }


def _signature(record_type: str, row: dict[str, Any]) -> tuple[Any, ...]:
    if record_type == "fact":
        return (canonical_key(record_type, row), row.get("value"), row.get("unit"))
    if record_type == "event":
        return (row.get("event_id"), row.get("entity_id"), row.get("event_type"), row.get("announcement_date"), row.get("status"))
    if record_type == "project":
        plan = row.get("capex_plan") or {}
        return (row.get("project_id"), row.get("entity_id"), row.get("event_type"), row.get("project_name"), plan.get("low"), plan.get("high"), row.get("capacity_before"), row.get("capacity_after"), row.get("status"))
    if record_type == "facility":
        return (row.get("facility_id"), row.get("entity_id"), row.get("facility_name"), row.get("fiscal_year"))
    if record_type == "commitment":
        return (row.get("commitment_id"), row.get("entity_id"), row.get("customer_name"), row.get("commitment_type"), row.get("amount"), row.get("volume"))
    if record_type == "backlog":
        return (row.get("record_id"), row.get("entity_id"), row.get("fiscal_year"), row.get("segment"), row.get("orders_received"), row.get("order_backlog"))
    raise KeyError(record_type)


def validate_round_trip(root: Path = ROOT) -> dict[str, Any]:
    projection = build_projection(root)
    snapshot = _projection_snapshot(projection)
    original = {
        "fact": load_jsonl(root / "data/canonical/facts.jsonl"),
        "event": load_jsonl(root / "data/canonical/events.jsonl"),
        "project": load_jsonl(root / "data/canonical/capex_projects.jsonl"),
        "facility": load_jsonl(root / "data/canonical/facilities.jsonl"),
        "commitment": load_jsonl(root / "data/canonical/customer_commitments.jsonl"),
        "backlog": load_jsonl(root / "data/canonical/orders_backlog.jsonl"),
    }
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        write_json(temp_root / "data/primary/entities.json", {"entities": []})
        _, payload = build_import(snapshot, root=temp_root)
    regenerated = {
        "fact": payload["facts"],
        "event": payload["events"],
        "project": payload["projects"],
        "facility": payload["facilities"],
        "commitment": payload["commitments"],
        "backlog": payload["backlog"],
    }
    mismatches: dict[str, Any] = {}
    for record_type in original:
        before = sorted(_signature(record_type, row) for row in original[record_type])
        after = sorted(_signature(record_type, row) for row in regenerated[record_type])
        if before != after:
            mismatches[record_type] = {"before_count": len(before), "after_count": len(after), "before_only": [x for x in before if x not in after][:10], "after_only": [x for x in after if x not in before][:10]}
    return {"status": "PASS" if not mismatches else "FAIL", "mismatches": mismatches, "tabs": list(projection)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = validate_round_trip(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
