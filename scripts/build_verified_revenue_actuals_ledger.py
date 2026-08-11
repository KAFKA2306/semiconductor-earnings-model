#!/usr/bin/env python3
"""Persist comparable SEC revenue duration facts before any growth calculation."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
METRICS_PATH = LEDGER_DIR / "verified_revenue_latest.json"
LINEAGE_PATH = LEDGER_DIR / "verified_revenue_lineage_audit_latest.json"
OUTPUT_PATH = LEDGER_DIR / "verified_revenue_actuals.ndjson"
MANIFEST_PATH = LEDGER_DIR / "verified_revenue_actuals_manifest.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def request_json(url: str, user_agent: str, retries: int = 3, timeout: int = 30) -> dict[str, Any]:
    if not user_agent.strip():
        raise RuntimeError("SEC_USER_AGENT must not be empty")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "data.sec.gov" or not parsed.path.startswith("/api/xbrl/companyfacts/CIK"):
        raise RuntimeError(f"non-primary SEC Company Facts URL rejected: {url}")
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    assert last is not None
    raise last


def build_actuals(metrics_doc: dict[str, Any], lineage_doc: dict[str, Any], payloads_by_url: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    actuals: dict[tuple[Any, ...], dict[str, Any]] = {}
    metrics = metrics_doc.get("metrics", [])
    if metrics_doc.get("status") != "PASS" or metrics_doc.get("issues") or metrics_doc.get("verified_metrics_total") != len(metrics):
        return [], [{"code": "VERIFIED_REVENUE_NOT_PASS"}]
    if lineage_doc.get("status") != "PASS" or lineage_doc.get("issues") or lineage_doc.get("checked_metrics_total") != len(metrics):
        return [], [{"code": "VERIFIED_REVENUE_LINEAGE_NOT_PASS"}]

    for metric in metrics:
        source_url = str(metric.get("source_url") or "")
        parsed = urlparse(source_url)
        if metric.get("metric") != "revenue" or metric.get("unit") != "USD" or metric.get("taxonomy") != "us-gaap" or parsed.scheme != "https" or parsed.netloc != "data.sec.gov" or not parsed.path.startswith("/api/xbrl/companyfacts/CIK"):
            issues.append({"code": "UNSAFE_CURRENT_METRIC", "event_id": metric.get("event_id")})
            continue
        payload = payloads_by_url.get(source_url)
        if payload is None:
            issues.append({"code": "MISSING_COMPANYFACTS_PAYLOAD", "event_id": metric.get("event_id")})
            continue
        concept = metric.get("concept")
        rows = payload.get("facts", {}).get("us-gaap", {}).get(concept, {}).get("units", {}).get("USD", [])
        if not isinstance(rows, list):
            issues.append({"code": "MISSING_REVENUE_FACTS", "event_id": metric.get("event_id")})
            continue
        for row in rows:
            start = parse_date(row.get("start")); end = parse_date(row.get("end"))
            if start is None or end is None or end <= start or not isinstance(row.get("val"), (int, float)):
                continue
            if row.get("form") not in {"10-Q", "10-K"} or not row.get("accn"):
                continue
            actual = {
                "schema_version": "verified-revenue-actual.v1",
                "company_id": metric.get("company_id"), "ticker": metric.get("ticker"),
                "metric": "revenue", "value": row["val"], "unit": "USD", "taxonomy": "us-gaap", "concept": concept,
                "period_start": row.get("start"), "period_end": row.get("end"), "duration_days": (end - start).days,
                "accession_number": row.get("accn"), "document_type": row.get("form"), "fiscal_year": row.get("fy"), "fiscal_period": row.get("fp"), "filed": row.get("filed"), "frame": row.get("frame"),
                "source": "SEC Company Facts API", "source_url": source_url,
            }
            key = (actual["company_id"], concept, actual["period_start"], actual["period_end"], actual["value"], actual["accession_number"], actual["document_type"])
            actuals[key] = actual
    return sorted(actuals.values(), key=lambda r: (str(r["company_id"]), str(r["concept"]), str(r["period_end"]), str(r["period_start"]), str(r["accession_number"]))), issues


def main() -> int:
    metrics_doc = load_json(METRICS_PATH); lineage_doc = load_json(LINEAGE_PATH)
    user_agent = os.environ.get("SEC_USER_AGENT", "")
    payloads: dict[str, dict[str, Any]] = {}
    for metric in metrics_doc.get("metrics", []):
        url = str(metric.get("source_url") or "")
        if url and url not in payloads:
            payloads[url] = request_json(url, user_agent)
    actuals, issues = build_actuals(metrics_doc, lineage_doc, payloads)
    OUTPUT_PATH.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in actuals), encoding="utf-8")
    manifest = {"schema_version": "verified-revenue-actuals-manifest.v1", "run_at": iso_now(), "actuals_total": len(actuals), "issues": issues, "status": "PASS" if not issues else "FAIL", "contract": "Growth calculations consume this persisted multi-period actual ledger; SEC Company Facts is fetched only by the ledger builder."}
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
