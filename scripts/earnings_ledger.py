#!/usr/bin/env python3
"""Fail-closed validator and deterministic report builder for earnings events."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "earnings"
REGISTRY = DATA / "source_registry.json"
INBOX = DATA / "inbox" / "events.ndjson"
LEDGER = DATA / "events.ndjson"
REJECTED = DATA / "rejected"
REPORTS = DATA / "reports"
TOKYO = ZoneInfo("Asia/Tokyo")

REJECTION_REASONS = {
    "OUTSIDE_TIME_WINDOW",
    "UNKNOWN_PUBLISHED_TIME",
    "STALE_FISCAL_PERIOD",
    "DUPLICATE",
    "NOT_PRIMARY_SOURCE",
    "FUTURE_EARNINGS_EVENT",
    "REPOST",
    "MISMATCHED_COMPANY",
    "UNVERIFIED_NUMBER",
}

REQUIRED = {
    "event_id",
    "company_id",
    "company",
    "fiscal_year",
    "fiscal_quarter",
    "fiscal_period",
    "period_end",
    "event_type",
    "document_type",
    "published_at",
    "retrieved_at",
    "source_id",
    "source_type",
    "source_url",
    "content_sha256",
    "actuals",
    "consensus",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_no}: expected object")
        rows.append(row)
    return rows


def append_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def iso_utc(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def registry_maps(registry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    companies: dict[str, Any] = {}
    sources: dict[str, Any] = {}
    for company in registry.get("companies", []):
        companies[company["company_id"]] = company
        for source in company.get("sources", []):
            sources[source["source_id"]] = (company, source)
    return companies, sources


def host_allowed(url: str, allowed_hosts: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    for allowed in allowed_hosts:
        allowed = allowed.lower()
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def reject(reason: str, detail: str) -> tuple[bool, str, str]:
    if reason not in REJECTION_REASONS:
        raise AssertionError(reason)
    return False, reason, detail


def validate_metric(metric: Any) -> bool:
    if not isinstance(metric, dict):
        return False
    if not isinstance(metric.get("metric_id"), str) or not metric["metric_id"]:
        return False
    if isinstance(metric.get("value"), bool) or not isinstance(metric.get("value"), (int, float)):
        return False
    return isinstance(metric.get("unit"), str) and bool(metric["unit"])


def validate_event(
    event: dict[str, Any],
    registry: dict[str, Any],
    *,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
    existing_event_ids: set[str] | None = None,
) -> tuple[bool, str | None, str | None]:
    missing = sorted(REQUIRED - event.keys())
    if missing:
        return reject("UNVERIFIED_NUMBER", f"missing required fields: {', '.join(missing)}")

    companies, sources = registry_maps(registry)
    company = companies.get(str(event.get("company_id")))
    if company is None or event.get("company") != company.get("legal_name"):
        return reject("MISMATCHED_COMPANY", "company_id/legal_name mismatch")

    source_pair = sources.get(str(event.get("source_id")))
    if source_pair is None:
        return reject("NOT_PRIMARY_SOURCE", "source_id is not registered")
    source_company, source = source_pair
    if source_company.get("company_id") != event.get("company_id"):
        return reject("MISMATCHED_COMPANY", "source belongs to a different company")
    if not source.get("enabled"):
        return reject("NOT_PRIMARY_SOURCE", "source is registered but disabled")
    if event.get("source_type") != source.get("source_type"):
        return reject("NOT_PRIMARY_SOURCE", "source_type mismatch")
    if not host_allowed(str(event.get("source_url", "")), source.get("allowed_hosts", [])):
        return reject("NOT_PRIMARY_SOURCE", "source_url host is not allow-listed")

    published_at = parse_dt(event.get("published_at"))
    retrieved_at = parse_dt(event.get("retrieved_at"))
    if published_at is None:
        return reject("UNKNOWN_PUBLISHED_TIME", "published_at is missing, invalid, or timezone-naive")
    if retrieved_at is None:
        return reject("UNVERIFIED_NUMBER", "retrieved_at is invalid or timezone-naive")
    if published_at > now:
        return reject("FUTURE_EARNINGS_EVENT", "published_at is in the future")
    if not (window_start <= published_at <= window_end):
        return reject("OUTSIDE_TIME_WINDOW", "published_at is outside the validator window")

    fy = event.get("fiscal_year")
    fq = event.get("fiscal_quarter")
    if not isinstance(fy, int) or not isinstance(fq, int) or fq not in {1, 2, 3, 4}:
        return reject("STALE_FISCAL_PERIOD", "invalid fiscal year/quarter")
    expected_period = f"FY{fy}Q{fq}"
    if event.get("fiscal_period") != expected_period:
        return reject("STALE_FISCAL_PERIOD", "fiscal_period disagrees with fiscal_year/fiscal_quarter")
    expected_id = f"{event['company_id']}|{expected_period}|{event['document_type']}"
    if event.get("event_id") != expected_id:
        return reject("STALE_FISCAL_PERIOD", "event_id disagrees with canonical fiscal key")
    try:
        period_end = date.fromisoformat(str(event.get("period_end")))
    except ValueError:
        return reject("STALE_FISCAL_PERIOD", "period_end is invalid")
    if period_end > published_at.date():
        return reject("FUTURE_EARNINGS_EVENT", "period_end is after published_at")

    digest = str(event.get("content_sha256", ""))
    if len(digest) != 64:
        return reject("UNVERIFIED_NUMBER", "content_sha256 length is invalid")
    try:
        int(digest, 16)
    except ValueError:
        return reject("UNVERIFIED_NUMBER", "content_sha256 is not hexadecimal")

    if existing_event_ids and event["event_id"] in existing_event_ids:
        return reject("DUPLICATE", "canonical event_id already exists")

    actuals = event.get("actuals")
    if not isinstance(actuals, list) or not actuals or not all(validate_metric(x) for x in actuals):
        return reject("UNVERIFIED_NUMBER", "actuals contain missing or non-numeric metrics")
    consensus = event.get("consensus")
    if consensus is not None:
        if not isinstance(consensus, list) or not all(validate_metric(x) for x in consensus):
            return reject("UNVERIFIED_NUMBER", "consensus must be null or numeric metrics")
        for metric in consensus:
            if not metric.get("provider") or parse_dt(metric.get("as_of")) is None:
                return reject("UNVERIFIED_NUMBER", "consensus requires provider and timezone-aware as_of")

    return True, None, None


def metric_key(metric: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(metric["metric_id"]),
        str(metric["unit"]),
        str(metric.get("basis", "GAAP")),
    )


def ratio_change(current: float, base: float | None) -> float | None:
    if base is None or base == 0:
        return None
    return round(current / base - 1.0, 12)


def calculate_comparisons(event: dict[str, Any], ledger: list[dict[str, Any]]) -> dict[str, Any]:
    history = [x for x in ledger if x.get("company_id") == event.get("company_id")]
    by_period = {x.get("fiscal_period"): x for x in history}
    fy = int(event["fiscal_year"])
    fq = int(event["fiscal_quarter"])
    previous_period = f"FY{fy}Q{fq - 1}" if fq > 1 else f"FY{fy - 1}Q4"
    yoy_period = f"FY{fy - 1}Q{fq}"

    def metric_map(row: dict[str, Any] | None, field: str = "actuals") -> dict[tuple[str, str, str], float]:
        if not row:
            return {}
        return {metric_key(x): float(x["value"]) for x in (row.get(field) or []) if validate_metric(x)}

    previous = metric_map(by_period.get(previous_period))
    prior_year = metric_map(by_period.get(yoy_period))
    consensus = metric_map({"actuals": event.get("consensus") or []})
    output: dict[str, Any] = {}
    for metric in event["actuals"]:
        key = metric_key(metric)
        current = float(metric["value"])
        output[metric["metric_id"]] = {
            "unit": metric["unit"],
            "basis": metric.get("basis", "GAAP"),
            "qoq": ratio_change(current, previous.get(key)),
            "yoy": ratio_change(current, prior_year.get(key)),
            "surprise": ratio_change(current, consensus.get(key)),
        }
    return output


def validate_inbox(window_start: datetime, window_end: datetime, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    registry = load_json(REGISTRY)
    ledger = read_ndjson(LEDGER)
    existing_ids = {str(row.get("event_id")) for row in ledger}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for event in read_ndjson(INBOX):
        ok, reason, detail = validate_event(
            event,
            registry,
            window_start=window_start,
            window_end=window_end,
            now=now,
            existing_event_ids=existing_ids,
        )
        if ok:
            canonical = dict(event)
            canonical["freshness"] = "PASS"
            canonical["validated_at"] = iso_utc(now)
            canonical["comparisons"] = calculate_comparisons(canonical, ledger + accepted)
            accepted.append(canonical)
            existing_ids.add(canonical["event_id"])
        else:
            rejected.append({
                "rejected_at": iso_utc(now),
                "reason": reason,
                "detail": detail,
                "company_id": event.get("company_id"),
                "event_id": event.get("event_id"),
                "published_at": event.get("published_at"),
                "source_url": event.get("source_url", "about:blank"),
            })
    append_ndjson(LEDGER, accepted)
    if rejected:
        day = now.astimezone(TOKYO).date().isoformat()
        append_ndjson(REJECTED / f"{day}.ndjson", rejected)
    if INBOX.exists():
        INBOX.unlink()
    return {"accepted": len(accepted), "rejected": len(rejected)}


def report_window(report_date: date) -> tuple[datetime, datetime]:
    end = datetime.combine(report_date, time(7, 0), tzinfo=TOKYO)
    return end - timedelta(days=1), end


def build_daily_report(report_date: date) -> Path:
    start, end = report_window(report_date)
    rows = []
    for event in read_ndjson(LEDGER):
        retrieved = parse_dt(event.get("retrieved_at"))
        if event.get("freshness") == "PASS" and retrieved and start <= retrieved < end:
            rows.append(event)
    rows.sort(key=lambda x: (x.get("published_at", ""), x.get("company_id", "")))
    lines = [
        f"# Earnings Evidence Report — {report_date.isoformat()}",
        "",
        f"- ingestion window: `{start.isoformat()}` <= retrieved_at < `{end.isoformat()}`",
        "- source: validator-PASS canonical `data/earnings/events.ndjson` only",
        "- collection at report time: **disabled by contract**",
        f"- accepted events: **{len(rows)}**",
        "",
    ]
    if not rows:
        lines += ["No validated earnings events were ingested in this window.", ""]
    for event in rows:
        lines += [
            f"## {event['company']} — {event['fiscal_period']}",
            "",
            f"- published_at: `{event['published_at']}`",
            f"- retrieved_at: `{event['retrieved_at']}`",
            f"- document_type: `{event['document_type']}`",
            f"- source: {event['source_url']}",
            f"- content_sha256: `{event['content_sha256']}`",
            "",
            "| metric | actual | unit | QoQ | YoY | consensus surprise |",
            "|---|---:|---|---:|---:|---:|",
        ]
        comparisons = event.get("comparisons", {})
        for metric in event.get("actuals", []):
            comp = comparisons.get(metric["metric_id"], {})
            def pct(value: Any) -> str:
                return "—" if value is None else f"{float(value) * 100:.2f}%"
            lines.append(
                f"| {metric['metric_id']} | {metric['value']} | {metric['unit']} | "
                f"{pct(comp.get('qoq'))} | {pct(comp.get('yoy'))} | {pct(comp.get('surprise'))} |"
            )
        lines.append("")
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{report_date.isoformat()}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--window-start", required=True)
    validate.add_argument("--window-end", required=True)
    report = sub.add_parser("report")
    report.add_argument("--date", required=True)
    args = parser.parse_args()
    if args.command == "validate":
        start = parse_dt(args.window_start)
        end = parse_dt(args.window_end)
        if not start or not end:
            raise SystemExit("window timestamps must be timezone-aware ISO-8601")
        print(json.dumps(validate_inbox(start, end), sort_keys=True))
        return 0
    path = build_daily_report(date.fromisoformat(args.date))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
