#!/usr/bin/env python3
"""Fail-closed audit for persisted verified revenue YoY duration relationships."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
INPUT_PATH = LEDGER_DIR / "verified_revenue_growth_latest.json"
OUTPUT_PATH = LEDGER_DIR / "verified_revenue_growth_duration_audit_latest.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def audit_growth(doc: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    growth = doc.get("growth")
    if not isinstance(growth, list):
        growth = []
        issues.append({"code": "GROWTH_NOT_LIST"})

    if doc.get("status") != "PASS" or doc.get("issues"):
        issues.append({"code": "GROWTH_ARTIFACT_NOT_PASS"})
    if doc.get("schema_version") != "verified-revenue-growth.v1":
        issues.append({"code": "UNEXPECTED_SCHEMA_VERSION"})
    if doc.get("calculated_yoy_total") != len(growth):
        issues.append({"code": "CALCULATED_COUNT_MISMATCH"})

    checked = 0
    for row in growth:
        event_id = row.get("event_id") if isinstance(row, dict) else None
        if not isinstance(row, dict):
            issues.append({"code": "GROWTH_ROW_NOT_OBJECT", "event_id": event_id})
            continue

        parsed = urlparse(str(row.get("source_url") or ""))
        if (
            row.get("growth_type") != "YoY"
            or row.get("metric") != "revenue"
            or row.get("unit") != "USD"
            or row.get("taxonomy") != "us-gaap"
            or row.get("document_type") not in {"10-K", "10-Q"}
            or not row.get("accession_number")
            or parsed.scheme != "https"
            or parsed.netloc != "data.sec.gov"
            or not parsed.path.startswith("/api/xbrl/companyfacts/CIK")
        ):
            issues.append({"code": "UNSAFE_GROWTH_PROVENANCE", "event_id": event_id})
            continue

        current_start = parse_date(row.get("current_period_start"))
        current_end = parse_date(row.get("current_period_end"))
        prior_start = parse_date(row.get("prior_period_start"))
        prior_end = parse_date(row.get("prior_period_end"))
        if None in {current_start, current_end, prior_start, prior_end}:
            issues.append({"code": "INVALID_PERIOD_DATE", "event_id": event_id})
            continue
        assert current_start and current_end and prior_start and prior_end

        current_duration = (current_end - current_start).days
        prior_duration = (prior_end - prior_start).days
        end_gap = (current_end - prior_end).days
        duration_gap = abs(current_duration - prior_duration)
        if current_duration <= 0 or prior_duration <= 0:
            issues.append({"code": "NON_POSITIVE_PERIOD_DURATION", "event_id": event_id})
            continue
        if not 350 <= end_gap <= 380:
            issues.append({"code": "INVALID_YOY_END_GAP", "event_id": event_id, "days": end_gap})
            continue
        if duration_gap > 7:
            issues.append({"code": "INVALID_YOY_DURATION_GAP", "event_id": event_id, "days": duration_gap})
            continue
        checked += 1

    for row in doc.get("not_calculated", []):
        if isinstance(row, dict) and any(key in row for key in ("yoy_percent", "current_value", "prior_value")):
            issues.append({"code": "UNCALCULATED_ROW_CONTAINS_GROWTH_VALUE", "event_id": row.get("event_id")})

    return {
        "schema_version": "verified-revenue-growth-duration-audit.v1",
        "run_at": iso_now(),
        "growth_rows_total": len(growth),
        "checked_growth_rows_total": checked,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": {
            "same_primary_sec_companyfacts_provenance_required": True,
            "yoy_period_end_gap_days": [350, 380],
            "maximum_duration_difference_days": 7,
            "non_positive_durations_rejected": True,
            "uncalculated_rows_must_not_contain_values": True,
        },
    }


def main() -> int:
    doc = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    result = audit_growth(doc)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
