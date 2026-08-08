from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
OUTPUT_PATH = LEDGER_DIR / "accounting_basis_audit_latest.json"


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def classify_event(row: dict[str, Any]) -> dict[str, Any]:
    """Classify only what the primary filing type can support without inference.

    This is deliberately an event-level gate, not a metric classifier. Form 10-K and
    10-Q contain primary US-GAAP financial statements, but other sections can discuss
    non-GAAP measures. Item 2.02 earnings materials can contain both GAAP and non-GAAP
    measures under Regulation G. Form 20-F filers may use IFRS as issued by the IASB or
    US GAAP, so the form alone cannot determine the accounting basis.
    """

    event_id = str(row.get("event_id") or "")
    if not event_id:
        raise ValueError("missing event_id")

    adapter = row.get("source_adapter")
    document_type = str(row.get("document_type") or "")

    base = {
        "event_id": event_id,
        "company_id": row.get("company_id"),
        "document_type": document_type,
        "source_adapter": adapter,
        "metric_level_basis_required": True,
    }

    if adapter != "sec_edgar":
        return {
            **base,
            "event_accounting_context": "UNVERIFIED_PRIMARY_SOURCE_BASIS",
            "automatic_gaap_metric_use": False,
            "reason": "No deterministic accounting-basis rule is implemented for this source adapter.",
        }

    if document_type in {"10-K", "10-Q"}:
        return {
            **base,
            "event_accounting_context": "US_GAAP_PRIMARY_FINANCIAL_STATEMENTS_PRESENT",
            "automatic_gaap_metric_use": False,
            "reason": "The filing contains primary US-GAAP financial statements, but individual extracted metrics still require statement/XBRL provenance before being labeled GAAP.",
        }

    if document_type in {"8-K", "6-K"}:
        return {
            **base,
            "event_accounting_context": "MIXED_OR_UNVERIFIED_EARNINGS_MATERIAL",
            "automatic_gaap_metric_use": False,
            "reason": "Earnings materials may contain both GAAP and non-GAAP measures; classify each metric only from explicit primary-source labeling or reconciliation.",
        }

    if document_type == "20-F":
        return {
            **base,
            "event_accounting_context": "ACCOUNTING_BASIS_UNVERIFIED_FROM_FORM",
            "automatic_gaap_metric_use": False,
            "reason": "Form 20-F alone does not establish whether the financial statements use IFRS as issued by the IASB or US GAAP.",
        }

    raise ValueError(f"unsupported SEC earnings document_type: {document_type!r}")


def audit(events: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in events:
        try:
            item = classify_event(row)
        except ValueError as exc:
            issues.append({"code": "UNCLASSIFIED_ACCOUNTING_BASIS", "event_id": row.get("event_id"), "detail": str(exc)})
            continue

        event_id = item["event_id"]
        if event_id in seen:
            issues.append({"code": "DUPLICATE_ACCOUNTING_BASIS_EVENT", "event_id": event_id})
            continue
        seen.add(event_id)
        items.append(item)

    items.sort(key=lambda item: item["event_id"])
    return {
        "schema_version": "earnings-accounting-basis-audit.v1",
        "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "events_total": len(events),
        "classified_events_total": len(items),
        "items": items,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": "Never infer GAAP/non-GAAP at metric level from filing type alone; explicit primary-source metric provenance is required.",
        "primary_rules": [
            "SEC Regulation G / non-GAAP financial measures",
            "SEC Form 8-K Item 2.02 earnings materials",
        ],
    }


def main() -> int:
    result = audit(load_ndjson(EVENTS_PATH))
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
