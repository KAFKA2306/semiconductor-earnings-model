from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
REJECTED_PATH = LEDGER_DIR / "rejected.ndjson"
OUTPUT_PATH = LEDGER_DIR / "rejection_reason_audit_latest.json"

ALLOWED_REJECTION_REASONS = {
    "NOT_EARNINGS_RELATED",
    "UNVERIFIED_6K",
    "SOURCE_FETCH_FAILED",
}


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit_rejections(
    accepted: list[dict[str, Any]], rejected: list[dict[str, Any]]
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    accepted_ids = [str(row.get("event_id") or "") for row in accepted]
    rejected_ids = [str(row.get("event_id") or "") for row in rejected]

    accepted_nonempty = {event_id for event_id in accepted_ids if event_id}
    rejected_nonempty = {event_id for event_id in rejected_ids if event_id}

    for event_id, count in Counter(rejected_ids).items():
        if not event_id:
            issues.append({"code": "MISSING_REJECTED_EVENT_ID"})
        elif count > 1:
            issues.append({"code": "DUPLICATE_REJECTED_EVENT_ID", "event_id": event_id, "count": count})

    for event_id in sorted(accepted_nonempty & rejected_nonempty):
        issues.append({"code": "EVENT_ACCEPTED_AND_REJECTED", "event_id": event_id})

    reason_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    document_type_counts: Counter[str] = Counter()

    for row in rejected:
        event_id = str(row.get("event_id") or "")
        reason = row.get("rejection_reason")
        document_type = str(row.get("document_type") or "")
        source_adapter = str(row.get("source_adapter") or "")

        if row.get("freshness") != "REJECTED":
            issues.append({
                "code": "REJECTED_ROW_NOT_MARKED_REJECTED",
                "event_id": event_id,
                "freshness": row.get("freshness"),
            })
        if not isinstance(reason, str) or not reason:
            issues.append({"code": "MISSING_REJECTION_REASON", "event_id": event_id})
            continue
        if reason not in ALLOWED_REJECTION_REASONS:
            issues.append({
                "code": "UNKNOWN_REJECTION_REASON",
                "event_id": event_id,
                "rejection_reason": reason,
            })
            continue

        reason_counts[reason] += 1
        source_counts[source_adapter] += 1
        document_type_counts[document_type] += 1

        if reason == "UNVERIFIED_6K" and document_type != "6-K":
            issues.append({
                "code": "UNVERIFIED_6K_REASON_FORM_MISMATCH",
                "event_id": event_id,
                "document_type": document_type,
            })
        if reason == "SOURCE_FETCH_FAILED" and document_type != "6-K":
            issues.append({
                "code": "SOURCE_FETCH_FAILED_REASON_FORM_MISMATCH",
                "event_id": event_id,
                "document_type": document_type,
            })
        if reason == "NOT_EARNINGS_RELATED" and document_type == "6-K":
            # This is valid only after the 6-K document was fetched and content-tested.
            if source_adapter != "sec_edgar":
                issues.append({
                    "code": "SIX_K_CONTENT_REJECTION_NON_SEC_SOURCE",
                    "event_id": event_id,
                    "source_adapter": source_adapter,
                })

    return {
        "schema_version": "earnings-rejection-reason-audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "allowed_rejection_reasons": sorted(ALLOWED_REJECTION_REASONS),
        "accepted_events_total": len(accepted),
        "rejected_events_total": len(rejected),
        "reason_counts": dict(sorted(reason_counts.items())),
        "source_adapter_counts": dict(sorted(source_counts.items())),
        "document_type_counts": dict(sorted(document_type_counts.items())),
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "policy": {
            "unknown_reason_fails_closed": True,
            "accepted_rejected_collision_fails_closed": True,
            "reason_form_consistency_required": True,
        },
    }


def main() -> None:
    accepted = load_ndjson(EVENTS_PATH)
    rejected = load_ndjson(REJECTED_PATH)
    result = audit_rejections(accepted, rejected)
    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"rejection_reason_audit={result['status']} "
        f"rejected={result['rejected_events_total']} issues={len(result['issues'])}"
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
