from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from semicon.ledger import DERIVED_METRICS, canonical_key, load_json, load_jsonl, validate_fact, validate_provenance

ROOT = Path(__file__).resolve().parents[1]

DATASETS = {
    "fact": "data/canonical/facts.jsonl",
    "event": "data/canonical/events.jsonl",
    "project": "data/canonical/capex_projects.jsonl",
    "facility": "data/canonical/facilities.jsonl",
    "commitment": "data/canonical/customer_commitments.jsonl",
    "backlog": "data/canonical/orders_backlog.jsonl",
}


def validate(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    counts: dict[str, int] = {}
    for record_type, rel in DATASETS.items():
        records = load_jsonl(root / rel)
        counts[record_type] = len(records)
        keys = [canonical_key(record_type, row) for row in records]
        dupes = [key for key, count in Counter(keys).items() if count > 1]
        if dupes:
            errors.append(f"{record_type}: duplicate keys: {dupes[:10]}")
        for row in records:
            if record_type == "fact":
                for err in validate_fact(row):
                    errors.append(f"fact:{row.get('fact_id')}:{err}")
                if row.get("metric") in DERIVED_METRICS:
                    errors.append(f"fact:{row.get('fact_id')}:derived metric in canonical")
            for err in validate_provenance(row):
                errors.append(f"{record_type}:{canonical_key(record_type, row)}:{err}")
            if row.get("value") is None and row.get("null_reason") is None and record_type == "fact":
                errors.append(f"fact:{row.get('fact_id')}:NULL without null_reason")
    registry = load_json(root / "data/registry/entities.json", {"entities": []}) or {"entities": []}
    entity_ids = [str(x.get("entity_id") or x.get("id") or "") for x in registry.get("entities", [])]
    if len(entity_ids) != len(set(entity_ids)):
        errors.append("entity registry contains duplicate entity_id")
    return {"status": "PASS" if not errors else "FAIL", "counts": counts, "entity_count": len(entity_ids), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = validate(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
