#!/usr/bin/env python3
"""Derive deterministic QoQ/YoY using only the persisted verified revenue actual ledger."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
METRICS_PATH = LEDGER_DIR / "verified_revenue_latest.json"
LINEAGE_PATH = LEDGER_DIR / "verified_revenue_lineage_audit_latest.json"
ACTUALS_PATH = LEDGER_DIR / "verified_revenue_actuals.ndjson"
MANIFEST_PATH = LEDGER_DIR / "verified_revenue_actuals_manifest.json"
OUTPUT_PATH = LEDGER_DIR / "verified_revenue_persisted_growth_latest.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _pct(current: Any, prior: Any) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(prior, (int, float)):
        return None
    prior_d = Decimal(str(prior))
    if prior_d == 0:
        return None
    value = ((Decimal(str(current)) - prior_d) / abs(prior_d) * Decimal("100")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(value)


def derive_persisted_growth(metrics_doc: dict[str, Any], lineage_doc: dict[str, Any], manifest: dict[str, Any], actuals: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    growth: list[dict[str, Any]] = []
    not_calculated: list[dict[str, Any]] = []
    metrics = metrics_doc.get("metrics", [])
    if metrics_doc.get("status") != "PASS" or metrics_doc.get("issues") or metrics_doc.get("verified_metrics_total") != len(metrics):
        issues.append({"code": "VERIFIED_REVENUE_NOT_PASS"})
    if lineage_doc.get("status") != "PASS" or lineage_doc.get("issues") or lineage_doc.get("checked_metrics_total") != len(metrics):
        issues.append({"code": "VERIFIED_REVENUE_LINEAGE_NOT_PASS"})
    if manifest.get("status") != "PASS" or manifest.get("issues") or manifest.get("actuals_total") != len(actuals):
        issues.append({"code": "PERSISTED_ACTUALS_NOT_PASS"})

    for row in actuals:
        parsed = urlparse(str(row.get("source_url") or ""))
        if row.get("schema_version") != "verified-revenue-actual.v1" or row.get("metric") != "revenue" or row.get("unit") != "USD" or row.get("taxonomy") != "us-gaap" or parsed.scheme != "https" or parsed.netloc != "data.sec.gov" or not parsed.path.startswith("/api/xbrl/companyfacts/CIK") or not isinstance(row.get("value"), (int, float)) or not isinstance(row.get("duration_days"), int):
            issues.append({"code": "UNSAFE_PERSISTED_ACTUAL", "company_id": row.get("company_id"), "period_end": row.get("period_end")})

    for metric in metrics:
        event_id = metric.get("event_id")
        candidates = [row for row in actuals if row.get("company_id") == metric.get("company_id") and row.get("concept") == metric.get("concept") and row.get("unit") == "USD"]
        current = [row for row in candidates if row.get("accession_number") == metric.get("accession_number") and row.get("document_type") == metric.get("document_type") and row.get("period_end") == metric.get("period_end") and row.get("value") == metric.get("value")]
        unique_current = {(r.get("period_start"), r.get("period_end"), r.get("value")): r for r in current}
        if len(unique_current) != 1:
            issues.append({"code": "AMBIGUOUS_CURRENT_PERSISTED_ACTUAL", "event_id": event_id, "count": len(unique_current)})
            continue
        cur = next(iter(unique_current.values()))
        cur_end = parse_date(cur.get("period_end"))
        if cur_end is None:
            issues.append({"code": "INVALID_CURRENT_PERIOD", "event_id": event_id})
            continue
        cur_duration = cur["duration_days"]

        specs = (("QoQ", 70, 110, False), ("YoY", 350, 380, True))
        for growth_type, min_gap, max_gap, same_accession in specs:
            if growth_type == "QoQ" and not 70 <= cur_duration <= 110:
                not_calculated.append({"event_id": event_id, "growth_type": growth_type, "reason": "CURRENT_FACT_NOT_STANDALONE_QUARTER"})
                continue
            prior: list[dict[str, Any]] = []
            for row in candidates:
                prior_end = parse_date(row.get("period_end"))
                if prior_end is None:
                    continue
                if same_accession and row.get("accession_number") != cur.get("accession_number"):
                    continue
                gap = (cur_end - prior_end).days
                if min_gap <= gap <= max_gap and abs(cur_duration - row["duration_days"]) <= 7:
                    prior.append(row)
            unique_prior = {(r.get("period_start"), r.get("period_end"), r.get("value")): r for r in prior}
            if not unique_prior:
                not_calculated.append({"event_id": event_id, "growth_type": growth_type, "reason": f"NO_COMPARABLE_PRIOR_{'QUARTER' if growth_type == 'QoQ' else 'YEAR'}_ACTUAL"})
                continue
            if len(unique_prior) != 1:
                issues.append({"code": f"AMBIGUOUS_PRIOR_{'QUARTER' if growth_type == 'QoQ' else 'YEAR'}_ACTUAL", "event_id": event_id, "count": len(unique_prior)})
                continue
            prior_row = next(iter(unique_prior.values()))
            pct = _pct(cur.get("value"), prior_row.get("value"))
            if pct is None:
                issues.append({"code": "ZERO_OR_INVALID_PRIOR_VALUE", "event_id": event_id, "growth_type": growth_type})
                continue
            item = {"event_id": event_id, "company_id": metric.get("company_id"), "ticker": metric.get("ticker"), "metric": "revenue", "growth_type": growth_type, "current_value": cur["value"], "prior_value": prior_row["value"], "unit": "USD", "current_period_start": cur["period_start"], "current_period_end": cur["period_end"], "prior_period_start": prior_row["period_start"], "prior_period_end": prior_row["period_end"], "taxonomy": "us-gaap", "concept": metric.get("concept"), "source_url": cur["source_url"], "actuals_ledger": "data/earnings_ledger/verified_revenue_actuals.ndjson", "verification": "current and prior values were joined from the persisted verified revenue actual ledger; this comparator performs no network access"}
            item["qoq_percent" if growth_type == "QoQ" else "yoy_percent"] = pct
            growth.append(item)

    return {"schema_version": "verified-revenue-persisted-growth.v1", "run_at": iso_now(), "eligible_metrics_total": len(metrics), "calculated_growth_total": len(growth), "growth": growth, "not_calculated": not_calculated, "issues": issues, "status": "PASS" if not issues else "FAIL", "contract": "QoQ/YoY compares persisted verified actuals only. The comparator has no HTTP client and missing/ambiguous comparables produce no fabricated value."}


def main() -> int:
    result = derive_persisted_growth(load_json(METRICS_PATH), load_json(LINEAGE_PATH), load_json(MANIFEST_PATH), load_ndjson(ACTUALS_PATH))
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
