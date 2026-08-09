from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
AUDIT_PATH = LEDGER_DIR / "audit_latest.json"
REPORTS_DIR = LEDGER_DIR / "reports"
JST = ZoneInfo("Asia/Tokyo")
PRIMARY_DOMAINS = {"www.sec.gov", "www.release.tdnet.info"}


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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def report_window(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(JST)
    cutoff_end = datetime.combine(local_now.date(), time(7, 0), tzinfo=JST)
    if local_now < cutoff_end:
        cutoff_end -= timedelta(days=1)
    return cutoff_end - timedelta(hours=24), cutoff_end


def validate_audit(audit: dict[str, Any]) -> None:
    if audit.get("status") != "PASS":
        raise RuntimeError("ledger audit is not PASS")
    if audit.get("issues") != []:
        raise RuntimeError("ledger audit contains issues")
    if not audit.get("run_at"):
        raise RuntimeError("ledger audit run_at is required")
    parse_dt(str(audit["run_at"]))


def select_events(
    events: list[dict[str, Any]], start: datetime, end: datetime
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for event in events:
        required = (
            "event_id",
            "company_id",
            "company_name",
            "document_type",
            "published_at",
            "source_url",
        )
        missing = [key for key in required if not event.get(key)]
        if missing:
            raise RuntimeError(f"accepted event missing required fields: {missing}")
        if event.get("freshness") != "PASS":
            raise RuntimeError(f"accepted event is not freshness PASS: {event['event_id']}")
        published = parse_dt(str(event["published_at"]))
        domain = urllib.parse.urlparse(str(event["source_url"])).netloc
        if domain not in PRIMARY_DOMAINS:
            raise RuntimeError(
                f"accepted event is not on a primary-source domain: {event['event_id']}"
            )
        if start <= published < end:
            selected.append(event)
    selected.sort(
        key=lambda event: (event["published_at"], event["event_id"]), reverse=True
    )
    return selected


def render_report(
    events: list[dict[str, Any]], audit: dict[str, Any], start: datetime, end: datetime
) -> str:
    selected = select_events(events, start, end)
    lines = [
        f"# 決算イベント日次レポート {end.astimezone(JST).date().isoformat()}",
        "",
        f"- 対象窓: {start.astimezone(JST).isoformat()} ～ {end.astimezone(JST).isoformat()}（終端は含まない）",
        f"- validator PASSイベント: {len(selected)}件",
        f"- 台帳監査run: {audit['run_at']}",
        "- 収集: このレポート処理では実行しない",
        "",
    ]
    for event in selected:
        lines.extend(
            [
                f"## {event['company_name']} | {event['document_type']}",
                "",
                f"- 公表日時: {event['published_at']}",
                f"- 表題: {event.get('title') or event['document_type']}",
                f"- 一次情報: {event['source_url']}",
                "",
            ]
        )
    if not selected:
        lines.extend(["対象窓にvalidator PASS済みの決算イベントはありません。", ""])
    return "\n".join(lines)


def run(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    start, end = report_window(now)
    audit = load_json(AUDIT_PATH)
    validate_audit(audit)
    events = load_ndjson(EVENTS_PATH)
    report = render_report(events, audit, start, end)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORTS_DIR / f"{end.astimezone(JST).date().isoformat()}.md"
    output.write_text(report, encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(output.relative_to(ROOT)),
                "window_start": iso(start),
                "window_end": iso(end),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", help="ISO8601 override for deterministic tests/manual runs")
    args = parser.parse_args()
    now = parse_dt(args.now) if args.now else None
    try:
        return run(now)
    except Exception as exc:
        print(f"daily earnings report failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
