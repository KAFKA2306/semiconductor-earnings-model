#!/usr/bin/env python3
"""Build a static, primary-source financial facts API from SEC Companyfacts."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

SEC_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
OCF_TAGS = ("NetCashProvidedByUsedInOperatingActivities",)
CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquirePropertyAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquireOtherPropertyPlantAndEquipment",
)


def get_json(url: str, user_agent: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def duration_days(row: dict[str, Any]) -> int | None:
    if not row.get("start") or not row.get("end"):
        return None
    return (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days


def candidates(facts: dict[str, Any], tags: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tag in tags:
        fact = facts.get("us-gaap", {}).get(tag, {})
        for unit, values in fact.get("units", {}).items():
            if unit != "USD":
                continue
            for row in values:
                if row.get("form") != "10-Q" or not row.get("start"):
                    continue
                days = duration_days(row)
                if days is None or days < 70:
                    continue
                rows.append({**row, "tag": tag, "unit": unit, "duration_days": days})
    return rows


def choose(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    latest_end = max(row.get("end", "") for row in rows)
    latest = [row for row in rows if row.get("end") == latest_end]
    return min(latest, key=lambda row: (row.get("duration_days", 0), row.get("filed", ""), row.get("accn", "")))


def filing_url(cik: str, accession: str) -> str:
    compact = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}/{accession}-index.html"


def recent_filings(cik: str, user_agent: str) -> list[dict[str, Any]]:
    url = SEC_SUBMISSIONS.format(cik=str(cik).zfill(10))
    recent = get_json(url, user_agent).get("filings", {}).get("recent", {})
    rows = []
    for index, form in enumerate(recent.get("form", [])):
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
    return rows[:12]


def fact_record(entity: dict[str, Any], row: dict[str, Any] | None, kind: str, api_url: str) -> dict[str, Any] | None:
    if row is None:
        return None
    accession = row["accn"]
    return {
        "entity_id": entity["id"],
        "kind": kind,
        "fact_tag": row["tag"],
        "unit": row["unit"],
        "reported_value": row["val"],
        "value_usd_billions": round(row["val"] / 1_000_000_000, 6),
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
    ocf = fact_record(entity, choose(candidates(facts, OCF_TAGS)), "operating_cash_flow", api_url)
    capex = fact_record(entity, choose(candidates(facts, CAPEX_TAGS)), "capital_expenditures", api_url)
    records = [record for record in (ocf, capex) if record is not None]
    same_period = bool(ocf and capex and ocf["period_start"] == capex["period_start"] and ocf["period_end"] == capex["period_end"])
    if not ocf and not capex:
        status = "public_no_10q_facts_yet"
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("data/primary/entities.json"))
    parser.add_argument("--output", type=Path, default=Path("site/public/api/v1"))
    parser.add_argument("--user-agent", default=os.getenv("SEC_USER_AGENT", "KAFKA2306-semiconductor-earnings-model"))
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    companies = [build_entity(entity, args.user_agent) for entity in registry["entities"]]
    generated_at = date.today().isoformat()
    payload = {
        "schema_version": "primary-finance-api.v1",
        "generated_at": generated_at,
        "source_policy": registry["source_policy"],
        "companies": companies,
    }
    facts = [fact for company in companies for fact in company["facts"]]
    write_json(args.output / "index.json", payload)
    write_json(args.output / "facts.json", {"schema_version": payload["schema_version"], "generated_at": generated_at, "facts": facts})
    for company in companies:
        write_json(args.output / "companies" / f"{company['id']}.json", company)
    print(f"primary_api_companies={len(companies)} primary_facts={len(facts)} output={args.output}")


if __name__ == "__main__":
    main()
