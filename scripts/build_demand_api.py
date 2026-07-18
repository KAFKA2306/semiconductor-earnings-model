#!/usr/bin/env python3
"""Build a five-year quarterly demand-side API from SEC cash-flow facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from build_semiconductor_profit_api import SEC_COMPANYFACTS, SEC_SUBMISSIONS, filing_url, get_json

HISTORY_LIMIT = 20
QUARTER_DAYS = range(70, 111)
Q2_YTD_DAYS = range(150, 221)
Q3_YTD_DAYS = range(240, 301)
ANNUAL_DAYS = range(300, 381)


def duration_days(row: dict[str, Any]) -> int | None:
    if not row.get("start") or not row.get("end"):
        return None
    return (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days


def candidates(facts: dict[str, Any], tag: str | None) -> list[dict[str, Any]]:
    if not tag or tag not in facts:
        return []
    rows = []
    for unit, values in facts[tag]["units"].items():
        if unit != "USD":
            continue
        for row in values:
            if row.get("form") not in {"10-Q", "10-K"} or not row.get("start") or row.get("fy") is None:
                continue
            days = duration_days(row)
            if days is None:
                continue
            rows.append({**row, "tag": tag, "unit": unit, "duration_days": days})
    return rows


def latest(rows: list[dict[str, Any]], fy: int, fp: str, durations: range) -> dict[str, Any] | None:
    selected = [row for row in rows if row.get("fy") == fy and row.get("fp") == fp and row["duration_days"] in durations]
    if not selected:
        return None
    selected.sort(key=lambda row: (row["end"], row.get("filed", ""), row.get("accn", "")), reverse=True)
    return selected[0]


def raw_record(entity: dict[str, Any], row: dict[str, Any], api_url: str, retrieved_at: str) -> dict[str, Any]:
    accession = row["accn"]
    return {
        "entity_id": entity["id"],
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
        "accession": accession,
        "source_url": filing_url(entity["cik"], accession),
        "source_api_url": api_url,
        "source_kind": "SEC EDGAR Companyfacts / 10-Q or 10-K",
        "retrieved_at": retrieved_at,
    }


def quarter_value(
    entity: dict[str, Any],
    row: dict[str, Any] | None,
    components: list[dict[str, Any]],
    api_url: str,
    retrieved_at: str,
    value: int | None = None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    source_facts = [raw_record(entity, component, api_url, retrieved_at) for component in components]
    return {
        "value_usd": row["val"] if value is None else value,
        "value_type": "reported_quarter" if len(components) == 1 else "derived_from_reported_periods",
        "period_start": row["start"],
        "period_end": row["end"],
        "fiscal_year": row.get("fy"),
        "fiscal_period": row.get("fp"),
        "fact_tag": row["tag"],
        "source_url": source_facts[-1]["source_url"],
        "source_api_url": api_url,
        "source_facts": source_facts,
        "retrieved_at": retrieved_at,
    }


def direct_or_difference(
    entity: dict[str, Any],
    direct: dict[str, Any] | None,
    later: dict[str, Any] | None,
    earlier: dict[str, Any] | None,
    api_url: str,
    retrieved_at: str,
) -> dict[str, Any] | None:
    if direct is not None:
        return quarter_value(entity, direct, [direct], api_url, retrieved_at)
    if later is None or earlier is None:
        return None
    derived = {**later, "val": later["val"] - earlier["val"], "start": (date.fromisoformat(earlier["end"]) + timedelta(days=1)).isoformat(), "fp": later["fp"]}
    return quarter_value(entity, derived, [later, earlier], api_url, retrieved_at, value=derived["val"])


def build_metric(entity: dict[str, Any], rows: list[dict[str, Any]], api_url: str, retrieved_at: str) -> dict[tuple[str, str], dict[str, Any]]:
    years = sorted({int(row["fy"]) for row in rows}, reverse=True)
    quarters: dict[tuple[str, str], dict[str, Any]] = {}
    for fy in years:
        q1 = latest(rows, fy, "Q1", QUARTER_DAYS)
        q2_direct = latest(rows, fy, "Q2", QUARTER_DAYS)
        q2_ytd = latest(rows, fy, "Q2", Q2_YTD_DAYS)
        q3_direct = latest(rows, fy, "Q3", QUARTER_DAYS)
        q3_ytd = latest(rows, fy, "Q3", Q3_YTD_DAYS)
        q4_direct = latest(rows, fy, "FY", QUARTER_DAYS)
        annual = latest(rows, fy, "FY", ANNUAL_DAYS)
        q1_value = quarter_value(entity, q1, [q1], api_url, retrieved_at)
        q2_value = direct_or_difference(entity, q2_direct, q2_ytd, q1, api_url, retrieved_at)
        q3_value = direct_or_difference(entity, q3_direct, q3_ytd, q2_ytd, api_url, retrieved_at)
        q4_value = direct_or_difference(entity, q4_direct, annual, q3_ytd, api_url, retrieved_at)
        for period, value in (("Q1", q1_value), ("Q2", q2_value), ("Q3", q3_value), ("Q4", q4_value)):
            if value is not None:
                if period == "Q4" and value["value_type"] == "derived_from_reported_periods":
                    value["fiscal_period"] = "Q4"
                    value["period_start"] = (date.fromisoformat(q3_ytd["end"]) + timedelta(days=1)).isoformat() if q3_ytd else value["period_start"]
                    value["period_end"] = annual["end"] if annual else value["period_end"]
                quarters[(value["period_start"], value["period_end"])] = value
    return quarters


def build_entity(entity: dict[str, Any], user_agent: str) -> dict[str, Any]:
    if entity["class"] != "public" or not entity.get("cik"):
        return {**entity, "availability": "no_public_sec_10q_10k", "quarters": [], "quantitative_status": "excluded_without_estimate"}
    cik = str(entity["cik"]).zfill(10)
    api_url = SEC_COMPANYFACTS.format(cik=cik)
    companyfacts = get_json(api_url, user_agent)
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    if not facts:
        return {**entity, "availability": "sec_companyfacts_without_us_gaap", "quarters": [], "quantitative_status": "public_no_quarterly_demand_facts"}
    retrieved_at = datetime.now(timezone.utc).isoformat()
    tags = entity.get("fact_tags", {})
    ocf_rows = candidates(facts, tags.get("operating_cash_flow"))
    capex_rows = candidates(facts, tags.get("capital_expenditures"))
    ocf = build_metric(entity, ocf_rows, api_url, retrieved_at)
    capex = build_metric(entity, capex_rows, api_url, retrieved_at)
    periods = sorted(set(ocf) & set(capex), key=lambda period: period[1], reverse=True)[:HISTORY_LIMIT]
    quarters = [
        {
            "period_start": period[0],
            "period_end": period[1],
            "fiscal_year": ocf[period]["fiscal_year"],
            "fiscal_period": ocf[period]["fiscal_period"],
            "operating_cash_flow": ocf[period],
            "capital_expenditures": capex[period],
        }
        for period in periods
    ]
    scale = max(
        (abs(value)
         for quarter in quarters
         for value in (
             quarter["operating_cash_flow"]["value_usd"],
             quarter["capital_expenditures"]["value_usd"],
         )),
        default=0,
    )
    for quarter in quarters:
        ocf_value = quarter["operating_cash_flow"]["value_usd"]
        capex_value = quarter["capital_expenditures"]["value_usd"]
        quarter["operating_cash_flow"]["normalized_value"] = round(ocf_value / scale * 100, 1) if scale else 0
        quarter["capital_expenditures"]["normalized_value"] = round(capex_value / scale * 100, 1) if scale else 0
        quarter["capital_expenditure_to_operating_cash_flow"] = round(capex_value / ocf_value, 4) if ocf_value else None
    status = "reported_or_derived_quarterly_facts" if quarters else "public_no_quarterly_demand_facts"
    return {
        **entity,
        "availability": "sec_companyfacts",
        "normalization": {
            "method": "within_company_shared_absolute_max",
            "scale_usd": scale,
            "display_range": "-100 to +100",
        },
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
    parser.add_argument("--registry", type=Path, default=Path("data/primary/entities.json"))
    parser.add_argument("--output", type=Path, default=Path("site/public/api/v1/demand"))
    parser.add_argument("--user-agent", default=os.getenv("SEC_USER_AGENT"))
    args = parser.parse_args()
    if not args.user_agent:
        raise SystemExit("SEC_USER_AGENT is required; do not use an unidentified or browser-shaped identity")
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    companies = [build_entity(entity, args.user_agent) for entity in registry["entities"]]
    payload_core = {
        "schema_version": "demand-side-api.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_policy": registry["source_policy"],
        "selection_rule": "up to 20 exact quarterly periods; direct quarterly facts preferred, otherwise same-tag reported YTD/annual differences",
        "companies": companies,
    }
    payload = {**payload_core, "content_hash": content_hash(payload_core)}
    write_json(args.output / "index.json", payload)
    for company in companies:
        write_json(args.output / "companies" / f"{company['id']}.json", company)
    print(f"demand_api_companies={len(companies)} histories={sum(bool(company['quarters']) for company in companies)}")


if __name__ == "__main__":
    main()
