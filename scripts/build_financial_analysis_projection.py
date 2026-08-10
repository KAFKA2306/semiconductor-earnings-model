from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "edinetdb_projections" / "KAFKA2306__semiconductor-earnings-model" / "semiconductor-kioxia-financials.json"
DEFAULT_OUTPUT = ROOT / "data" / "financial_analysis" / "kioxia-annual-analysis.json"

METRICS = {
    "revenue_yoy": "(revenue_t / revenue_t-1) - 1; only when adjacent records share accounting_standard and basis",
    "operating_margin": "operating_income / revenue",
    "net_margin": "net_income / revenue",
    "free_cash_flow": "cf_operating + cf_investing",
}


def ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def build(source: dict[str, Any], source_path: str) -> dict[str, Any]:
    rows = sorted(source.get("records", []), key=lambda row: row.get("fiscal_year", 0))
    out: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for row in rows:
        comparable = bool(previous and previous.get("accounting_standard") == row.get("accounting_standard") and previous.get("basis") == row.get("basis"))
        revenue_yoy = None
        revenue_yoy_reason = None
        if comparable:
            prior_revenue = previous.get("revenue") if previous else None
            growth_base = ratio(row.get("revenue"), prior_revenue)
            revenue_yoy = None if growth_base is None else growth_base - 1
            if revenue_yoy is None:
                revenue_yoy_reason = "missing_or_zero_prior_revenue"
        else:
            revenue_yoy_reason = "no_comparable_prior_period"
        cfo = row.get("cf_operating")
        cfi = row.get("cf_investing")
        out.append({
            "fiscal_year": row.get("fiscal_year"), "accounting_standard": row.get("accounting_standard"), "basis": row.get("basis"),
            "revenue": row.get("revenue"), "operating_income": row.get("operating_income"), "net_income": row.get("net_income"), "eps": row.get("eps"),
            "cf_operating": cfo, "cf_investing": cfi,
            "revenue_yoy": revenue_yoy, "revenue_yoy_null_reason": revenue_yoy_reason,
            "operating_margin": ratio(row.get("operating_income"), row.get("revenue")),
            "net_margin": ratio(row.get("net_income"), row.get("revenue")),
            "free_cash_flow": cfo + cfi if cfo is not None and cfi is not None else None,
        })
        previous = row
    return {
        "schema_version": "financial-analysis.v1", "entity": "Kioxia Holdings Corporation", "frequency": "annual", "currency": "JPY", "ratio_unit": "decimal",
        "source": {"projection_path": source_path, "provider": source.get("provider"), "source_endpoint": source.get("source_endpoint"), "request_fingerprint": source.get("request_fingerprint"), "response_sha256": source.get("response_sha256"), "fetched_at": source.get("fetched_at")},
        "metric_definitions": METRICS, "records": out,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic annual financial analysis from an EDINET DB projection.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT)); parser.add_argument("--output", default=str(DEFAULT_OUTPUT)); args = parser.parse_args()
    input_path = Path(args.input); output_path = Path(args.output)
    source = json.loads(input_path.read_text(encoding="utf-8"))
    source_path = str(input_path.relative_to(ROOT)) if input_path.is_relative_to(ROOT) else str(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(build(source, source_path), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
