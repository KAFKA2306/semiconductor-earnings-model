from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
OUTPUT_PATH = LEDGER_DIR / "period_normalization_latest.json"


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def normalize_period(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize only primary-source reporting-period facts.

    SEC submissions exposes reportDate as filing metadata. We preserve that date as
    period_end, but deliberately do not infer fiscal year or quarter from calendar
    dates. Non-SEC events remain unnormalized until their primary source exposes an
    equally authoritative period field.
    """

    if row.get("source_adapter") != "sec_edgar":
        return None
    report_date = row.get("report_date")
    if not report_date:
        return None
    try:
        parsed = date.fromisoformat(str(report_date))
    except ValueError as exc:
        raise ValueError(f"invalid SEC report_date for {row.get('event_id')}: {report_date}") from exc

    return {
        "event_id": row.get("event_id"),
        "company_id": row.get("company_id"),
        "document_type": row.get("document_type"),
        "period_end": parsed.isoformat(),
        "period_source": "SEC submissions reportDate",
        "fiscal_year": None,
        "fiscal_quarter": None,
        "normalization_status": "PRIMARY_PERIOD_END_ONLY",
    }


def audit(events: list[dict[str, Any]]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in events:
        try:
            item = normalize_period(row)
        except ValueError as exc:
            issues.append({"code": "INVALID_PRIMARY_PERIOD", "event_id": row.get("event_id"), "detail": str(exc)})
            continue
        if item is None:
            continue
        event_id = str(item.get("event_id") or "")
        if not event_id:
            issues.append({"code": "MISSING_EVENT_ID"})
            continue
        if event_id in seen:
            issues.append({"code": "DUPLICATE_NORMALIZED_EVENT", "event_id": event_id})
            continue
        seen.add(event_id)
        normalized.append(item)

    normalized.sort(key=lambda x: (x["period_end"], x["event_id"]))
    return {
        "schema_version": "earnings-period-normalization.v1",
        "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "events_total": len(events),
        "normalized_events_total": len(normalized),
        "items": normalized,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": "period_end equals SEC submissions reportDate; fiscal year/quarter are never inferred",
    }


def main() -> int:
    result = audit(load_ndjson(EVENTS_PATH))
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
