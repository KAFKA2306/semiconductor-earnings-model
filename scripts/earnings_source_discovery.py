#!/usr/bin/env python3
"""Discover new filings from enabled official sources without guessing fiscal periods."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "earnings"
REGISTRY = DATA / "source_registry.json"
STATE = DATA / "collection_state.json"
CANDIDATES = DATA / "inbox" / "candidates.ndjson"
RAW = DATA / "raw"
DEFAULT_USER_AGENT = "KAFKA2306 semiconductor-earnings-model https://github.com/KAFKA2306/semiconductor-earnings-model"
RELEVANT_FORMS = {"8-K", "10-Q", "10-K", "6-K", "20-F", "40-F"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def request_bytes(url: str, retries: int = 3, timeout: int = 30) -> tuple[bytes, str]:
    user_agent = os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT).strip() or DEFAULT_USER_AGENT
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), response.geturl()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"request failed after {retries} attempts: {url}: {last_error}")


def parse_sec_acceptance(value: str | None, filing_date: str | None) -> datetime | None:
    if value:
        try:
            return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if filing_date:
        try:
            return datetime.fromisoformat(filing_date).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def is_earnings_candidate(form: str, items: str | None) -> bool:
    if form not in RELEVANT_FORMS:
        return False
    if form == "8-K" and items:
        item_set = {x.strip() for x in items.split(",")}
        return "2.02" in item_set
    return True


def sec_archive_url(cik: str, accession: str, primary_document: str) -> str:
    cik_int = str(int(cik))
    accession_compact = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_compact}/{primary_document}"


def sec_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recent = payload.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []
    columns = [
        "accessionNumber",
        "filingDate",
        "acceptanceDateTime",
        "form",
        "primaryDocument",
        "primaryDocDescription",
        "items",
    ]
    lengths = [len(recent.get(key, [])) for key in columns if isinstance(recent.get(key), list)]
    if not lengths:
        return []
    rows: list[dict[str, Any]] = []
    for index in range(max(lengths)):
        row: dict[str, Any] = {}
        for key in columns:
            values = recent.get(key, [])
            row[key] = values[index] if isinstance(values, list) and index < len(values) else None
        rows.append(row)
    return rows


def select_new_sec_rows(
    rows: list[dict[str, Any]],
    *,
    last_seen_id: str | None,
    now: datetime,
    bootstrap_hours: int = 72,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    cutoff = now - timedelta(hours=bootstrap_hours)
    for row in rows:
        accession = row.get("accessionNumber")
        if not accession:
            continue
        if last_seen_id and accession == last_seen_id:
            break
        if not is_earnings_candidate(str(row.get("form") or ""), row.get("items")):
            continue
        published = parse_sec_acceptance(row.get("acceptanceDateTime"), row.get("filingDate"))
        if not last_seen_id and (published is None or published < cutoff):
            continue
        selected.append(row)
    return selected


def persist_raw(source_id: str, accession: str, retrieved_at: datetime, body: bytes) -> Path:
    day_dir = RAW / retrieved_at.date().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    safe_accession = accession.replace("/", "-")
    path = day_dir / f"{source_id}-{safe_accession}.bin"
    path.write_bytes(body)
    return path.relative_to(ROOT)


def collect_sec(company: dict[str, Any], source: dict[str, Any], state: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    source_state = state["sources"].setdefault(source["source_id"], {})
    source_state["last_attempt_at"] = iso(now)
    raw, final_url = request_bytes(source["endpoint"])
    payload = json.loads(raw.decode("utf-8"))
    rows = sec_rows(payload)
    selected = select_new_sec_rows(rows, last_seen_id=source_state.get("last_seen_id"), now=now)
    candidates: list[dict[str, Any]] = []
    for row in reversed(selected):
        accession = row["accessionNumber"]
        primary_document = row.get("primaryDocument")
        published_at = parse_sec_acceptance(row.get("acceptanceDateTime"), row.get("filingDate"))
        if not primary_document or published_at is None:
            continue
        document_url = sec_archive_url(company["cik"], accession, primary_document)
        document, resolved_url = request_bytes(document_url)
        digest = hashlib.sha256(document).hexdigest()
        raw_path = persist_raw(source["source_id"], accession, now, document)
        candidates.append({
            "candidate_id": f"{source['source_id']}|{accession}",
            "company_id": company["company_id"],
            "company": company["legal_name"],
            "source_id": source["source_id"],
            "source_type": source["source_type"],
            "source_url": resolved_url,
            "source_index_url": final_url,
            "document_id": accession,
            "document_type": row.get("form"),
            "document_title": row.get("primaryDocDescription") or primary_document,
            "published_at": iso(published_at),
            "retrieved_at": iso(now),
            "content_sha256": digest,
            "raw_path": str(raw_path),
            "normalization_status": "PENDING",
            "normalization_reason": "fiscal_period_not_guessed_from_filing_metadata",
        })
        source_state["last_seen_id"] = accession
        source_state["last_seen_published_at"] = iso(published_at)
        source_state["last_content_sha256"] = digest
    source_state["last_success_at"] = iso(now)
    return candidates


def main() -> int:
    registry = load_json(REGISTRY)
    state = load_json(STATE)
    now = utc_now()
    candidates: list[dict[str, Any]] = []
    failures: list[str] = []
    for company in registry.get("companies", []):
        for source in company.get("sources", []):
            if not source.get("enabled"):
                continue
            try:
                if source.get("adapter") == "sec_submissions":
                    candidates.extend(collect_sec(company, source, state, now))
                else:
                    failures.append(f"{source['source_id']}: unsupported enabled adapter")
            except Exception as exc:  # fail closed per source; keep existing canonical ledger untouched
                failures.append(f"{source['source_id']}: {type(exc).__name__}: {exc}")
    state["updated_at"] = iso(now)
    append_ndjson(CANDIDATES, candidates)
    write_json(STATE, state)
    print(json.dumps({"candidates": len(candidates), "failures": failures}, ensure_ascii=False, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
