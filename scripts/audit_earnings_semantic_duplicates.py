from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
OUTPUT_PATH = LEDGER_DIR / "semantic_duplicate_audit_latest.json"


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def semantic_key(row: dict[str, Any]) -> str | None:
    """Return a deterministic SEC earnings identity when the reporting period is proven.

    The SEC submissions feed supplies reportDate as primary-source metadata.  We do not
    infer a fiscal quarter or fiscal year from calendar dates.  If reportDate is absent,
    no semantic key is fabricated and the event remains outside this dedupe gate.
    """

    if row.get("source_adapter") != "sec_edgar":
        return None
    company_id = row.get("company_id")
    report_date = row.get("report_date")
    document_type = row.get("document_type")
    if not company_id or not report_date or not document_type:
        return None
    return f"{company_id}|{report_date}|{document_type}"


def audit(events: list[dict[str, Any]]) -> dict[str, Any]:
    seen: dict[str, str] = {}
    duplicates: list[dict[str, str]] = []
    keyed_events = 0

    for row in events:
        key = semantic_key(row)
        if key is None:
            continue
        keyed_events += 1
        event_id = str(row.get("event_id") or "")
        previous = seen.get(key)
        if previous is not None and previous != event_id:
            duplicates.append(
                {
                    "code": "DUPLICATE_SEMANTIC_EARNINGS_EVENT",
                    "semantic_key": key,
                    "first_event_id": previous,
                    "duplicate_event_id": event_id,
                }
            )
        else:
            seen[key] = event_id

    return {
        "schema_version": "earnings-semantic-duplicate-audit.v1",
        "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "events_total": len(events),
        "events_with_primary_period_key": keyed_events,
        "duplicate_count": len(duplicates),
        "duplicates": duplicates,
        "status": "PASS" if not duplicates else "FAIL",
        "key_contract": "SEC company_id + primary-source report_date + document_type; no fiscal-period inference",
    }


def main() -> int:
    result = audit(load_ndjson(EVENTS_PATH))
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
