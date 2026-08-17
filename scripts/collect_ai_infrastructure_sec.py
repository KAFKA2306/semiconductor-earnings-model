#!/usr/bin/env python3
"""Collect quarterly capital expenditure evidence from SEC Company Facts."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

CONCEPT = "PaymentsToAcquirePropertyPlantAndEquipment"
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
USER_AGENT = "KAFKA2306 semiconductor-earnings-model github.com/KAFKA2306"


def source_url(cik: int) -> str:
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def fetch(cik: int) -> bytes:
    request = Request(source_url(cik), headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    with urlopen(request, timeout=60) as response:
        return response.read()


def _pick_cumulative_facts(payload: dict) -> dict[tuple[int, str], dict]:
    try:
        facts = payload["facts"]["us-gaap"][CONCEPT]["units"]["USD"]
    except KeyError as exc:
        raise ValueError(f"{CONCEPT} not found") from exc
    grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for fact in facts:
        fp = fact.get("fp")
        form = fact.get("form")
        fy = fact.get("fy")
        if fp not in {"Q1", "Q2", "Q3", "FY"} or form not in {"10-Q", "10-K"}:
            continue
        if fp == "FY" and form != "10-K":
            continue
        if fp != "FY" and form != "10-Q":
            continue
        if not isinstance(fy, int) or not all(fact.get(key) for key in ("start", "end", "filed", "accn")):
            continue
        if not isinstance(fact.get("val"), (int, float)):
            continue
        grouped[(fy, fp)].append(fact)

    selected = {}
    for key, candidates in grouped.items():
        latest_end = max(item["end"] for item in candidates)
        current = [item for item in candidates if item["end"] == latest_end]
        earliest_start = min(item["start"] for item in current)
        cumulative = [item for item in current if item["start"] == earliest_start]
        selected[key] = min(cumulative, key=lambda item: (item["filed"], item["accn"]))
    return selected


def _source_fact(fact: dict) -> dict:
    return {key: fact[key] for key in ("start", "end", "val", "accn", "filed", "form", "fy", "fp")}


def quarterly_capex(payload: dict, ticker: str, entity: str, cik: int, raw_sha256: str) -> list[dict]:
    facts = _pick_cumulative_facts(payload)
    rows = []
    fiscal_years = sorted({fy for fy, _ in facts})
    for fy in fiscal_years:
        if not all((fy, fp) in facts for fp in ("Q1", "Q2", "Q3", "FY")):
            continue
        q1, q2, q3, annual = (facts[(fy, fp)] for fp in ("Q1", "Q2", "Q3", "FY"))
        starts = {fact["start"] for fact in (q1, q2, q3, annual)}
        if len(starts) != 1:
            continue
        periods = (
            ("Q1", q1["end"], q1["val"], [q1], "Q1 cumulative"),
            ("Q2", q2["end"], q2["val"] - q1["val"], [q2, q1], "Q2 cumulative - Q1 cumulative"),
            ("Q3", q3["end"], q3["val"] - q2["val"], [q3, q2], "Q3 cumulative - Q2 cumulative"),
            ("Q4", annual["end"], annual["val"] - q3["val"], [annual, q3], "FY cumulative - Q3 cumulative"),
        )
        for fp, end, value, inputs, formula in periods:
            if value < 0:
                continue
            rows.append(
                {
                    "id": f"{ticker.lower()}:{end}:capital-expenditures:actual",
                    "entity": entity,
                    "ticker": ticker,
                    "cik": f"{cik:010d}",
                    "concept_id": "capital_expenditures",
                    "sec_concept": CONCEPT,
                    "value_type": "actual",
                    "value": value,
                    "unit": "USD",
                    "period_end": end,
                    "period_type": "quarter",
                    "fiscal_year": fy,
                    "fiscal_period": fp,
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
            raise ValueError(f"{ticker}: only {len(rows)} complete quarterly CAPEX observations")
        observations.extend(rows)
    return {
        "schema_version": "ai-infrastructure-sec-capex.v1",
        "publisher": "U.S. Securities and Exchange Commission",
        "source_api": "SEC Company Facts",
        "concept": CONCEPT,
        "company_count": len({row["ticker"] for row in observations}),
        "observations": observations,
        "source_hashes": source_hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/financial_db/ai_infrastructure_sec_capex.json"))
    args = parser.parse_args()
    payload = collect()
    if payload["company_count"] < 10:
        raise SystemExit(f"expected 10 companies, got {payload['company_count']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['observations'])} observations across {payload['company_count']} companies")


if __name__ == "__main__":
    main()
