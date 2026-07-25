#!/usr/bin/env python3
"""Finalize generated research API evaluations and refresh its content hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
API_PATH = ROOT / "site/public/api/v2/semiconductor-research/index.json"


def corrected_minimum_runway_result(*, self_funding: bool, runway_years: float | None) -> str:
    if self_funding:
        return "pass"
    if runway_years is None:
        return "unknown"
    return "pass" if runway_years >= 2 else "fail"


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> None:
    payload = json.loads(API_PATH.read_text(encoding="utf-8"))
    for company in payload["companies"]:
        severe = next(item for item in company["scenarios"] if item["scenario_id"] == "severe")
        evaluation = next(item for item in company["evaluations"] if item["rule_id"] == "minimum_two_year_runway")
        evaluation["result"] = corrected_minimum_runway_result(
            self_funding=severe["annual_cash_burn_usd"] == 0,
            runway_years=severe["liquid_reserve_runway_years"],
        )
        for record in payload["database"]["evaluations"]:
            if record["issuer_id"] == company["id"] and record["rule_id"] == "minimum_two_year_runway":
                record["result"] = evaluation["result"]
    payload_core = {key: value for key, value in payload.items() if key != "content_hash"}
    payload["content_hash"] = content_hash(payload_core)
    API_PATH.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("research_api_finalized=self_funding_runway_pass")


if __name__ == "__main__":
    main()
