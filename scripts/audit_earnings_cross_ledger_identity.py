from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
ACCEPTED_PATH = LEDGER_DIR / "events.ndjson"
REJECTED_PATH = LEDGER_DIR / "rejected.ndjson"
OUTPUT_PATH = LEDGER_DIR / "cross_ledger_identity_audit_latest.json"


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number} must be a JSON object")
        rows.append(value)
    return rows


def normalize_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def identity_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()

    event_id = row.get("event_id")
    if isinstance(event_id, str) and event_id.strip():
        keys.add(f"event_id:{event_id.strip()}")

    source_adapter = row.get("source_adapter")
    accession = row.get("accession_number")
    if source_adapter == "sec_edgar" and isinstance(accession, str) and accession.strip():
        normalized_accession = accession.replace("-", "").strip()
        if normalized_accession:
            keys.add(f"sec_accession:{normalized_accession}")

    source_url = normalize_url(row.get("source_url"))
    if source_url:
        keys.add(f"source_url:{source_url}")

    return keys


def audit(accepted: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    accepted_index: dict[str, str] = {}
    rejected_index: dict[str, str] = {}

    for ledger_name, rows, index in (
        ("accepted", accepted, accepted_index),
        ("rejected", rejected, rejected_index),
    ):
        for row_number, row in enumerate(rows, start=1):
            event_id = row.get("event_id")
            keys = identity_keys(row)
            if not isinstance(event_id, str) or not event_id.strip():
                issues.append(
                    {
                        "code": "MISSING_EVENT_ID",
                        "ledger": ledger_name,
                        "row_number": row_number,
                    }
                )
                continue
            if not keys:
                issues.append(
                    {
                        "code": "MISSING_STABLE_IDENTITY",
                        "ledger": ledger_name,
                        "event_id": event_id,
                    }
                )
                continue
            for key in keys:
                index.setdefault(key, event_id)

    for key in sorted(set(accepted_index) & set(rejected_index)):
        issues.append(
            {
                "code": "ACCEPTED_REJECTED_IDENTITY_COLLISION",
                "identity": key,
                "accepted_event_id": accepted_index[key],
                "rejected_event_id": rejected_index[key],
            }
        )

    collisions = [issue for issue in issues if issue["code"] == "ACCEPTED_REJECTED_IDENTITY_COLLISION"]
    return {
        "schema_version": "earnings-cross-ledger-identity-audit.v1",
        "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "accepted_events_total": len(accepted),
        "rejected_events_total": len(rejected),
        "accepted_identity_keys_total": len(accepted_index),
        "rejected_identity_keys_total": len(rejected_index),
        "collision_count": len(collisions),
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": (
            "an event identity may exist in exactly one ledger state; event_id, SEC accession, "
            "and normalized primary-source URL are checked without inventing missing identifiers"
        ),
    }


def main() -> int:
    try:
        result = audit(load_ndjson(ACCEPTED_PATH), load_ndjson(REJECTED_PATH))
    except (json.JSONDecodeError, ValueError) as exc:
        result = {
            "schema_version": "earnings-cross-ledger-identity-audit.v1",
            "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "issues": [{"code": "LEDGER_PARSE_ERROR", "detail": str(exc)}],
            "status": "FAIL",
        }
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
