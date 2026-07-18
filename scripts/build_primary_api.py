#!/usr/bin/env python3
"""Build a static, primary-source financial facts API from SEC Companyfacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SEC_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
QUARTER_DAYS = range(70, 111)


def get_json(url: str, user_agent: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def duration_days(row: dict[str, Any]) -> int | None:
    if not row.get("start") or not row.get("end"):
        return None
    return (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days


def candidates(facts: dict[str, Any], tag: str | None) -> list[dict[str, Any]]:
    if not tag:
        return []
    rows: list[dict[str, Any]] = []
    if tag not in facts["us-gaap"]:
        return []
    fact = facts["us-gaap"][tag]
    for unit, values in fact["units"].items():
        if unit != "USD":
            continue
        for row in values:
            if row.get("form") != "10-Q" or not row.get("start"):
                continue
            days = duration_days(row)
            if days not in QUARTER_DAYS:
                continue
            rows.append({**row, "tag": tag, "unit": unit, "duration_days": days})
    return rows


def choose(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    latest_end = max(row["end"] for row in rows)
    latest = [row for row in rows if row["end"] == latest_end]
    periods = {(row["start"], row["end"]) for row in latest}
    if len(periods) != 1 or len(latest) != 1:
        raise ValueError(f"ambiguous quarterly fact candidates: {sorted(periods)}")
    return latest[0]


def filing_url(cik: str, accession: str) -> str:
    compact = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}/{accession}-index.html"


def recent_filings(cik: str, user_agent: str) -> list[dict[str, Any]]:
    url = SEC_SUBMISSIONS.format(cik=str(cik).zfill(10))
    recent = get_json(url, user_agent)["filings"]["recent"]
    rows = []
    for index, form in enumerate(recent["form"]):
        if form not in {"10-Q", "10-K", "S-1", "S-1/A", "8-K"}:
            continue
        accession = recent["accessionNumber"][index]
        primary = recent["primaryDocument"][index]
        compact = accession.replace("-", "")
        rows.append({
            "form": form,
        "filed": recent["filingDate"][index],
        "report_date": recent["reportDate"][index],
            "accession": accession,
            "source_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}/{primary}",
            "index_url": filing_url(str(cik), accession),
        })
    return sorted(rows, key=lambda row: (row["filed"], row["accession"]), reverse=True)[:12]


def fact_record(entity: dict[str, Any], row: dict[str, Any] | None, kind: str, api_url: str, retrieved_at: str) -> dict[str, Any] | None:
    if row is None:
        return None
    accession = row["accn"]
    return {
        "entity_id": entity["id"],
        "kind": kind,
        "fact_tag": row["tag"],
        "unit": row["unit"],
        "reported_value": row["val"],
        "period_start": row["start"],
        "period_end": row["end"],
        "duration_days": row["duration_days"],
        "form": row["form"],
        "fiscal_period": row.get("fp"),
        "filed": row.get("filed"),
        "accession": accession,
        "source_url": filing_url(entity["cik"], accession),
        "source_api_url": api_url,
        "source_kind": "SEC EDGAR Companyfacts / 10-Q",
        "retrieved_at": retrieved_at,
    }


def build_entity(entity: dict[str, Any], user_agent: str) -> dict[str, Any]:
    if entity["class"] != "public":
        return {
            **entity,
            "availability": "no_public_sec_10q_10k",
            "facts": [],
            "quantitative_status": "excluded_without_estimate",
        }
    cik = str(entity["cik"]).zfill(10)
    api_url = SEC_COMPANYFACTS.format(cik=cik)
    facts = get_json(api_url, user_agent)["facts"]
    filings = recent_filings(cik, user_agent)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    fact_tags = entity["fact_tags"]
    ocf = fact_record(entity, choose(candidates(facts, fact_tags.get("operating_cash_flow"))), "operating_cash_flow", api_url, retrieved_at)
    capex = fact_record(entity, choose(candidates(facts, fact_tags.get("capital_expenditures"))), "capital_expenditures", api_url, retrieved_at)
    records = [record for record in (ocf, capex) if record is not None]
    same_period = bool(ocf and capex and ocf["period_start"] == capex["period_start"] and ocf["period_end"] == capex["period_end"])
    has_10q = any(filing["form"] == "10-Q" for filing in filings)
    if not ocf and not capex:
        status = "public_no_quarterly_10q_facts" if has_10q else "public_no_10q_facts_yet"
    elif not capex:
        status = "capital_expenditure_fact_unavailable"
    elif same_period:
        status = "reported_facts_same_period"
    else:
        status = "reported_facts_period_mismatch"
    return {
        **entity,
        "availability": "sec_companyfacts",
        "recent_filings": filings,
        "facts": records,
        "quantitative_status": status,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("data/primary/entities.json"))
    parser.add_argument("--output", type=Path, default=Path("site/public/api/v1"))
    parser.add_argument("--user-agent", default=os.getenv("SEC_USER_AGENT"))
    args = parser.parse_args()
    if not args.user_agent:
        raise SystemExit("SEC_USER_AGENT is required; do not use an unidentified or browser-shaped identity")
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    companies = [build_entity(entity, args.user_agent) for entity in registry["entities"]]
    generated_at = datetime.now(timezone.utc).isoformat()
    payload_core = {
        "schema_version": "primary-finance-api.v1",
        "generated_at": generated_at,
        "source_policy": registry["source_policy"],
        "companies": companies,
    }
    payload = {**payload_core, "content_hash": content_hash(payload_core)}
    facts = [fact for company in companies for fact in company["facts"]]
    write_json(args.output / "index.json", payload)
    write_json(args.output / "facts.json", {"schema_version": payload["schema_version"], "generated_at": generated_at, "facts": facts})
    for company in companies:
        write_json(args.output / "companies" / f"{company['id']}.json", company)
    print(f"primary_api_companies={len(companies)} primary_facts={len(facts)} output={args.output}")


if __name__ == "__main__":
    main()
