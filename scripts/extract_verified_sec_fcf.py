from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
OUTPUT_PATH = LEDGER_DIR / "verified_fcf_latest.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
OCF_CONCEPT = "NetCashProvidedByUsedInOperatingActivities"
CAPEX_CONCEPT = "PaymentsToAcquirePropertyPlantAndEquipment"
ELIGIBLE_FORMS = {"10-K", "10-Q"}
FRESHNESS_HOURS = 24


def parse_dt(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        raise ValueError(f"timezone missing: {value}")
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


def is_live_event(event: dict[str, Any], now: datetime) -> tuple[bool, dict[str, Any] | None]:
    event_id = event.get("event_id")
    try:
        published = parse_dt(str(event["published_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        return False, {"code": "INVALID_PUBLISHED_AT", "event_id": event_id, "detail": str(exc)}
    if published > now:
        return False, {"code": "FUTURE_PUBLISHED_AT", "event_id": event_id}
    if now - published > timedelta(hours=FRESHNESS_HOURS):
        return False, None
    return True, None


def select_duration_fact(
    payload: dict[str, Any],
    concept_name: str,
    accession: str,
    form: str,
    report_date: str,
    event_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    concept = payload.get("facts", {}).get("us-gaap", {}).get(concept_name)
    if not isinstance(concept, dict):
        return None, {
            "code": "NO_STANDARD_FCF_INPUT_CONCEPT",
            "event_id": event_id,
            "accession_number": accession,
            "concept": concept_name,
        }

    candidates = [
        fact
        for fact in concept.get("units", {}).get("USD", [])
        if fact.get("accn") == accession
        and fact.get("form") == form
        and fact.get("end") == report_date
        and isinstance(fact.get("val"), (int, float))
        and not isinstance(fact.get("val"), bool)
        and isinstance(fact.get("start"), str)
    ]
    if not candidates:
        return None, {
            "code": "NO_VERIFIED_FCF_INPUT_FACT",
            "event_id": event_id,
            "accession_number": accession,
            "concept": concept_name,
        }

    signatures = {(fact["start"], fact["end"], fact["val"]) for fact in candidates}
    if len(signatures) != 1:
        return None, {
            "code": "AMBIGUOUS_FCF_INPUT_FACT",
            "event_id": event_id,
            "accession_number": accession,
            "concept": concept_name,
            "facts": [
                {"start": start, "end": end, "value": value}
                for start, end, value in sorted(signatures)
            ],
        }
    return candidates[0], None


def extract_event_fcf(event: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    event_id = str(event.get("event_id") or "")
    accession = str(event.get("accession_number") or "")
    report_date = str(event.get("report_date") or "")
    form = str(event.get("document_type") or "")
    if not event_id or not accession or not report_date:
        return None, [{"code": "MISSING_EVENT_XBRL_KEY", "event_id": event_id or None}]
    if form not in ELIGIBLE_FORMS:
        return None, []

    ocf, ocf_issue = select_duration_fact(payload, OCF_CONCEPT, accession, form, report_date, event_id)
    capex, capex_issue = select_duration_fact(payload, CAPEX_CONCEPT, accession, form, report_date, event_id)
    issues = [issue for issue in (ocf_issue, capex_issue) if issue is not None]
    if issues:
        return None, issues
    assert ocf is not None and capex is not None

    if ocf["start"] != capex["start"] or ocf["end"] != capex["end"]:
        return None, [{
            "code": "FCF_INPUT_PERIOD_MISMATCH",
            "event_id": event_id,
            "accession_number": accession,
            "operating_cash_flow_period": {"start": ocf["start"], "end": ocf["end"]},
            "capex_period": {"start": capex["start"], "end": capex["end"]},
        }]

    try:
        start = datetime.fromisoformat(ocf["start"]).date()
        end = datetime.fromisoformat(ocf["end"]).date()
    except ValueError:
        return None, [{"code": "INVALID_FCF_PERIOD", "event_id": event_id, "accession_number": accession}]
    if start > end:
        return None, [{"code": "INVALID_FCF_PERIOD", "event_id": event_id, "accession_number": accession}]

    ocf_value = ocf["val"]
    capex_value = capex["val"]
    fcf_value = ocf_value - capex_value
    cik = int(event["cik"])
    return {
        "event_id": event_id,
        "company_id": event.get("company_id"),
        "ticker": event.get("ticker"),
        "accession_number": accession,
        "period_start": ocf["start"],
        "period_end": ocf["end"],
        "duration_days": (end - start).days + 1,
        "document_type": form,
        "metric": "free_cash_flow",
        "value": fcf_value,
        "unit": "USD",
        "accounting_basis": "derived-non-gaap",
        "derivation": "NetCashProvidedByUsedInOperatingActivities - PaymentsToAcquirePropertyPlantAndEquipment",
        "inputs": {
            "operating_cash_flow": {
                "taxonomy": "us-gaap",
                "concept": OCF_CONCEPT,
                "value": ocf_value,
            },
            "capital_expenditures": {
                "taxonomy": "us-gaap",
                "concept": CAPEX_CONCEPT,
                "value": capex_value,
            },
        },
        "filed": ocf.get("filed"),
        "source": "SEC Company Facts API",
        "source_url": SEC_COMPANYFACTS_URL.format(cik=cik),
        "verification": "derived only from two live <=24h SEC Company Facts USD inputs sharing exact accession, form, period start and period end; FCF is explicitly non-GAAP derived",
    }, []


def audit(events: list[dict[str, Any]], payloads_by_cik: dict[int, dict[str, Any]], now: datetime) -> dict[str, Any]:
    now = now.astimezone(timezone.utc)
    metrics: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    eligible = 0
    stale = 0
    for event in events:
        if event.get("source_adapter") != "sec_edgar" or event.get("freshness") != "PASS":
            continue
        if event.get("document_type") not in ELIGIBLE_FORMS:
            continue
        live, freshness_issue = is_live_event(event, now)
        if freshness_issue is not None:
            issues.append(freshness_issue)
            continue
        if not live:
            stale += 1
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
        metric, event_issues = extract_event_fcf(event, payload)
        if metric is not None:
            metrics.append(metric)
        issues.extend(event_issues)

    return {
        "schema_version": "verified-sec-fcf.v1",
        "run_at": iso(now),
        "freshness_gate_hours": FRESHNESS_HOURS,
        "eligible_events_total": eligible,
        "stale_events_skipped_total": stale,
        "verified_metrics_total": len(metrics),
        "metrics": metrics,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": "FCF is a derived non-GAAP metric. Persist it only when live <=24h SEC 10-K/10-Q Company Facts provides one unambiguous USD us-gaap operating-cash-flow fact and one unambiguous USD us-gaap PP&E acquisition fact for the exact same accession, form, period start and period end. Missing, stale, future, malformed, mismatched or conflicting inputs never become metrics.",
    }


def main() -> int:
    now = datetime.now(timezone.utc)
    events = load_ndjson(EVENTS_PATH)
    user_agent = os.environ.get("SEC_USER_AGENT", "")
    payloads: dict[int, dict[str, Any]] = {}
    for event in events:
        if event.get("source_adapter") != "sec_edgar" or event.get("freshness") != "PASS":
            continue
        if event.get("document_type") not in ELIGIBLE_FORMS:
            continue
        live, issue = is_live_event(event, now)
        if issue is not None or not live:
            continue
        try:
            cik = int(event["cik"])
        except (KeyError, TypeError, ValueError):
            continue
        if cik not in payloads:
            payloads[cik] = request_json(SEC_COMPANYFACTS_URL.format(cik=cik), user_agent)

    result = audit(events, payloads, now)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
