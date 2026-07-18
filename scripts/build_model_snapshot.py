#!/usr/bin/env python3
"""Create a raw-facts snapshot from one unambiguous reported quarter."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", type=Path, default=Path("site/public/api/v1/index.json"))
    parser.add_argument("--output", type=Path, default=Path("data/quant_audit/semiconductor_latest.json"))
    args = parser.parse_args()

    api = json.loads(args.api.read_text(encoding="utf-8"))
    eligible = [
        company for company in api["companies"]
        if company["class"] == "public" and company["quantitative_status"] == "reported_facts_same_period"
    ]
    period_counts: dict[tuple[str, str], int] = {}
    for company in eligible:
        periods = {
            (fact["period_start"], fact["period_end"])
            for fact in company["facts"]
            if fact["kind"] in {"operating_cash_flow", "capital_expenditures"}
        }
        for period in periods:
            if all(
                any(fact["kind"] == kind and (fact["period_start"], fact["period_end"]) == period for fact in company["facts"])
                for kind in ("operating_cash_flow", "capital_expenditures")
            ):
                period_counts[period] = period_counts.get(period, 0) + 1
    if not period_counts:
        raise SystemExit("no common reported quarter")
    largest = max(period_counts.values())
    winners = [period for period, count in period_counts.items() if count == largest]
    if len(winners) != 1:
        raise SystemExit(f"ambiguous common quarters: {sorted(winners)}")
    period = winners[0]

    sources: list[dict[str, Any]] = []
    for company in eligible:
        facts = {
            fact["kind"]: fact
            for fact in company["facts"]
            if (fact["period_start"], fact["period_end"]) == period
        }
        if set(facts) != {"operating_cash_flow", "capital_expenditures"}:
            continue
        ocf = facts["operating_cash_flow"]
        capex = facts["capital_expenditures"]
        sources.append({
            "id": company["id"],
            "label": company["name"],
            "ticker": company["ticker"],
            "period_start": period[0],
            "period_end": period[1],
            "operating_cash_flow_usd": ocf["reported_value"],
            "capital_expenditures_usd": capex["reported_value"],
            "operating_cash_flow_fact_tag": ocf["fact_tag"],
            "capital_expenditures_fact_tag": capex["fact_tag"],
            "operating_cash_flow_accession": ocf["accession"],
            "capital_expenditures_accession": capex["accession"],
            "operating_cash_flow_source_url": ocf["source_url"],
            "capital_expenditures_source_url": capex["source_url"],
            "source_api_url": capex["source_api_url"],
            "source_kind": "SEC EDGAR Companyfacts / 10-Q",
        })
    if not sources:
        raise SystemExit("no primary facts selected")

    snapshot = {
        "schema_version": "primary-facts-snapshot.v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "primary_api_generated_at": api["generated_at"],
        "primary_api_content_hash": api["content_hash"],
        "primary_period": {"start": period[0], "end": period[1]},
        "sources": sources,
        "selection_rule": "one unique largest cohort of public companies with exact quarterly primary facts; ambiguous cohorts stop the build",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"facts_snapshot_sources={len(sources)} period={period[0]}..{period[1]}")


if __name__ == "__main__":
    main()
