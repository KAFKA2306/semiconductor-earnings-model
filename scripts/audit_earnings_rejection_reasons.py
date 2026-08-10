from __future__ import annotations

import json
import urllib.parse
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

ADAPTER_CONTRACTS = {
    "sec_edgar": {
        "domains": {"www.sec.gov"},
        "identity_fields": ("accession_number", "cik"),
        "published_timezones": {"UTC"},
    },
    "tdnet_public": {
        "domains": {"www.release.tdnet.info"},
        "identity_fields": ("security_code",),
        "published_timezones": {"Asia/Tokyo"},
    },
}

REQUIRED_REJECTED_FIELDS = (
    "schema_version",
    "event_id",
    "company_id",
    "company_name",
    "document_type",
    "published_at",
    "published_timezone",
    "retrieved_at",
    "source_adapter",
    "source_url",
)


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


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

        missing_fields = [field for field in REQUIRED_REJECTED_FIELDS if not row.get(field)]
        if missing_fields:
            issues.append({
                "code": "MISSING_REJECTION_PROVENANCE_FIELD",
                "event_id": event_id,
                "fields": missing_fields,
            })

        if row.get("schema_version") != "earnings-event.v1":
            issues.append({
                "code": "INVALID_REJECTED_SCHEMA_VERSION",
                "event_id": event_id,
                "schema_version": row.get("schema_version"),
            })

        published_at = parse_timestamp(row.get("published_at"))
        retrieved_at = parse_timestamp(row.get("retrieved_at"))
        if published_at is None:
            issues.append({"code": "INVALID_REJECTED_PUBLISHED_AT", "event_id": event_id})
        if retrieved_at is None:
            issues.append({"code": "INVALID_REJECTED_RETRIEVED_AT", "event_id": event_id})
        if published_at is not None and retrieved_at is not None and retrieved_at < published_at:
            issues.append({
                "code": "REJECTED_RETRIEVED_BEFORE_PUBLISHED",
                "event_id": event_id,
                "published_at": row.get("published_at"),
                "retrieved_at": row.get("retrieved_at"),
            })

        adapter_contract = ADAPTER_CONTRACTS.get(source_adapter)
        if adapter_contract is None:
            issues.append({
                "code": "UNKNOWN_REJECTION_SOURCE_ADAPTER",
                "event_id": event_id,
                "source_adapter": source_adapter,
            })
        else:
            source_url = str(row.get("source_url") or "")
            parsed_url = urllib.parse.urlparse(source_url)
            if parsed_url.scheme != "https" or parsed_url.netloc not in adapter_contract["domains"]:
                issues.append({
                    "code": "REJECTION_SOURCE_DOMAIN_MISMATCH",
                    "event_id": event_id,
                    "source_adapter": source_adapter,
                    "source_url": source_url,
                })
            missing_identity = [
                field for field in adapter_contract["identity_fields"] if row.get(field) in (None, "")
            ]
            if missing_identity:
                issues.append({
                    "code": "MISSING_REJECTION_SOURCE_IDENTITY",
                    "event_id": event_id,
                    "source_adapter": source_adapter,
                    "fields": missing_identity,
                })
            published_timezone = row.get("published_timezone")
            if published_timezone not in adapter_contract["published_timezones"]:
                issues.append({
                    "code": "REJECTION_PUBLISHED_TIMEZONE_MISMATCH",
                    "event_id": event_id,
                    "source_adapter": source_adapter,
                    "published_timezone": published_timezone,
                    "allowed_timezones": sorted(adapter_contract["published_timezones"]),
                })

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
            if source_adapter != "sec_edgar":
                issues.append({
                    "code": "SIX_K_CONTENT_REJECTION_NON_SEC_SOURCE",
                    "event_id": event_id,
                    "source_adapter": source_adapter,
                })

    return {
        "schema_version": "earnings-rejection-reason-audit.v2",
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
            "rejection_provenance_required": True,
            "source_adapter_domain_binding_required": True,
            "source_adapter_timezone_binding_required": True,
            "retrieved_at_not_before_published_at": True,
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
