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
ELIGIBLE_SEC_FORMS = {"10-K", "10-Q"}


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def parse_utc_timestamp(value: Any, *, event_id: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"missing SEC published_at for {event_id}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid SEC published_at for {event_id}: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timezone-naive SEC published_at for {event_id}: {value}")
    return parsed.astimezone(timezone.utc)


def normalize_period(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize only verified primary-source SEC reporting-period facts.

    SEC submissions exposes reportDate as filing metadata. We preserve that date as
    period_end, but deliberately do not infer fiscal year or quarter from calendar
    dates. Only accepted 10-K/10-Q events that still carry the collector's strict
    freshness PASS are eligible. The period end must not be later than the SEC
    publication timestamp already verified elsewhere in the ledger pipeline.
    """

    if row.get("source_adapter") != "sec_edgar":
        return None
    if row.get("document_type") not in ELIGIBLE_SEC_FORMS:
        return None

    event_id = row.get("event_id")
    if row.get("freshness") != "PASS":
        raise ValueError(f"SEC freshness is not PASS for {event_id}")

    report_date = row.get("report_date")
    if not report_date:
        raise ValueError(f"missing SEC report_date for {event_id}")
    try:
        parsed = date.fromisoformat(str(report_date))
    except ValueError as exc:
        raise ValueError(f"invalid SEC report_date for {event_id}: {report_date}") from exc

    published_at = parse_utc_timestamp(row.get("published_at"), event_id=event_id)
    if parsed > published_at.date():
        raise ValueError(
            f"SEC report_date is after published_at for {event_id}: "
            f"{parsed.isoformat()} > {published_at.date().isoformat()}"
        )

    accession_number = str(row.get("accession_number") or "").strip()
    if not accession_number:
        raise ValueError(f"missing SEC accession_number for {event_id}")

    return {
        "event_id": event_id,
        "company_id": row.get("company_id"),
        "document_type": row.get("document_type"),
        "accession_number": accession_number,
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
        "contract": (
            "period_end equals SEC submissions reportDate for freshness-PASS 10-K/10-Q events; "
            "period_end cannot be after verified publication time; fiscal year/quarter are never inferred"
        ),
    }


def main() -> int:
    result = audit(load_ndjson(EVENTS_PATH))
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
