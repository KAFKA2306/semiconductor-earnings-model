from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from semicon.ledger import (
    dedupe_or_conflict,
    load_json,
    load_jsonl,
    validate_provenance,
    write_json,
    write_jsonl,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = Path("data/raw/company_ir/capex_project_seed_v1.json")


def _doc_id(url: str) -> str:
    return "urlsha256:" + hashlib.sha256(url.encode("utf-8")).hexdigest()


def _materialize(
    record: dict[str, Any],
    *,
    record_type: str,
    source_map: dict[str, dict[str, Any]],
    source_path: Path,
    source_row: int,
    imported_at: str,
) -> dict[str, Any]:
    source_ref = str(record["source_ref"])
    source = source_map[source_ref]
    url = str(source["source_url"])
    provenance = {
        "import_source": "company_ir_seed",
        "spreadsheet_id": None,
        "sheet_name": str(source_path).replace("\\", "/"),
        "source_row": source_row,
        "imported_at": imported_at,
        "original_source_url": url,
        "doc_id": _doc_id(url),
        "raw_snapshot_sha256": source.get("source_sha256"),
        "source_ref": source_ref,
    }
    out = {k: v for k, v in record.items() if k != "source_ref"}
    out.update(
        {
            "source_system": "company_ir",
            "source_doc_id": provenance["doc_id"],
            "source_url": url,
            "quality_flag": "primary_source_extracted",
            "provenance": [provenance],
        }
    )
    errors = validate_provenance(out)
    if errors:
        raise ValueError(f"{record_type}:{source_row}: invalid provenance: {errors}")
    return out


def ingest(root: Path = ROOT, source_path: Path | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    rel = source_path or DEFAULT_SOURCE
    path = rel if rel.is_absolute() else root / rel
    raw = load_json(path, {}) or {}
    if raw.get("schema_version") != "company-ir-capex-seed.v1":
        raise ValueError(f"unsupported seed schema: {raw.get('schema_version')!r}")

    imported_at = str(raw["extracted_at"])
    source_map = {str(item["source_ref"]): item for item in raw.get("sources", [])}
    target_files = {
        "event": root / "data/canonical/events.jsonl",
        "project": root / "data/canonical/capex_projects.jsonl",
        "facility": root / "data/canonical/facilities.jsonl",
        "commitment": root / "data/canonical/customer_commitments.jsonl",
    }
    source_keys = {
        "event": "events",
        "project": "projects",
        "facility": "facilities",
        "commitment": "commitments",
    }

    results: dict[str, list[dict[str, Any]]] = {}
    conflicts: list[dict[str, Any]] = []
    duplicate_count = 0
    created_count = 0

    for record_type, target in target_files.items():
        incoming = [
            _materialize(
                record,
                record_type=record_type,
                source_map=source_map,
                source_path=path.relative_to(root) if path.is_relative_to(root) else path,
                source_row=index,
                imported_at=imported_at,
            )
            for index, record in enumerate(raw.get(source_keys[record_type], []), start=1)
        ]
        existing = load_jsonl(target)
        merged, duplicates, found_conflicts = dedupe_or_conflict(record_type, existing, incoming)
        results[record_type] = merged
        duplicate_count += duplicates
        created_count += max(len(merged) - len(existing), 0)
        conflicts.extend(conflict.as_dict() for conflict in found_conflicts)

    report = {
        "schema_version": "company-ir-capex-seed-report.v1",
        "source_file": str(path.relative_to(root) if path.is_relative_to(root) else path),
        "sources": len(source_map),
        "records_created": created_count,
        "duplicates": duplicate_count,
        "conflicts": len(conflicts),
        "event_count": len(results["event"]),
        "project_count": len(results["project"]),
        "facility_count": len(results["facility"]),
        "commitment_count": len(results["commitment"]),
    }

    if conflicts:
        if not dry_run:
            write_json(root / "data/conflicts/company_ir_seed_conflicts.json", conflicts)
        raise RuntimeError(json.dumps(report, ensure_ascii=False, sort_keys=True))

    if not dry_run:
        write_jsonl(target_files["event"], results["event"])
        write_jsonl(target_files["project"], results["project"])
        write_jsonl(target_files["facility"], results["facility"])
        write_jsonl(target_files["commitment"], results["commitment"])
        write_json(root / "data/raw/company_ir/capex_project_seed_v1_report.json", report)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest first-party company IR CapEx/capacity evidence into the infrastructure ledger.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = ingest(args.root, args.source, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
