#!/usr/bin/env python3
"""Derive fail-closed QoQ revenue growth from verified SEC Company Facts revenue."""

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
OUTPUT_PATH = LEDGER_DIR / "verified_revenue_qoq_latest.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def request_json(url: str, user_agent: str, retries: int = 3, timeout: int = 30) -> dict[str, Any]:
    if not user_agent.strip():
        raise RuntimeError("SEC_USER_AGENT must not be empty")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "data.sec.gov"
        or not parsed.path.startswith("/api/xbrl/companyfacts/CIK")
    ):
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


def _duration(row: dict[str, Any]) -> int | None:
    start = parse_date(row.get("start"))
    end = parse_date(row.get("end"))
    if start is None or end is None or end <= start:
        return None
    return (end - start).days


def _quarter_rows(metric: dict[str, Any], payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    concept = metric.get("concept")
    rows = payload.get("facts", {}).get("us-gaap", {}).get(concept, {}).get("units", {}).get("USD", [])
    if not isinstance(rows, list):
        return [], []

    accession = metric.get("accession_number")
    form = metric.get("document_type")
    end = metric.get("period_end")
    value = metric.get("value")
    current = [
        row
        for row in rows
        if row.get("accn") == accession
        and row.get("form") == form
        and row.get("end") == end
        and row.get("val") == value
        and _duration(row) is not None
    ]
    current_unique = {(row.get("start"), row.get("end"), row.get("val")): row for row in current}
    current_rows = list(current_unique.values())
    if len(current_rows) != 1:
        return current_rows, []

    current_row = current_rows[0]
    current_start = parse_date(current_row.get("start"))
    current_end = parse_date(current_row.get("end"))
    current_duration = _duration(current_row)
    assert current_start is not None and current_end is not None and current_duration is not None
    if not 70 <= current_duration <= 110:
        return current_rows, []

    prior: list[dict[str, Any]] = []
    for row in rows:
        prior_end = parse_date(row.get("end"))
        prior_duration = _duration(row)
        if prior_end is None or prior_duration is None or not isinstance(row.get("val"), (int, float)):
            continue
        if row.get("form") not in {"10-Q", "10-K"}:
            continue
        end_gap = (current_end - prior_end).days
        duration_gap = abs(current_duration - prior_duration)
        if 70 <= end_gap <= 110 and duration_gap <= 7:
            prior.append(row)

    prior_unique = {(row.get("start"), row.get("end"), row.get("val")): row for row in prior}
    return current_rows, list(prior_unique.values())


def derive_qoq(
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
            or metric.get("document_type") not in {"10-Q", "10-K"}
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

        current_rows, prior_rows = _quarter_rows(metric, payload)
        if len(current_rows) != 1:
            issues.append({"code": "AMBIGUOUS_CURRENT_DURATION_FACT", "event_id": event_id, "count": len(current_rows)})
            continue

        current = current_rows[0]
        current_duration = _duration(current)
        if current_duration is None or not 70 <= current_duration <= 110:
            not_calculated.append(
                {
                    "event_id": event_id,
                    "growth_type": "QoQ",
                    "reason": "CURRENT_FACT_NOT_STANDALONE_QUARTER",
                }
            )
            continue
        if not prior_rows:
            not_calculated.append(
                {
                    "event_id": event_id,
                    "growth_type": "QoQ",
                    "reason": "NO_COMPARABLE_PRIOR_QUARTER_FACT",
                }
            )
            continue
        if len(prior_rows) != 1:
            issues.append({"code": "AMBIGUOUS_PRIOR_QUARTER_FACT", "event_id": event_id, "count": len(prior_rows)})
            continue

        prior = prior_rows[0]
        prior_value = Decimal(str(prior["val"]))
        if prior_value == 0:
            issues.append({"code": "ZERO_PRIOR_VALUE", "event_id": event_id})
            continue
        current_value = Decimal(str(metric["value"]))
        qoq = ((current_value - prior_value) / abs(prior_value) * Decimal("100")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        growth.append(
            {
                "event_id": event_id,
                "company_id": metric.get("company_id"),
                "ticker": metric.get("ticker"),
                "metric": "revenue",
                "growth_type": "QoQ",
                "current_value": metric.get("value"),
                "prior_value": prior["val"],
                "unit": "USD",
                "current_period_start": current.get("start"),
                "current_period_end": current.get("end"),
                "prior_period_start": prior.get("start"),
                "prior_period_end": prior.get("end"),
                "qoq_percent": float(qoq),
                "accession_number": metric.get("accession_number"),
                "document_type": metric.get("document_type"),
                "taxonomy": "us-gaap",
                "concept": metric.get("concept"),
                "source_url": source_url,
                "verification": "current and prior revenue are standalone quarter-duration facts from SEC Company Facts using the same us-gaap concept and USD unit; period ends are 70-110 days apart and durations differ by at most 7 days",
            }
        )

    return {
        "schema_version": "verified-revenue-qoq.v1",
        "run_at": iso_now(),
        "eligible_metrics_total": len(metrics),
        "calculated_qoq_total": len(growth),
        "growth": growth,
        "not_calculated": not_calculated,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": "QoQ is persisted only for comparable standalone quarter-duration us-gaap revenue facts from the primary SEC Company Facts payload; missing comparables produce no value and ambiguity fails closed.",
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

    result = derive_qoq(metrics_doc, lineage_doc, payloads)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
