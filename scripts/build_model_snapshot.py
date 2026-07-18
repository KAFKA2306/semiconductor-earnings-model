#!/usr/bin/env python3
"""Create a model snapshot only from same-period primary API facts."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", type=Path, default=Path("site/public/api/v1/index.json"))
    parser.add_argument("--config", type=Path, default=Path("data/quant_audit/model_assumptions.json"))
    parser.add_argument("--output", type=Path, default=Path("data/quant_audit/semiconductor_latest.json"))
    args = parser.parse_args()

    api = json.loads(args.api.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    eligible = [
        company for company in api["companies"]
        if company["class"] == "public" and company["quantitative_status"] == "reported_facts_same_period"
    ]
    period_counts: dict[tuple[str, str], int] = {}
    for company in eligible:
        company_periods = {
            (fact["period_start"], fact["period_end"])
            for fact in company["facts"]
            if fact["kind"] in ("operating_cash_flow", "capital_expenditures")
        }
        for period in company_periods:
            if all(
                any(fact["kind"] == kind and (fact["period_start"], fact["period_end"]) == period for fact in company["facts"])
                for kind in ("operating_cash_flow", "capital_expenditures")
            ):
                period_counts[period] = period_counts.get(period, 0) + 1
    if not period_counts:
        raise SystemExit("no common reported period across eligible companies")
    period = max(period_counts, key=lambda item: (period_counts[item], item[1]))

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
            "operating_cash_flow": ocf["value_usd_billions"],
            "capital_expenditures": capex["value_usd_billions"],
            "operating_cash_flow_fact_tag": ocf["fact_tag"],
            "capital_expenditures_fact_tag": capex["fact_tag"],
            "source_url": capex["source_url"],
            "source_kind": "SEC EDGAR Companyfacts / 10-Q",
        })
    if not sources:
        raise SystemExit("no primary facts selected")
    ocf_total = sum(Decimal(str(row["operating_cash_flow"])) for row in sources)
    capex_total = sum(Decimal(str(row["capital_expenditures"])) for row in sources)
    snapshot = {
        "schema_version": "semiconductor-quant-audit.v2",
        "as_of": date.today().isoformat(),
        "graph_version": date.today().isoformat() + ".2",
        "primary_api_generated_at": api["generated_at"],
        "primary_period": {"start": period[0], "end": period[1]},
        "model_base_ratio": float(capex_total / ocf_total),
        "beta_range": config["beta_range"],
        "consensus": config["consensus"],
        "scenarios": config["scenarios"],
        "sources": sources,
        "selection_rule": "largest same-period group of reported primary facts; excluded entities remain in the API",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"model_snapshot_sources={len(sources)} period={period[0]}..{period[1]} base_ratio={float(capex_total / ocf_total):.6f}")


if __name__ == "__main__":
    main()
