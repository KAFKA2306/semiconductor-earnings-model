from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

EVENT_ID_RE = re.compile(r'data-event-id=["\']([^"\']+)["\']')
BODY_COUNT_RE = {
    "fresh": re.compile(r'data-fresh-event-count=["\'](\d+)["\']'),
    "expired": re.compile(r'data-expired-event-count=["\'](\d+)["\']'),
    "visible": re.compile(r'data-visible-metric-count=["\'](\d+)["\']'),
    "hidden": re.compile(r'data-hidden-by-freshness-count=["\'](\d+)["\']'),
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_rendered_ledger(html: str, publication: dict, revenue: dict) -> list[str]:
    issues: list[str] = []

    if publication.get("schema_version") != "earnings-ledger-publication.v1":
        issues.append("INVALID_PUBLICATION_SCHEMA")
    if publication.get("audit_status") != "PASS":
        issues.append("PUBLICATION_NOT_PASS")

    contract = publication.get("contract") or {}
    required_contract = {
        "primary_sources_only": True,
        "freshness_gate_hours": 24,
        "publication_rechecks_freshness": True,
        "fail_closed": True,
        "unverified_values_published": False,
    }
    for key, expected in required_contract.items():
        if contract.get(key) != expected:
            issues.append(f"INVALID_CONTRACT_{key.upper()}")

    events = publication.get("events")
    if not isinstance(events, list):
        issues.append("PUBLICATION_EVENTS_NOT_LIST")
        events = []

    published_ids = {event.get("event_id") for event in events if event.get("event_id")}
    if len(published_ids) != len(events):
        issues.append("MISSING_OR_DUPLICATE_PUBLICATION_EVENT_ID")

    accepted = publication.get("accepted_events_total")
    expired = publication.get("expired_events_total")
    ledger_accepted = publication.get("ledger_accepted_events_total")
    if accepted != len(events):
        issues.append("PUBLICATION_ACCEPTED_COUNT_MISMATCH")
    if not all(isinstance(value, int) and value >= 0 for value in (accepted, expired, ledger_accepted)):
        issues.append("INVALID_FRESHNESS_COUNTS")
    elif ledger_accepted != accepted + expired:
        issues.append("FRESHNESS_ACCOUNTING_MISMATCH")

    rendered_ids = EVENT_ID_RE.findall(html)
    if len(rendered_ids) != len(set(rendered_ids)):
        issues.append("DUPLICATE_RENDERED_EVENT_ID")
    stale_rendered = sorted(set(rendered_ids) - published_ids)
    if stale_rendered:
        issues.append("STALE_EVENT_RENDERED:" + ",".join(stale_rendered))

    raw_metrics = revenue.get("metrics") or []
    raw_ids = [metric.get("event_id") for metric in raw_metrics if metric.get("event_id")]
    expected_visible = sum(1 for event_id in raw_ids if event_id in published_ids)
    expected_hidden = len(raw_metrics) - expected_visible

    expected_counts = {
        "fresh": accepted,
        "expired": expired,
        "visible": expected_visible,
        "hidden": expected_hidden,
    }
    for key, expected in expected_counts.items():
        match = BODY_COUNT_RE[key].search(html)
        if match is None:
            issues.append(f"MISSING_RENDERED_{key.upper()}_COUNT")
        elif int(match.group(1)) != expected:
            issues.append(f"RENDERED_{key.upper()}_COUNT_MISMATCH")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default="site/dist/ledger/index.html")
    parser.add_argument("--publication", default="data/earnings_ledger/publication_latest.json")
    parser.add_argument("--revenue", default="data/earnings_ledger/verified_revenue_latest.json")
    args = parser.parse_args()

    html = Path(args.html).read_text(encoding="utf-8")
    publication = _read_json(Path(args.publication))
    revenue = _read_json(Path(args.revenue))
    issues = audit_rendered_ledger(html, publication, revenue)
    if issues:
        raise SystemExit("ledger page publication boundary audit failed: " + "; ".join(issues))
    print("ledger page publication boundary: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
