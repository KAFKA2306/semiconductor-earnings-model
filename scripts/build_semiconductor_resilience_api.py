#!/usr/bin/env python3
"""Build a five-year semiconductor liquidity and downside-runway ledger from SEC facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SEC_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ANNUAL_DAYS = range(300, 451)
HISTORY_LIMIT = 5

DURATION_TAGS = {
    "revenue": ("registry",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditures": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ),
}
INSTANT_TAGS = {
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "short_term_investments": (
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "ShortTermInvestmentsAndMarketableSecuritiesCurrent",
    ),
    "retained_earnings": ("RetainedEarningsAccumulatedDeficit",),
    "debt_current": (
        "LongTermDebtCurrent",
        "CurrentPortionOfLongTermDebt",
        "ShortTermBorrowings",
    ),
    "debt_noncurrent": (
        "LongTermDebtNoncurrent",
        "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    ),
    "debt_total_fallback": (
        "LongTermDebtAndFinanceLeaseObligations",
        "LongTermDebt",
    ),
}
SCENARIOS = (
    {
        "id": "cycle",
        "name": "景気後退",
        "operating_cash_flow_decline": 0.30,
        "capital_expenditure_reduction": 0.15,
        "description": "営業CFを30%減、CapExを15%削減。通常の半導体循環を想定した機械的感応度。",
    },
    {
        "id": "severe",
        "name": "深い下振れ",
        "operating_cash_flow_decline": 0.60,
        "capital_expenditure_reduction": 0.35,
        "description": "営業CFを60%減、CapExを35%削減。需要急減と投資抑制が同時進行するケース。",
    },
    {
        "id": "crisis",
        "name": "危機",
        "operating_cash_flow_decline": 0.90,
        "capital_expenditure_reduction": 0.50,
        "description": "営業CFを90%減、CapExを50%削減。資金創出がほぼ停止する極端な感応度。",
    },
)


def get_json(url: str, user_agent: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def duration_days(row: dict[str, Any]) -> int | None:
    if not row.get("start") or not row.get("end"):
        return None
    return (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days


def rows_for_tag(facts: dict[str, Any], tag: str, *, annual: bool) -> list[dict[str, Any]]:
    fact = facts.get(tag)
    if not fact:
        return []
    rows: list[dict[str, Any]] = []
    for unit, values in fact.get("units", {}).items():
        if unit != "USD":
            continue
        for value in values:
            if value.get("form") != "10-K" or not value.get("end"):
                continue
            if annual:
                days = duration_days(value)
                if days not in ANNUAL_DAYS:
                    continue
                rows.append({**value, "tag": tag, "unit": unit, "duration_days": days})
            elif not value.get("start"):
                rows.append({**value, "tag": tag, "unit": unit})
    return rows


def latest_by_period(rows: Iterable[dict[str, Any]], *, instant: bool) -> dict[Any, dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        key = row["end"] if instant else (row["start"], row["end"])
        grouped.setdefault(key, []).append(row)
    return {
        key: sorted(values, key=lambda item: (item.get("filed", ""), item.get("accn", "")), reverse=True)[0]
        for key, values in grouped.items()
    }


def choose_tag_rows(
    facts: dict[str, Any],
    tags: Iterable[str],
    *,
    annual: bool,
) -> tuple[str | None, dict[Any, dict[str, Any]]]:
    for tag in tags:
        rows = rows_for_tag(facts, tag, annual=annual)
        if rows:
            return tag, latest_by_period(rows, instant=not annual)
    return None, {}


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
        "period_start": row.get("start"),
        "period_end": row["end"],
        "duration_days": row.get("duration_days"),
        "form": row["form"],
        "fiscal_year": row.get("fy"),
        "fiscal_period": row.get("fp"),
        "filed": row.get("filed"),
        "accession": row["accn"],
        "source_url": filing_url(entity["cik"], row["accn"]),
        "source_api_url": api_url,
        "source_kind": "SEC EDGAR Companyfacts / 10-K",
        "retrieved_at": retrieved_at,
    }


def synthetic_fact(entity_id: str, kind: str, period_end: str, value: int, derivation: str) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "kind": kind,
        "reported_value": value,
        "period_end": period_end,
        "source_kind": "derived_from_reported_facts",
        "derivation": derivation,
    }


def scenario_result(liquid_reserve: int, operating_cash_flow: int, capex: int, scenario: dict[str, Any]) -> dict[str, Any]:
    stressed_ocf = round(operating_cash_flow * (1 - scenario["operating_cash_flow_decline"]))
    stressed_capex = round(capex * (1 - scenario["capital_expenditure_reduction"]))
    stressed_fcf = stressed_ocf - stressed_capex
    annual_burn = max(-stressed_fcf, 0)
    runway_years = None if annual_burn == 0 else liquid_reserve / annual_burn
    if annual_burn == 0:
        band = "self_funding"
    elif runway_years >= 5:
        band = "five_years_plus"
    elif runway_years >= 2:
        band = "two_to_five_years"
    else:
        band = "under_two_years"
    return {
        "scenario_id": scenario["id"],
        "stressed_operating_cash_flow_usd": stressed_ocf,
        "stressed_capital_expenditures_usd": stressed_capex,
        "stressed_free_cash_flow_usd": stressed_fcf,
        "annual_cash_burn_usd": annual_burn,
        "liquid_reserve_runway_years": None if runway_years is None else round(runway_years, 2),
        "runway_band": band,
    }


def build_entity(entity: dict[str, Any], user_agent: str) -> dict[str, Any]:
    cik = str(entity["cik"]).zfill(10)
    api_url = SEC_COMPANYFACTS.format(cik=cik)
    facts = get_json(api_url, user_agent)["facts"]["us-gaap"]
    retrieved_at = datetime.now(timezone.utc).isoformat()

    revenue_tag, revenue_rows = choose_tag_rows(facts, (entity["revenue_tag"],), annual=True)
    ocf_tag, ocf_rows = choose_tag_rows(facts, DURATION_TAGS["operating_cash_flow"], annual=True)
    capex_tag, capex_rows = choose_tag_rows(facts, DURATION_TAGS["capital_expenditures"], annual=True)
    cash_tag, cash_rows = choose_tag_rows(facts, INSTANT_TAGS["cash"], annual=False)
    investments_tag, investments_rows = choose_tag_rows(facts, INSTANT_TAGS["short_term_investments"], annual=False)
    retained_tag, retained_rows = choose_tag_rows(facts, INSTANT_TAGS["retained_earnings"], annual=False)
    debt_current_tag, debt_current_rows = choose_tag_rows(facts, INSTANT_TAGS["debt_current"], annual=False)
    debt_noncurrent_tag, debt_noncurrent_rows = choose_tag_rows(facts, INSTANT_TAGS["debt_noncurrent"], annual=False)
    debt_fallback_tag, debt_fallback_rows = choose_tag_rows(facts, INSTANT_TAGS["debt_total_fallback"], annual=False)

    annual_periods = sorted(set(revenue_rows) & set(ocf_rows) & set(capex_rows), key=lambda value: value[1], reverse=True)
    years: list[dict[str, Any]] = []
    for period_start, period_end in annual_periods:
        cash = cash_rows.get(period_end)
        if not cash:
            continue
        investments = investments_rows.get(period_end)
        retained = retained_rows.get(period_end)
        debt_current = debt_current_rows.get(period_end)
        debt_noncurrent = debt_noncurrent_rows.get(period_end)
        debt_fallback = debt_fallback_rows.get(period_end)

        revenue = fact_record(entity, revenue_rows[(period_start, period_end)], "revenue", api_url, retrieved_at)
        ocf = fact_record(entity, ocf_rows[(period_start, period_end)], "operating_cash_flow", api_url, retrieved_at)
        capex = fact_record(entity, capex_rows[(period_start, period_end)], "capital_expenditures", api_url, retrieved_at)
        cash_fact = fact_record(entity, cash, "cash", api_url, retrieved_at)
        investment_fact = fact_record(entity, investments, "short_term_investments", api_url, retrieved_at) if investments else None
        retained_fact = fact_record(entity, retained, "retained_earnings", api_url, retrieved_at) if retained else None
        current_debt_fact = fact_record(entity, debt_current, "debt_current", api_url, retrieved_at) if debt_current else None
        noncurrent_debt_fact = fact_record(entity, debt_noncurrent, "debt_noncurrent", api_url, retrieved_at) if debt_noncurrent else None
        fallback_debt_fact = fact_record(entity, debt_fallback, "debt_total", api_url, retrieved_at) if debt_fallback else None

        cash_value = int(cash_fact["reported_value"])
        investment_value = int(investment_fact["reported_value"]) if investment_fact else 0
        liquid_reserve = cash_value + investment_value
        if current_debt_fact or noncurrent_debt_fact:
            total_debt = int(current_debt_fact["reported_value"]) if current_debt_fact else 0
            total_debt += int(noncurrent_debt_fact["reported_value"]) if noncurrent_debt_fact else 0
            debt_method = "current_plus_noncurrent"
        elif fallback_debt_fact:
            total_debt = int(fallback_debt_fact["reported_value"])
            debt_method = "single_reported_total"
        else:
            total_debt = None
            debt_method = "unavailable"
        ocf_value = int(ocf["reported_value"])
        capex_value = abs(int(capex["reported_value"]))
        free_cash_flow = ocf_value - capex_value

        years.append({
            "period_start": period_start,
            "period_end": period_end,
            "fiscal_year": revenue.get("fiscal_year"),
            "revenue": revenue,
            "operating_cash_flow": ocf,
            "capital_expenditures": capex,
            "cash": cash_fact,
            "short_term_investments": investment_fact,
            "retained_earnings": retained_fact,
            "debt_current": current_debt_fact,
            "debt_noncurrent": noncurrent_debt_fact,
            "debt_total_reported": fallback_debt_fact,
            "liquid_reserve": synthetic_fact(entity["id"], "liquid_reserve", period_end, liquid_reserve, "cash + short-term investments when separately reported"),
            "total_debt": None if total_debt is None else synthetic_fact(entity["id"], "total_debt", period_end, total_debt, debt_method),
            "net_liquidity_usd": None if total_debt is None else liquid_reserve - total_debt,
            "free_cash_flow": synthetic_fact(entity["id"], "free_cash_flow", period_end, free_cash_flow, "operating cash flow - absolute capital expenditures"),
        })
        if len(years) == HISTORY_LIMIT:
            break

    latest = years[0] if years else None
    scenarios = []
    if latest:
        reserve = int(latest["liquid_reserve"]["reported_value"])
        ocf_value = int(latest["operating_cash_flow"]["reported_value"])
        capex_value = abs(int(latest["capital_expenditures"]["reported_value"]))
        scenarios = [scenario_result(reserve, ocf_value, capex_value, scenario) for scenario in SCENARIOS]

    return {
        **entity,
        "availability": "sec_companyfacts",
        "quantitative_status": "reported_annual_resilience_facts" if years else "insufficient_annual_resilience_facts",
        "selected_tags": {
            "revenue": revenue_tag,
            "operating_cash_flow": ocf_tag,
            "capital_expenditures": capex_tag,
            "cash": cash_tag,
            "short_term_investments": investments_tag,
            "retained_earnings": retained_tag,
            "debt_current": debt_current_tag,
            "debt_noncurrent": debt_noncurrent_tag,
            "debt_total_fallback": debt_fallback_tag,
        },
        "years": years,
        "scenarios": scenarios,
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
    parser.add_argument("--output", type=Path, default=Path("site/public/api/v1/semiconductor-resilience"))
    parser.add_argument("--user-agent", default=os.getenv("SEC_USER_AGENT"))
    args = parser.parse_args()
    if not args.user_agent:
        raise SystemExit("SEC_USER_AGENT is required; do not use an unidentified or browser-shaped identity")

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    companies = [build_entity(entity, args.user_agent) for entity in registry["entities"]]
    generated_at = datetime.now(timezone.utc).isoformat()
    payload_core = {
        "schema_version": "semiconductor-resilience-api.v1",
        "generated_at": generated_at,
        "target": registry["target"],
        "source_policy": "Only annual SEC 10-K Companyfacts are used. Liquid reserve is cash plus separately reported current investments. Retained earnings is displayed but never treated as spendable cash.",
        "calculation_policy": {
            "free_cash_flow": "operating cash flow - absolute capital expenditures",
            "liquid_reserve": "cash and cash equivalents + short-term investments when separately reported",
            "runway": "liquid reserve / annual cash burn when stressed free cash flow is negative; otherwise self-funding",
            "warning": "Scenario outputs are deterministic sensitivities, not management guidance, forecasts, credit ratings, or bankruptcy probabilities.",
        },
        "scenarios": list(SCENARIOS),
        "companies": companies,
    }
    payload = {**payload_core, "content_hash": content_hash(payload_core)}
    write_json(args.output / "index.json", payload)
    for company in companies:
        write_json(args.output / "companies" / f"{company['id']}.json", company)
    print(f"semiconductor_resilience_companies={len(companies)} complete={sum(bool(company['years']) for company in companies)}")


if __name__ == "__main__":
    main()
