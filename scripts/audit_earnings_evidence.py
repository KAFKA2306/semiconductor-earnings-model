from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
STATE_PATH = LEDGER_DIR / "state.json"
OUTPUT_PATH = LEDGER_DIR / "evidence_latest.json"
VERIFIED_REVENUE_PATH = LEDGER_DIR / "verified_revenue_latest.json"
ALLOWED_DOMAINS = {"data.sec.gov", "www.release.tdnet.info"}
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def parse_dt(value: str) -> datetime:
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        raise ValueError(f"timezone missing: {value}")
    return dt


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def request_bytes(url: str, user_agent: str, retries: int = 1, timeout: int = 30) -> tuple[bytes, str | None]:
    if not user_agent.strip():
        raise RuntimeError("SEC_USER_AGENT is required for primary evidence verification")
    domain = urllib.parse.urlparse(url).netloc
    if domain not in ALLOWED_DOMAINS:
        raise RuntimeError(f"non-primary evidence domain: {domain}")
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "identity",
                "Accept": "application/json,application/pdf,text/html,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.headers.get("Content-Type")
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    assert last is not None
    raise last


def required_metric_event_ids(metrics_doc: dict[str, Any]) -> set[str]:
    if metrics_doc.get("status") != "PASS" or metrics_doc.get("issues"):
        return set()
    return {
        event_id
        for metric in metrics_doc.get("metrics", [])
        if isinstance(metric, dict)
        for event_id in [metric.get("event_id")]
        if isinstance(event_id, str) and event_id
    }


def select_window_events(
    events: list[dict[str, Any]],
    state: dict[str, Any],
    required_event_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    start = parse_dt(state["window_start"])
    end = parse_dt(state["window_end"])
    required = required_event_ids or set()
    selected = []
    for event in events:
        if event.get("freshness") != "PASS":
            continue
        published = parse_dt(event["published_at"])
        if start <= published <= end or event.get("event_id") in required:
            selected.append(event)
    return sorted(selected, key=lambda e: (e["published_at"], e["event_id"]))


def evidence_target(event: dict[str, Any]) -> tuple[str, str]:
    adapter = event.get("source_adapter")
    if adapter == "sec_edgar":
        cik = event.get("cik")
        if cik is None:
            raise RuntimeError(f"SEC evidence event missing CIK: {event.get('event_id')}")
        return SEC_SUBMISSIONS_URL.format(cik=int(cik)), "SEC_SUBMISSIONS_JSON"
    if adapter == "tdnet_public":
        return event["source_url"], "TDNET_DISCLOSURE_DOCUMENT"
    raise RuntimeError(f"unsupported evidence adapter: {adapter}")


def verify_event(event: dict[str, Any], user_agent: str, verified_at: datetime) -> dict[str, Any]:
    evidence_url, evidence_scope = evidence_target(event)
    raw, content_type = request_bytes(evidence_url, user_agent)
    if not raw:
        raise RuntimeError(f"empty primary evidence: {event['event_id']}")
    if evidence_scope == "SEC_SUBMISSIONS_JSON":
        payload = json.loads(raw.decode("utf-8"))
        accessions = payload.get("filings", {}).get("recent", {}).get("accessionNumber", [])
        if event.get("accession_number") not in accessions:
            raise RuntimeError(f"SEC accession missing from submissions evidence: {event['event_id']}")
    return {
        "event_id": event["event_id"],
        "company_id": event["company_id"],
        "document_type": event["document_type"],
        "published_at": event["published_at"],
        "source_url": event["source_url"],
        "evidence_url": evidence_url,
        "evidence_scope": evidence_scope,
        "source_content_sha256": hashlib.sha256(raw).hexdigest(),
        "source_content_bytes": len(raw),
        "content_type": content_type,
        "verified_at": iso(verified_at),
        "status": "PASS",
    }


def reusable_evidence(event: dict[str, Any], row: Any) -> bool:
    if not isinstance(row, dict) or row.get("status") != "PASS":
        return False
    if row.get("event_id") != event.get("event_id"):
        return False
    if row.get("company_id") != event.get("company_id"):
        return False
    if row.get("document_type") != event.get("document_type"):
        return False
    digest = row.get("source_content_sha256", "")
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        return False
    return isinstance(row.get("source_content_bytes"), int) and row["source_content_bytes"] > 0


def audit_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        event_id = row.get("event_id")
        if not event_id:
            issues.append({"code": "MISSING_EVENT_ID"})
            continue
        if event_id in seen:
            issues.append({"code": "DUPLICATE_EVIDENCE_EVENT_ID", "event_id": event_id})
        seen.add(event_id)
        digest = row.get("source_content_sha256", "")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            issues.append({"code": "INVALID_SOURCE_SHA256", "event_id": event_id})
        if not isinstance(row.get("source_content_bytes"), int) or row["source_content_bytes"] <= 0:
            issues.append({"code": "EMPTY_SOURCE_CONTENT", "event_id": event_id})
        domain = urllib.parse.urlparse(row.get("evidence_url", "")).netloc
        if domain not in ALLOWED_DOMAINS:
            issues.append({"code": "NON_PRIMARY_DOMAIN", "event_id": event_id, "domain": domain})
        if row.get("evidence_scope") not in {"SEC_SUBMISSIONS_JSON", "TDNET_DISCLOSURE_DOCUMENT"}:
            issues.append({"code": "INVALID_EVIDENCE_SCOPE", "event_id": event_id})
    return issues


def run(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    state = load_json(STATE_PATH, {})
    if state.get("audit_status") != "PASS":
        raise RuntimeError("earnings ledger must PASS before evidence verification")
    if not state.get("window_start") or not state.get("window_end"):
        raise RuntimeError("ledger window is missing")

    events = load_ndjson(EVENTS_PATH)
    metrics_doc = load_json(VERIFIED_REVENUE_PATH, {})
    required_ids = required_metric_event_ids(metrics_doc)
    window_events = select_window_events(events, state)
    window_ids = {event["event_id"] for event in window_events}
    selected = select_window_events(events, state, required_ids)

    selected_ids = {event.get("event_id") for event in selected}
    missing_required = sorted(required_ids - selected_ids)
    if missing_required:
        raise RuntimeError(
            "verified revenue metric references missing fresh accepted event: "
            + ", ".join(missing_required)
        )

    previous_doc = load_json(OUTPUT_PATH, {})
    previous_by_id = {
        row.get("event_id"): row
        for row in previous_doc.get("evidence", [])
        if isinstance(row, dict) and row.get("event_id")
    }
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    rows: list[dict[str, Any]] = []
    reused = 0
    for event in selected:
        event_id = event["event_id"]
        prior = previous_by_id.get(event_id)
        if event_id not in window_ids and reusable_evidence(event, prior):
            rows.append(prior)
            reused += 1
        else:
            rows.append(verify_event(event, user_agent, now))

    issues = audit_evidence(rows)
    payload = {
        "schema_version": "earnings-evidence-audit.v1",
        "verified_at": iso(now),
        "window_start": state["window_start"],
        "window_end": state["window_end"],
        "verified_events": len(rows),
        "required_metric_events": len(required_ids),
        "reused_evidence_events": reused,
        "evidence": rows,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "verified_events": len(rows),
                "required_metric_events": len(required_ids),
                "reused_evidence_events": reused,
                "status": payload["status"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", help="ISO8601 override for deterministic tests")
    args = parser.parse_args()
    now = parse_dt(args.now) if args.now else None
    return run(now=now)


if __name__ == "__main__":
    raise SystemExit(main())
