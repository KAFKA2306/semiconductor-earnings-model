#!/usr/bin/env python3
"""Build direct quarterly semiconductor revenue and operating-income facts."""

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
HISTORY_LIMIT = 20


def get_json(url: str, user_agent: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def duration_days(row: dict[str, Any]) -> int | None:
    if not row.get("start") or not row.get("end"):
        return None
    return (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days


def candidates(facts: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    if tag not in facts:
        return []
    rows: list[dict[str, Any]] = []
    for unit, values in facts[tag]["units"].items():
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


def history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        period = (row["start"], row["end"])
        grouped.setdefault(period, []).append(row)
    by_period = {
        period: sorted(rows, key=lambda row: (row.get("filed", ""), row.get("accn", "")), reverse=True)[0]
        for period, rows in grouped.items()
    }
    return [by_period[period] for period in sorted(by_period, key=lambda value: value[1], reverse=True)[:HISTORY_LIMIT]]


def filing_url(cik: str, accession: str) -> str:
    compact = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}/{accession}-index.html"


def fact_record(entity: dict[str, Any], row: dict[str, Any], kind: str, api_url: str, retrieved_at: str) -> dict[str, Any]:
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
        "fiscal_year": row.get("fy"),
        "fiscal_period": row.get("fp"),
        "filed": row.get("filed"),
        "accession": row["accn"],
        "source_url": filing_url(entity["cik"], row["accn"]),
        "source_api_url": api_url,
        "source_kind": "SEC EDGAR Companyfacts / 10-Q",
        "retrieved_at": retrieved_at,
    }


def build_entity(entity: dict[str, Any], user_agent: str) -> dict[str, Any]:
    cik = str(entity["cik"]).zfill(10)
    api_url = SEC_COMPANYFACTS.format(cik=cik)
    facts = get_json(api_url, user_agent)["facts"]["us-gaap"]
    retrieved_at = datetime.now(timezone.utc).isoformat()
    revenue_rows = history(candidates(facts, entity["revenue_tag"]))
    income_rows = history(candidates(facts, entity["operating_income_tag"]))
    revenue_by_period = {(row["start"], row["end"]): row for row in revenue_rows}
    income_by_period = {(row["start"], row["end"]): row for row in income_rows}
    periods = sorted(set(revenue_by_period) & set(income_by_period), key=lambda value: value[1], reverse=True)
    quarters = []
    for period in periods:
        quarters.append({
            "period_start": period[0],
            "period_end": period[1],
            "fiscal_year": revenue_by_period[period].get("fy"),
            "fiscal_period": revenue_by_period[period].get("fp"),
            "revenue": fact_record(entity, revenue_by_period[period], "revenue", api_url, retrieved_at),
            "operating_income": fact_record(entity, income_by_period[period], "operating_income", api_url, retrieved_at),
        })
    has_10q = any(form == "10-Q" for form in get_json(SEC_SUBMISSIONS.format(cik=cik), user_agent)["filings"]["recent"]["form"])
    if not quarters:
        status = "public_no_quarterly_profit_facts" if has_10q else "public_no_10q_facts_yet"
    else:
        status = "reported_profit_facts_same_period"
    facts_flat = [fact for quarter in quarters for fact in (quarter["revenue"], quarter["operating_income"])]
    return {
        **entity,
        "availability": "sec_companyfacts",
        "facts": facts_flat,
        "quarters": quarters,
        "quantitative_status": status,
    }


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("data/primary/semiconductor_entities.json"))
    parser.add_argument("--output", type=Path, default=Path("site/public/api/v1/semiconductor-profit"))
    parser.add_argument("--user-agent", default=os.getenv("SEC_USER_AGENT"))
    args = parser.parse_args()
    if not args.user_agent:
        raise SystemExit("SEC_USER_AGENT is required; do not use an unidentified or browser-shaped identity")
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    companies = [build_entity(entity, args.user_agent) for entity in registry["entities"]]
    period_counts: dict[tuple[str, str], int] = {}
    for company in companies:
        for quarter in company["quarters"]:
            period = (quarter["period_start"], quarter["period_end"])
            period_counts[period] = period_counts.get(period, 0) + 1
    largest = max(period_counts.values(), default=0)
    winners = sorted(period for period, count in period_counts.items() if count == largest)
    cohort_period = winners[0] if len(winners) == 1 else None
    cohort_ids = [company["id"] for company in companies if cohort_period and any((quarter["period_start"], quarter["period_end"]) == cohort_period for quarter in company["quarters"])]
    cohort = {
        "status": "unique" if cohort_period else ("ambiguous" if winners else "no_common_period"),
        "period_start": cohort_period[0] if cohort_period else None,
        "period_end": cohort_period[1] if cohort_period else None,
        "company_ids": cohort_ids,
        "candidate_periods": [{"period_start": period[0], "period_end": period[1]} for period in winners],
    }
    generated_at = datetime.now(timezone.utc).isoformat()
    payload_core = {
        "schema_version": "semiconductor-profit-api.v1",
        "generated_at": generated_at,
        "target": registry["target"],
        "source_policy": registry["source_policy"],
        "selection_rule": "largest unique common reported quarter among registered direct SEC issuer facts; no index weights or estimates",
        "cohort": cohort,
        "companies": companies,
    }
    payload = {**payload_core, "content_hash": content_hash(payload_core)}
    write_json(args.output / "index.json", payload)
    write_json(args.output / "facts.json", {"schema_version": payload["schema_version"], "generated_at": generated_at, "facts": [fact for company in companies for fact in company["facts"]]})
    for company in companies:
        write_json(args.output / "companies" / f"{company['id']}.json", company)
    print(f"semiconductor_profit_companies={len(companies)} cohort={len(cohort_ids)} cohort_status={cohort['status']}")


if __name__ == "__main__":
    main()
