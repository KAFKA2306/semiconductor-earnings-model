#!/usr/bin/env python3
"""Fail-closed lineage audit for verified SEC revenue metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_ndjson(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def audit(events_path: Path, metrics_path: Path, evidence_path: Path) -> dict:
    events = {row.get("event_id"): row for row in load_ndjson(events_path)}
    metrics_doc = load_json(metrics_path)
    evidence_doc = load_json(evidence_path)
    evidence = {row.get("event_id"): row for row in evidence_doc.get("evidence", [])}
    issues: list[str] = []
    checked = 0

    if metrics_doc.get("status") != "PASS" or metrics_doc.get("issues"):
        issues.append("VERIFIED_METRICS_NOT_PASS")
    if evidence_doc.get("status") != "PASS" or evidence_doc.get("issues"):
        issues.append("EVIDENCE_NOT_PASS")

    seen: set[str] = set()
    for metric in metrics_doc.get("metrics", []):
        checked += 1
        event_id = metric.get("event_id")
        if not event_id or event_id in seen:
            issues.append(f"DUPLICATE_OR_MISSING_EVENT_ID:{event_id}")
            continue
        seen.add(event_id)
        event = events.get(event_id)
        proof = evidence.get(event_id)
        if not event:
            issues.append(f"METRIC_WITHOUT_ACCEPTED_EVENT:{event_id}")
            continue
        if event.get("freshness") != "PASS":
            issues.append(f"METRIC_EVENT_NOT_FRESH:{event_id}")
        if event.get("source_adapter") != "sec_edgar":
            issues.append(f"METRIC_EVENT_NOT_SEC:{event_id}")
        if event.get("document_type") not in {"10-K", "10-Q"}:
            issues.append(f"METRIC_EVENT_FORM_NOT_ALLOWED:{event_id}")
        for key in ("company_id", "ticker", "accession_number", "document_type"):
            if metric.get(key) != event.get(key):
                issues.append(f"METRIC_EVENT_MISMATCH:{event_id}:{key}")
        if metric.get("period_end") != event.get("report_date"):
            issues.append(f"METRIC_EVENT_MISMATCH:{event_id}:period_end")
        if metric.get("metric") != "revenue" or metric.get("unit") != "USD" or metric.get("taxonomy") != "us-gaap":
            issues.append(f"UNSAFE_METRIC_CONTRACT:{event_id}")
        source_url = metric.get("source_url", "")
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or parsed.netloc != "data.sec.gov" or not parsed.path.startswith("/api/xbrl/companyfacts/CIK"):
            issues.append(f"NON_PRIMARY_METRIC_SOURCE:{event_id}")
        if not proof or proof.get("status") != "PASS":
            issues.append(f"MISSING_PASS_EVIDENCE:{event_id}")
        elif proof.get("company_id") != event.get("company_id") or proof.get("document_type") != event.get("document_type"):
            issues.append(f"EVIDENCE_EVENT_MISMATCH:{event_id}")

    if metrics_doc.get("verified_metrics_total") != checked:
        issues.append("VERIFIED_METRIC_COUNT_MISMATCH")

    return {
        "schema_version": "verified-revenue-lineage-audit.v1",
        "checked_metrics_total": checked,
        "issues": sorted(set(issues)),
        "status": "PASS" if not issues else "FAIL",
        "contract": "Every persisted SEC revenue metric must trace to the same fresh accepted 10-K/10-Q event and PASS primary-source evidence; mismatches fail closed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default="data/earnings_ledger/events.ndjson")
    parser.add_argument("--metrics", default="data/earnings_ledger/verified_revenue_latest.json")
    parser.add_argument("--evidence", default="data/earnings_ledger/evidence_latest.json")
    parser.add_argument("--output", default="data/earnings_ledger/verified_revenue_lineage_audit_latest.json")
    args = parser.parse_args()
    result = audit(Path(args.events), Path(args.metrics), Path(args.evidence))
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
