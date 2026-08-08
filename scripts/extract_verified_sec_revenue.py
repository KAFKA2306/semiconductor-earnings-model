from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
OUTPUT_PATH = LEDGER_DIR / "verified_revenue_latest.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def request_json(url: str, user_agent: str, retries: int = 3, timeout: int = 30) -> dict[str, Any]:
    if not user_agent.strip():
        raise RuntimeError("SEC_USER_AGENT must not be empty")
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


def extract_event_revenue(event: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    event_id = str(event.get("event_id") or "")
    accession = str(event.get("accession_number") or "")
    report_date = str(event.get("report_date") or "")
    form = str(event.get("document_type") or "")
    issues: list[dict[str, Any]] = []
    if not event_id or not accession or not report_date:
        return None, [{"code": "MISSING_EVENT_XBRL_KEY", "event_id": event_id or None}]
    if form not in {"10-K", "10-Q"}:
        return None, []

    facts = payload.get("facts", {}).get("us-gaap", {})
    candidates: list[dict[str, Any]] = []
    for tag in REVENUE_TAGS:
        concept = facts.get(tag)
        if not isinstance(concept, dict):
            continue
        for fact in concept.get("units", {}).get("USD", []):
            if (
                fact.get("accn") == accession
                and fact.get("form") == form
                and fact.get("end") == report_date
                and isinstance(fact.get("val"), (int, float))
            ):
                candidates.append({"tag": tag, **fact})

    if not candidates:
        return None, [{"code": "NO_VERIFIED_STANDARD_REVENUE_FACT", "event_id": event_id, "accession_number": accession}]

    values = {candidate["val"] for candidate in candidates}
    if len(values) != 1:
        return None, [
            {
                "code": "AMBIGUOUS_STANDARD_REVENUE_FACT",
                "event_id": event_id,
                "accession_number": accession,
                "values": sorted(values),
            }
        ]

    chosen = next(candidate for tag in REVENUE_TAGS for candidate in candidates if candidate["tag"] == tag)
    metric = {
        "event_id": event_id,
        "company_id": event.get("company_id"),
        "ticker": event.get("ticker"),
        "accession_number": accession,
        "period_end": report_date,
        "document_type": form,
        "metric": "revenue",
        "value": chosen["val"],
        "unit": "USD",
        "taxonomy": "us-gaap",
        "concept": chosen["tag"],
        "frame": chosen.get("frame"),
        "fiscal_year": chosen.get("fy"),
        "fiscal_period": chosen.get("fp"),
        "filed": chosen.get("filed"),
        "source": "SEC Company Facts API",
        "source_url": SEC_COMPANYFACTS_URL.format(cik=int(event["cik"])),
        "verification": "exact accession + exact form + exact period end + USD + standard us-gaap taxonomy",
    }
    return metric, issues


def audit(events: list[dict[str, Any]], payloads_by_cik: dict[int, dict[str, Any]]) -> dict[str, Any]:
    metrics: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    eligible = 0
    for event in events:
        if event.get("source_adapter") != "sec_edgar" or event.get("freshness") != "PASS":
            continue
        if event.get("document_type") not in {"10-K", "10-Q"}:
            continue
        eligible += 1
        try:
            cik = int(event["cik"])
        except (KeyError, TypeError, ValueError):
            issues.append({"code": "INVALID_SEC_CIK", "event_id": event.get("event_id")})
            continue
        payload = payloads_by_cik.get(cik)
        if payload is None:
            issues.append({"code": "MISSING_COMPANYFACTS_PAYLOAD", "event_id": event.get("event_id"), "cik": cik})
            continue
        metric, event_issues = extract_event_revenue(event, payload)
        if metric is not None:
            metrics.append(metric)
        issues.extend(event_issues)

    return {
        "schema_version": "verified-sec-revenue.v1",
        "run_at": iso_now(),
        "eligible_events_total": eligible,
        "verified_metrics_total": len(metrics),
        "metrics": metrics,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": "Only standard SEC us-gaap Company Facts revenue facts matching exact accession, form, period end and USD are persisted; missing or conflicting values fail closed.",
    }


def main() -> int:
    events = load_ndjson(EVENTS_PATH)
    user_agent = os.environ.get("SEC_USER_AGENT", "")
    payloads: dict[int, dict[str, Any]] = {}
    for event in events:
        if event.get("source_adapter") != "sec_edgar" or event.get("freshness") != "PASS":
            continue
        if event.get("document_type") not in {"10-K", "10-Q"}:
            continue
        try:
            cik = int(event["cik"])
        except (KeyError, TypeError, ValueError):
            continue
        if cik not in payloads:
            payloads[cik] = request_json(SEC_COMPANYFACTS_URL.format(cik=cik), user_agent)

    result = audit(events, payloads)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
