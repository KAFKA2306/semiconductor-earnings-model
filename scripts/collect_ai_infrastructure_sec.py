#!/usr/bin/env python3
"""Collect quarterly cash PP&E evidence from SEC Company Facts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

CONCEPT = "PaymentsToAcquirePropertyPlantAndEquipment"
CONCEPT_ID = "cash_paid_for_property_plant_equipment"
COMPANIES = {
    "MSFT": (789019, "Microsoft Corporation"),
    "GOOGL": (1652044, "Alphabet Inc."),
    "AMZN": (1018724, "Amazon.com, Inc."),
    "META": (1326801, "Meta Platforms, Inc."),
    "NVDA": (1045810, "NVIDIA Corporation"),
    "AVGO": (1730168, "Broadcom Inc."),
    "MU": (723125, "Micron Technology, Inc."),
    "AMD": (2488, "Advanced Micro Devices, Inc."),
    "INTC": (50863, "Intel Corporation"),
    "ORCL": (1341439, "Oracle Corporation"),
}


def source_url(cik: int) -> str:
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def fetch(cik: int) -> bytes:
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is required for SEC automated access")
    request = Request(
        source_url(cik),
        headers={"User-Agent": user_agent, "Accept-Encoding": "identity"},
    )
    with urlopen(request, timeout=60) as response:
        return response.read()


def _duration_days(fact: dict) -> int:
    return (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days


def _concept_facts(payload: dict) -> list[dict]:
    try:
        raw_facts = payload["facts"]["us-gaap"][CONCEPT]["units"]["USD"]
    except KeyError as exc:
        raise ValueError(f"{CONCEPT} not found") from exc

    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for fact in raw_facts:
        if fact.get("form") not in {"10-Q", "10-K"}:
            continue
        if not all(fact.get(key) for key in ("start", "end", "filed", "accn")):
            continue
        if not isinstance(fact.get("val"), (int, float)):
            continue
        key = (fact["start"], fact["end"], fact["form"])
        grouped.setdefault(key, []).append(fact)

    return [
        min(candidates, key=lambda item: (item["filed"], item["accn"]))
        for candidates in grouped.values()
    ]


def _source_fact(fact: dict) -> dict:
    return {
        key: fact.get(key)
        for key in ("start", "end", "val", "accn", "filed", "form", "fy", "fp")
    }


def quarterly_capex(
    payload: dict,
    ticker: str,
    entity: str,
    cik: int,
    raw_sha256: str,
) -> list[dict]:
    """Reconstruct quarterly cash paid for PP&E from cumulative SEC facts.

    The SEC concept is a cash-flow fact. It is deliberately not labeled as total
    capital expenditures because company-reported CapEx may also include finance
    leases or other non-cash additions.
    """
    facts = _concept_facts(payload)
    annuals = sorted(
        (
            fact
            for fact in facts
            if fact["form"] == "10-K" and 300 <= _duration_days(fact) <= 400
        ),
        key=lambda item: item["end"],
    )
    rows = []
    for annual in annuals:
        cumulative = sorted(
            (
                fact
                for fact in facts
                if fact["form"] == "10-Q"
                and fact["start"] == annual["start"]
                and fact["end"] < annual["end"]
                and 60 <= _duration_days(fact) <= 300
            ),
            key=lambda item: item["end"],
        )
        if len(cumulative) != 3:
            continue
        q1, q2, q3 = cumulative
        values = (
            q1["val"],
            q2["val"] - q1["val"],
            q3["val"] - q2["val"],
            annual["val"] - q3["val"],
        )
        if any(value < 0 for value in values):
            continue
        fiscal_year = annual.get("fy") or date.fromisoformat(annual["end"]).year
        periods = (
            ("Q1", q1["end"], values[0], [q1], "Q1 year-to-date"),
            ("Q2", q2["end"], values[1], [q2, q1], "Q2 year-to-date - Q1 year-to-date"),
            ("Q3", q3["end"], values[2], [q3, q2], "Q3 year-to-date - Q2 year-to-date"),
            ("Q4", annual["end"], values[3], [annual, q3], "FY - Q3 year-to-date"),
        )
        for fiscal_period, end, value, inputs, formula in periods:
            rows.append(
                {
                    "id": f"{ticker.lower()}:{end}:cash-paid-for-property-plant-equipment:actual",
                    "entity": entity,
                    "ticker": ticker,
                    "cik": f"{cik:010d}",
                    "concept_id": CONCEPT_ID,
                    "sec_concept": CONCEPT,
                    "definition": "Cash paid to acquire property, plant and equipment as reported under the SEC XBRL cash-flow concept; not total company CapEx when leases or other non-cash additions are included.",
                    "value_type": "actual",
                    "value": value,
                    "unit": "USD",
                    "period_end": end,
                    "period_type": "quarter",
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fiscal_period,
                    "as_of": max(item["filed"] for item in inputs),
                    "source_tier": "primary_regulatory",
                    "source_url": source_url(cik),
                    "source_sha256": raw_sha256,
                    "formula": formula,
                    "source_facts": [_source_fact(item) for item in inputs],
                }
            )
    rows.sort(key=lambda row: row["period_end"])
    return rows[-8:]


def collect() -> dict:
    observations = []
    source_hashes = {}
    for index, (ticker, (cik, entity)) in enumerate(COMPANIES.items()):
        if index:
            time.sleep(0.12)
        raw = fetch(cik)
        digest = hashlib.sha256(raw).hexdigest()
        source_hashes[ticker] = digest
        payload = json.loads(raw)
        rows = quarterly_capex(payload, ticker, entity, cik, digest)
        if len(rows) < 4:
            raise ValueError(
                f"{ticker}: only {len(rows)} complete quarterly cash-PP&E observations"
            )
        observations.extend(rows)
    return {
        "schema_version": "ai-infrastructure-sec-cash-ppe.v2",
        "publisher": "U.S. Securities and Exchange Commission",
        "source_api": "SEC Company Facts",
        "concept": CONCEPT,
        "concept_id": CONCEPT_ID,
        "company_count": len({row["ticker"] for row in observations}),
        "observations": observations,
        "source_hashes": source_hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/financial_db/ai_infrastructure_sec_cash_ppe.json"),
    )
    args = parser.parse_args()
    payload = collect()
    if payload["company_count"] < 10:
        raise SystemExit(f"expected 10 companies, got {payload['company_count']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {len(payload['observations'])} observations "
        f"across {payload['company_count']} companies"
    )


if __name__ == "__main__":
    main()
