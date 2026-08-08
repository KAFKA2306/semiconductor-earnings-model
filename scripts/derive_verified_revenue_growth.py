#!/usr/bin/env python3
"""Derive fail-closed YoY revenue growth from comparable facts in the same SEC filing."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
METRICS_PATH = LEDGER_DIR / "verified_revenue_latest.json"
LINEAGE_PATH = LEDGER_DIR / "verified_revenue_lineage_audit_latest.json"
OUTPUT_PATH = LEDGER_DIR / "verified_revenue_growth_latest.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def request_json(url: str, user_agent: str, retries: int = 3, timeout: int = 30) -> dict[str, Any]:
    if not user_agent.strip():
        raise RuntimeError("SEC_USER_AGENT must not be empty")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "data.sec.gov" or not parsed.path.startswith("/api/xbrl/companyfacts/CIK"):
        raise RuntimeError(f"non-primary SEC Company Facts URL rejected: {url}")
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent, "Accept-Encoding": "identity", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    assert last is not None
    raise last


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _period_rows(metric: dict[str, Any], payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    concept = metric.get("concept")
    units = payload.get("facts", {}).get("us-gaap", {}).get(concept, {}).get("units", {}).get("USD", [])
    if not isinstance(units, list):
        return [], []

    accession = metric.get("accession_number")
    form = metric.get("document_type")
    end = metric.get("period_end")
    value = metric.get("value")
    current = [
        row for row in units
        if row.get("accn") == accession
        and row.get("form") == form
        and row.get("end") == end
        and row.get("val") == value
        and parse_date(row.get("start")) is not None
        and parse_date(row.get("end")) is not None
    ]

    current_unique = {
        (row.get("start"), row.get("end"), row.get("val")): row
        for row in current
    }
    current_rows = list(current_unique.values())
    if len(current_rows) != 1:
        return current_rows, []

    cur = current_rows[0]
    cur_start = parse_date(cur["start"])
    cur_end = parse_date(cur["end"])
    assert cur_start is not None and cur_end is not None
    cur_duration = (cur_end - cur_start).days
    fiscal_period = metric.get("fiscal_period")

    prior: list[dict[str, Any]] = []
    for row in units:
        if row.get("accn") != accession or row.get("form") != form:
            continue
        if fiscal_period and row.get("fp") not in {None, fiscal_period}:
            continue
        prior_start = parse_date(row.get("start"))
        prior_end = parse_date(row.get("end"))
        if prior_start is None or prior_end is None or not isinstance(row.get("val"), (int, float)):
            continue
        end_gap = (cur_end - prior_end).days
        duration_gap = abs(cur_duration - (prior_end - prior_start).days)
        if 350 <= end_gap <= 380 and duration_gap <= 7:
            prior.append(row)

    prior_unique = {
        (row.get("start"), row.get("end"), row.get("val")): row
        for row in prior
    }
    return current_rows, list(prior_unique.values())


def derive_yoy(
    metrics_doc: dict[str, Any],
    lineage_doc: dict[str, Any],
    payloads_by_url: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    growth: list[dict[str, Any]] = []
    not_calculated: list[dict[str, Any]] = []
    metrics = metrics_doc.get("metrics", [])

    if metrics_doc.get("status") != "PASS" or metrics_doc.get("issues"):
        issues.append({"code": "VERIFIED_REVENUE_NOT_PASS"})
    if lineage_doc.get("status") != "PASS" or lineage_doc.get("issues"):
        issues.append({"code": "VERIFIED_REVENUE_LINEAGE_NOT_PASS"})
    if metrics_doc.get("verified_metrics_total") != len(metrics):
        issues.append({"code": "VERIFIED_REVENUE_COUNT_MISMATCH"})
    if lineage_doc.get("checked_metrics_total") != len(metrics):
        issues.append({"code": "LINEAGE_COUNT_MISMATCH"})

    for metric in metrics:
        event_id = metric.get("event_id")
        source_url = metric.get("source_url")
        parsed = urlparse(source_url or "")
        if (
            metric.get("metric") != "revenue"
            or metric.get("unit") != "USD"
            or metric.get("taxonomy") != "us-gaap"
            or not isinstance(metric.get("value"), (int, float))
            or parsed.scheme != "https"
            or parsed.netloc != "data.sec.gov"
            or not parsed.path.startswith("/api/xbrl/companyfacts/CIK")
        ):
            issues.append({"code": "UNSAFE_CURRENT_METRIC", "event_id": event_id})
            continue
        payload = payloads_by_url.get(source_url)
        if payload is None:
            issues.append({"code": "MISSING_COMPANYFACTS_PAYLOAD", "event_id": event_id})
            continue

        current_rows, prior_rows = _period_rows(metric, payload)
        if len(current_rows) != 1:
            issues.append({"code": "AMBIGUOUS_CURRENT_DURATION_FACT", "event_id": event_id, "count": len(current_rows)})
            continue
        if not prior_rows:
            not_calculated.append({
                "event_id": event_id,
                "growth_type": "YoY",
                "reason": "NO_COMPARABLE_PRIOR_YEAR_FACT_IN_SAME_FILING",
            })
            continue
        if len(prior_rows) != 1:
            issues.append({"code": "AMBIGUOUS_PRIOR_YEAR_FACT", "event_id": event_id, "count": len(prior_rows)})
            continue

        current = current_rows[0]
        prior = prior_rows[0]
        prior_value = Decimal(str(prior["val"]))
        if prior_value == 0:
            issues.append({"code": "ZERO_PRIOR_VALUE", "event_id": event_id})
            continue
        current_value = Decimal(str(metric["value"]))
        yoy = ((current_value - prior_value) / abs(prior_value) * Decimal("100")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        growth.append({
            "event_id": event_id,
            "company_id": metric.get("company_id"),
            "ticker": metric.get("ticker"),
            "metric": "revenue",
            "growth_type": "YoY",
            "current_value": metric.get("value"),
            "prior_value": prior["val"],
            "unit": "USD",
            "current_period_start": current.get("start"),
            "current_period_end": current.get("end"),
            "prior_period_start": prior.get("start"),
            "prior_period_end": prior.get("end"),
            "yoy_percent": float(yoy),
            "accession_number": metric.get("accession_number"),
            "document_type": metric.get("document_type"),
            "taxonomy": "us-gaap",
            "concept": metric.get("concept"),
            "source_url": source_url,
            "verification": "current and prior-year revenue are duration facts in the same SEC filing accession, same form/concept/unit, with period ends 350-380 days apart and durations within 7 days",
        })

    return {
        "schema_version": "verified-revenue-growth.v1",
        "run_at": iso_now(),
        "eligible_metrics_total": len(metrics),
        "calculated_yoy_total": len(growth),
        "growth": growth,
        "not_calculated": not_calculated,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": "YoY is persisted only from comparable revenue duration facts contained in the same SEC filing accession; missing comparables produce no value, ambiguity fails closed, and QoQ remains uncomputed until an equally strict quarter-duration contract is implemented.",
    }


def main() -> int:
    metrics_doc = load_json(METRICS_PATH)
    lineage_doc = load_json(LINEAGE_PATH)
    user_agent = os.environ.get("SEC_USER_AGENT", "")
    payloads: dict[str, dict[str, Any]] = {}
    for metric in metrics_doc.get("metrics", []):
        source_url = str(metric.get("source_url") or "")
        if source_url and source_url not in payloads:
            payloads[source_url] = request_json(source_url, user_agent)

    result = derive_yoy(metrics_doc, lineage_doc, payloads)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
