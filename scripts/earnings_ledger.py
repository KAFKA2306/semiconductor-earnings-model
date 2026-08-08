from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
REGISTRY_PATH = LEDGER_DIR / "source_registry.json"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
REJECTED_PATH = LEDGER_DIR / "rejected.ndjson"
STATE_PATH = LEDGER_DIR / "state.json"
AUDIT_PATH = LEDGER_DIR / "audit_latest.json"
REPORTS_DIR = LEDGER_DIR / "reports"

JST = ZoneInfo("Asia/Tokyo")
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
TDNET_BASE = "https://www.release.tdnet.info/inbs/"
EARNINGS_FORMS = {"10-Q", "10-K", "20-F"}
TDNET_KEYWORDS = (
    "決算短信",
    "決算",
    "業績予想",
    "業績",
    "四半期",
    "通期",
    "売上高",
    "営業利益",
)
SIX_K_KEYWORDS = (
    "financial results",
    "quarterly results",
    "earnings release",
    "results for the",
    "results of operations",
)


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


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


def in_window(dt: datetime, window: Window) -> bool:
    return window.start <= dt <= window.end


def event_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def write_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r.get("published_at", ""), r.get("event_id", "")))
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8")


def request_bytes(url: str, user_agent: str, retries: int = 3, timeout: int = 30) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "identity",
                "Accept": "application/json,text/html,application/xhtml+xml,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    assert last is not None
    raise last


def request_json(url: str, user_agent: str) -> Any:
    return json.loads(request_bytes(url, user_agent).decode("utf-8"))


def sec_company_tickers(user_agent: str) -> dict[str, int]:
    payload = request_json(SEC_TICKERS_URL, user_agent)
    return {
        item["ticker"].upper(): int(item["cik_str"])
        for item in payload.values()
        if item.get("ticker") and item.get("cik_str") is not None
    }


def sec_filing_url(cik: int, accession: str) -> str:
    accession_flat = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_flat}/{accession}-index.html"


def sec_document_url(cik: int, accession: str, primary_document: str) -> str:
    accession_flat = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_flat}/{primary_document}"


def looks_like_earnings_6k(text: str) -> bool:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = html.unescape(cleaned).lower()
    return any(k in cleaned for k in SIX_K_KEYWORDS) and (
        "revenue" in cleaned or "net income" in cleaned or "operating income" in cleaned
    )


def collect_sec(
    source: dict[str, Any],
    window: Window,
    user_agent: str,
    ticker_map: dict[str, int],
    retrieved_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ticker = source["ticker"].upper()
    cik = int(source.get("cik") or ticker_map[ticker])
    payload = request_json(SEC_SUBMISSIONS_URL.format(cik=cik), user_agent)
    recent = payload.get("filings", {}).get("recent", {})
    if not recent:
        return [], []
    fields = {
        k: recent.get(k, [])
        for k in (
            "accessionNumber",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
            "form",
            "primaryDocument",
            "items",
        )
    }
    count = len(fields["accessionNumber"])
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for i in range(count):
        accession = fields["accessionNumber"][i]
        form = fields["form"][i]
        accepted_at_raw = fields["acceptanceDateTime"][i]
        if not accepted_at_raw:
            continue
        published = parse_dt(accepted_at_raw)
        if not in_window(published, window):
            continue
        primary_document = fields["primaryDocument"][i] if i < len(fields["primaryDocument"]) else ""
        items = fields["items"][i] if i < len(fields["items"]) else ""
        report_date = fields["reportDate"][i] if i < len(fields["reportDate"]) else ""
        reason = None
        if form == "8-K":
            if "2.02" not in (items or ""):
                reason = "NOT_EARNINGS_RELATED"
        elif form == "6-K":
            if not primary_document:
                reason = "UNVERIFIED_6K"
            else:
                doc_url = sec_document_url(cik, accession, primary_document)
                try:
                    text = request_bytes(doc_url, user_agent).decode("utf-8", errors="replace")[:500_000]
                except Exception:
                    reason = "SOURCE_FETCH_FAILED"
                else:
                    if not looks_like_earnings_6k(text):
                        reason = "NOT_EARNINGS_RELATED"
        elif form not in EARNINGS_FORMS:
            reason = "NOT_EARNINGS_RELATED"
        filing_url = sec_filing_url(cik, accession)
        eid = event_id("SEC", str(cik), accession, form)
        base = {
            "schema_version": "earnings-event.v1",
            "event_id": eid,
            "company_id": source["id"],
            "company_name": source["name"],
            "ticker": ticker,
            "source_adapter": "sec_edgar",
            "document_type": form,
            "published_at": iso(published),
            "published_timezone": "UTC",
            "retrieved_at": iso(retrieved_at),
            "source_url": filing_url,
            "accession_number": accession,
            "report_date": report_date or None,
            "title": f"{form} filing",
            "freshness": "PASS",
        }
        if reason:
            rejected.append({**base, "freshness": "REJECTED", "rejection_reason": reason})
        else:
            accepted.append(base)
    return accepted, rejected


class TDNetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.capture_key: str | None = None
        self.buf: list[str] = []
        self.title_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attrs_d = dict(attrs)
        if tag == "tr":
            self.current = {}
        if tag == "td" and self.current is not None:
            cls = attrs_d.get("class") or ""
            mapping = {"kjTime": "time", "kjCode": "code", "kjName": "company", "kjTitle": "title"}
            if cls in mapping:
                self.capture_key = mapping[cls]
                self.buf = []
        if tag == "a" and self.capture_key == "title":
            href = attrs_d.get("href")
            if href:
                self.title_href = href

    def handle_data(self, data: str):
        if self.capture_key:
            self.buf.append(data)

    def handle_endtag(self, tag: str):
        if tag == "td" and self.capture_key and self.current is not None:
            self.current[self.capture_key] = " ".join("".join(self.buf).split())
            if self.capture_key == "title" and self.title_href:
                self.current["href"] = self.title_href
            self.capture_key = None
            self.buf = []
            self.title_href = None
        if tag == "tr" and self.current is not None:
            if {"time", "code", "company", "title"} <= self.current.keys():
                self.rows.append(self.current)
            self.current = None


def parse_tdnet(html_text: str) -> list[dict[str, str]]:
    parser = TDNetParser()
    parser.feed(html_text)
    return parser.rows


def collect_tdnet(
    source: dict[str, Any],
    window: Window,
    user_agent: str,
    retrieved_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    codes = {str(c)[:4] for c in source["codes"]}
    target_companies = source["companies"]
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    start_date = window.start.astimezone(JST).date()
    end_date = window.end.astimezone(JST).date()
    dates = []
    d = start_date
    while d <= end_date:
        dates.append(d)
        d += timedelta(days=1)
    for date_ in dates:
        found_any_page = False
        for page in range(1, 30):
            url = f"{TDNET_BASE}I_list_{page:03d}_{date_.strftime('%Y%m%d')}.html"
            try:
                raw = request_bytes(url, user_agent, retries=2)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    break
                raise
            text = raw.decode("utf-8", errors="replace")
            rows = parse_tdnet(text)
            if not rows:
                if "開示された情報はありません" in text:
                    found_any_page = True
                    break
                if page == 1:
                    raise RuntimeError(f"TDnet parse failure or unexpected empty page: {url}")
                break
            found_any_page = True
            for row in rows:
                code = row["code"].strip()[:4]
                if code not in codes:
                    continue
                try:
                    local_dt = datetime.strptime(
                        f"{date_.isoformat()} {row['time']}", "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=JST)
                except ValueError:
                    continue
                published = local_dt.astimezone(timezone.utc)
                if not in_window(published, window):
                    continue
                company_meta = target_companies.get(code, {})
                title = row["title"]
                url_abs = urllib.parse.urljoin(TDNET_BASE, row.get("href", ""))
                eid = event_id("TDNET", code, date_.isoformat(), row["time"], title, url_abs)
                base = {
                    "schema_version": "earnings-event.v1",
                    "event_id": eid,
                    "company_id": company_meta.get("id", code),
                    "company_name": row["company"] or company_meta.get("name", code),
                    "ticker": company_meta.get("ticker"),
                    "source_adapter": "tdnet_public",
                    "document_type": "TDNET_DISCLOSURE",
                    "published_at": iso(published),
                    "published_timezone": "Asia/Tokyo",
                    "retrieved_at": iso(retrieved_at),
                    "source_url": url_abs,
                    "title": title,
                    "security_code": code,
                    "freshness": "PASS",
                }
                if any(k in title for k in TDNET_KEYWORDS):
                    accepted.append(base)
                else:
                    rejected.append(
                        {**base, "freshness": "REJECTED", "rejection_reason": "NOT_EARNINGS_RELATED"}
                    )
            if len(rows) < 100:
                break
        if not found_any_page:
            raise RuntimeError(f"TDnet unavailable for {date_}")
    return accepted, rejected


def audit_ledger(
    registry: dict[str, Any],
    events: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    run_at: datetime,
    source_status: list[dict[str, Any]],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    ids: set[str] = set()
    allowed_domains = {"www.sec.gov", "www.release.tdnet.info"}
    for row in events:
        missing = [
            k
            for k in ("event_id", "company_id", "published_at", "source_url", "document_type")
            if not row.get(k)
        ]
        if missing:
            issues.append(
                {"code": "MISSING_REQUIRED_FIELD", "event_id": row.get("event_id"), "fields": missing}
            )
            continue
        if row["event_id"] in ids:
            issues.append({"code": "DUPLICATE_EVENT_ID", "event_id": row["event_id"]})
        ids.add(row["event_id"])
        try:
            published = parse_dt(row["published_at"])
        except Exception:
            issues.append({"code": "INVALID_PUBLISHED_AT", "event_id": row["event_id"]})
            continue
        if published > run_at + timedelta(minutes=5):
            issues.append({"code": "FUTURE_PUBLISHED_AT", "event_id": row["event_id"]})
        domain = urllib.parse.urlparse(row["source_url"]).netloc
        if domain not in allowed_domains:
            issues.append(
                {"code": "NON_PRIMARY_DOMAIN", "event_id": row["event_id"], "domain": domain}
            )
    unsupported = [s["id"] for s in registry["sources"] if not s.get("enabled", True)]
    failures = [s for s in source_status if s["status"] == "error"]
    return {
        "schema_version": "earnings-ledger-audit.v1",
        "run_at": iso(run_at),
        "accepted_events_total": len(events),
        "rejected_events_total": len(rejected),
        "source_status": source_status,
        "unsupported_or_disabled_sources": unsupported,
        "issues": issues,
        "status": "PASS" if not issues and not failures else "FAIL",
    }


def render_report(events: list[dict[str, Any]], window: Window, audit: dict[str, Any]) -> str:
    selected = [e for e in events if in_window(parse_dt(e["published_at"]), window)]
    selected.sort(key=lambda e: e["published_at"], reverse=True)
    lines = [
        f"# 決算イベント収集台帳 {window.end.astimezone(JST).date().isoformat()}",
        "",
        f"- 対象窓: {window.start.astimezone(JST).isoformat()} ～ {window.end.astimezone(JST).isoformat()}",
        f"- 鮮度PASS: {len(selected)}件",
        f"- 台帳監査: {audit['status']}",
        "",
    ]
    for e in selected:
        lines += [
            f"## {e['company_name']} | {e['document_type']}",
            "",
            f"- 公表日時: {e['published_at']}",
            f"- 表題: {e['title']}",
            f"- 一次情報: {e['source_url']}",
            "",
        ]
    if not selected:
        lines += ["対象24時間内に鮮度ゲートを通過した決算イベントはありません。", ""]
    return "\n".join(lines)


def run(now: datetime | None = None, audit_only: bool = False) -> int:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    window = Window(start=now - timedelta(hours=24), end=now)
    registry = load_json(REGISTRY_PATH, {})
    events = load_ndjson(EVENTS_PATH)
    rejected = load_ndjson(REJECTED_PATH)
    source_status: list[dict[str, Any]] = []
    if not audit_only:
        user_agent = os.environ.get(
            "SEC_USER_AGENT",
            "KAFKA2306 semiconductor-earnings-model https://github.com/KAFKA2306/semiconductor-earnings-model",
        )
        ticker_map: dict[str, int] | None = None
        new_events: list[dict[str, Any]] = []
        new_rejected: list[dict[str, Any]] = []
        for source in registry.get("sources", []):
            if not source.get("enabled", True):
                source_status.append(
                    {
                        "source_id": source["id"],
                        "status": "disabled",
                        "reason": source.get("disabled_reason"),
                    }
                )
                continue
            try:
                if source["adapter"] == "sec_edgar":
                    if ticker_map is None:
                        ticker_map = sec_company_tickers(user_agent)
                    a, r = collect_sec(source, window, user_agent, ticker_map, now)
                elif source["adapter"] == "tdnet_public":
                    a, r = collect_tdnet(source, window, user_agent, now)
                else:
                    raise RuntimeError(f"unsupported adapter {source['adapter']}")
                new_events.extend(a)
                new_rejected.extend(r)
                source_status.append(
                    {
                        "source_id": source["id"],
                        "status": "success",
                        "accepted": len(a),
                        "rejected": len(r),
                    }
                )
            except Exception as exc:
                source_status.append(
                    {
                        "source_id": source["id"],
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        event_map = {e["event_id"]: e for e in events}
        for e in new_events:
            event_map[e["event_id"]] = e
        rejected_map = {e["event_id"]: e for e in rejected}
        for e in new_rejected:
            if e["event_id"] not in event_map:
                rejected_map[e["event_id"]] = e
        events = list(event_map.values())
        rejected = list(rejected_map.values())
        write_ndjson(EVENTS_PATH, events)
        write_ndjson(REJECTED_PATH, rejected)
    else:
        previous_audit = load_json(AUDIT_PATH, {})
        source_status = previous_audit.get("source_status", [])
    audit = audit_ledger(registry, events, rejected, now, source_status)
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = {
        "schema_version": "earnings-ledger-state.v1",
        "last_run_at": iso(now),
        "window_start": iso(window.start),
        "window_end": iso(window.end),
        "audit_status": audit["status"],
        "accepted_total": len(events),
        "rejected_total": len(rejected),
    }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{now.astimezone(JST).date().isoformat()}.md"
    report_path.write_text(render_report(events, window, audit), encoding="utf-8")
    if audit["status"] != "PASS":
        print(json.dumps(audit, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "window_start": iso(window.start),
                "window_end": iso(window.end),
                "new_window_events": sum(
                    1 for e in events if in_window(parse_dt(e["published_at"]), window)
                ),
                "audit": audit["status"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--now", help="ISO8601 override for deterministic tests/manual audit")
    args = parser.parse_args()
    now = parse_dt(args.now) if args.now else None
    return run(now=now, audit_only=args.audit_only)


if __name__ == "__main__":
    raise SystemExit(main())
