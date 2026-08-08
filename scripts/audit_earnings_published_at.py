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
OUTPUT_PATH = LEDGER_DIR / "published_at_audit_latest.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


def acceptance_for_accession(payload: dict[str, Any], accession: str) -> str | None:
    recent = payload.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    accepted = recent.get("acceptanceDateTime", [])
    for index, candidate in enumerate(accessions):
        if candidate == accession:
            if index >= len(accepted):
                return None
            value = accepted[index]
            return str(value) if value else None
    return None


def verify_sec_event(event: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    event_id = event.get("event_id")
    accession = str(event.get("accession_number") or "")
    issues: list[dict[str, Any]] = []
    item: dict[str, Any] = {
        "event_id": event_id,
        "company_id": event.get("company_id"),
        "accession_number": accession or None,
        "ledger_published_at": event.get("published_at"),
        "verification_source": "SEC submissions acceptanceDateTime",
    }
    if not accession:
        issues.append({"code": "MISSING_SEC_ACCESSION", "event_id": event_id})
        item["status"] = "FAIL"
        return item, issues

    primary = acceptance_for_accession(payload, accession)
    item["primary_acceptance_at"] = primary
    if not primary:
        issues.append({"code": "ACCESSION_NOT_FOUND_IN_SEC_RECENT", "event_id": event_id, "accession_number": accession})
        item["status"] = "FAIL"
        return item, issues

    try:
        ledger_dt = parse_dt(str(event.get("published_at") or ""))
        primary_dt = parse_dt(primary)
    except (ValueError, TypeError) as exc:
        issues.append({"code": "INVALID_PUBLISHED_TIMESTAMP", "event_id": event_id, "detail": str(exc)})
        item["status"] = "FAIL"
        return item, issues

    item["ledger_published_at_utc"] = iso(ledger_dt)
    item["primary_acceptance_at_utc"] = iso(primary_dt)
    delta_seconds = abs((ledger_dt - primary_dt).total_seconds())
    item["delta_seconds"] = delta_seconds
    if delta_seconds != 0:
        issues.append(
            {
                "code": "SEC_PUBLISHED_AT_MISMATCH",
                "event_id": event_id,
                "ledger_published_at": iso(ledger_dt),
                "primary_acceptance_at": iso(primary_dt),
                "delta_seconds": delta_seconds,
            }
        )
        item["status"] = "FAIL"
    else:
        item["status"] = "PASS"
    return item, issues


def audit(events: list[dict[str, Any]], payloads_by_cik: dict[int, dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    non_sec_events = 0

    for event in events:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            issues.append({"code": "MISSING_EVENT_ID"})
            continue
        if event_id in seen:
            issues.append({"code": "DUPLICATE_EVENT_ID", "event_id": event_id})
            continue
        seen.add(event_id)
        if event.get("source_adapter") != "sec_edgar":
            non_sec_events += 1
            continue
        try:
            cik = int(event["cik"])
        except (KeyError, TypeError, ValueError):
            issues.append({"code": "INVALID_SEC_CIK", "event_id": event_id})
            continue
        payload = payloads_by_cik.get(cik)
        if payload is None:
            issues.append({"code": "MISSING_SEC_SUBMISSIONS_PAYLOAD", "event_id": event_id, "cik": cik})
            continue
        item, event_issues = verify_sec_event(event, payload)
        items.append(item)
        issues.extend(event_issues)

    return {
        "schema_version": "earnings-published-at-audit.v1",
        "run_at": iso(datetime.now(timezone.utc)),
        "events_total": len(events),
        "sec_events_total": len(items),
        "non_sec_events_not_independently_reverified": non_sec_events,
        "items": items,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": "SEC ledger published_at must exactly equal SEC submissions acceptanceDateTime; no date-only or crawl-time substitution",
    }


def main() -> int:
    events = load_ndjson(EVENTS_PATH)
    user_agent = os.environ.get("SEC_USER_AGENT", "")
    payloads: dict[int, dict[str, Any]] = {}
    for event in events:
        if event.get("source_adapter") != "sec_edgar":
            continue
        try:
            cik = int(event["cik"])
        except (KeyError, TypeError, ValueError):
            continue
        if cik not in payloads:
            payloads[cik] = request_json(SEC_SUBMISSIONS_URL.format(cik=cik), user_agent)

    result = audit(events, payloads)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
