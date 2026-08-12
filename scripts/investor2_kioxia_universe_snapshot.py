from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "config" / "investor2_kioxia_semiconductor_universe_50_2026-08-12.json"
BASE_PLAN_PATH = ROOT / "config" / "edinetdb_quota_plan.json"
PROJECTIONS_ROOT = ROOT / "data" / "edinetdb_projections" / "KAFKA2306__investor2"
OUTPUT_PATH = PROJECTIONS_ROOT / "investor2-kioxia-semiconductor-universe-50-5y-quarterly.json"

# Only deterministic first-party/official filing channels are canonical by default.
# Other fetched rows are retained, but quarantined instead of silently discarded.
CANONICAL_SOURCE_TYPES = {"edinet_annual", "edinet_quarterly", "quarterly_disclosure"}
FLOW_FIELDS = (
    "revenue",
    "operating_income",
    "ordinary_income",
    "net_income",
    "profit_ifrs",
    "cf_operating",
    "cf_investing",
    "cf_financing",
    "gross_profit",
    "sga",
    "capex",
)
STOCK_FIELDS = (
    "total_assets",
    "net_assets",
    "total_liabilities",
    "total_equity",
    "shareholders_equity",
    "cash",
    "bps",
)
QUARTER_FIELDS = [
    "fiscal_year",
    "quarter",
    "accounting_standard",
    "basis",
    "basis_source",
    *FLOW_FIELDS,
    "eps",
    *STOCK_FIELDS,
    "derivation_method",
    "has_prev_ytd",
    "source_type",
    "prev_source_type",
    "submit_date_time",
    "doc_id",
    "edinet_filing_url",
    "edinet_view_url",
]
MASTER_FIELDS = [
    "edinet_code",
    "sec_code",
    "name",
    "industry",
    "accounting_standard",
    "latest_fiscal_year",
    "listing_status",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def projection_id(code: str) -> str:
    return f"investor2-kioxia-universe-{code.lower()}-quarterly-5y"


def build_plan() -> dict[str, Any]:
    base = load_json(BASE_PLAN_PATH)
    universe = load_json(UNIVERSE_PATH)
    companies = universe["companies"]
    codes = [row["edinet_code"] for row in companies]
    code_consumers = {code: ["KAFKA2306/investor2"] for code in codes}
    requests = []
    for code in codes:
        requests.append(
            {
                "id": projection_id(code),
                "consumer": "KAFKA2306/investor2",
                "method": "GET",
                "path": f"/v1/companies/{code}/financials",
                "params": {"period": "quarterly_standalone", "years": "5"},
                "projection_fields": QUARTER_FIELDS,
            }
        )
    return {
        "schema_version": base["schema_version"],
        "daily_limit": base["daily_limit"],
        "reserve_requests": base["reserve_requests"],
        "monthly_limit": base["monthly_limit"],
        "monthly_reserve_requests": base.get("monthly_reserve_requests", 0),
        "refresh_after_jst": base["refresh_after_jst"],
        "attribution": base["attribution"],
        "consumer_registry": base["consumer_registry"],
        "policy": base["policy"],
        "company_master": {
            "codes": codes,
            "code_consumers": code_consumers,
            "projection_fields": MASTER_FIELDS,
        },
        "requests": requests,
    }


def canonical_reason(record: dict[str, Any]) -> tuple[bool, str | None]:
    source_type = record.get("source_type")
    if source_type not in CANONICAL_SOURCE_TYPES:
        if source_type == "kabupro":
            return False, "third_party_backfill"
        if source_type == "ir_pdf":
            return False, "ir_pdf_extraction_requires_primary_url_verification"
        return False, "source_type_not_first_party_allowlisted"
    # Keep the filing/disclosure row, but mark traceability gaps explicitly.
    if not record.get("doc_id") and not record.get("edinet_filing_url"):
        return False, "official_source_identifier_missing"
    return True, None


def derive_annual(quarters: list[dict[str, Any]]) -> dict[str, Any]:
    by_q = {int(row["quarter"]): row for row in quarters if row.get("quarter") in (1, 2, 3, 4)}
    result: dict[str, Any] = {
        "fiscal_year": quarters[0].get("fiscal_year") if quarters else None,
        "complete_four_quarters": set(by_q) == {1, 2, 3, 4},
        "canonical": bool(by_q) and set(by_q) == {1, 2, 3, 4} and all(
            row.get("canonical_eligible", False) for row in by_q.values()
        ),
        "source_quarters": [
            {
                "quarter": q,
                "source_type": by_q[q].get("source_type"),
                "doc_id": by_q[q].get("doc_id"),
                "edinet_filing_url": by_q[q].get("edinet_filing_url"),
            }
            for q in sorted(by_q)
        ],
    }
    for field in FLOW_FIELDS:
        values = [by_q[q].get(field) for q in (1, 2, 3, 4)] if set(by_q) == {1, 2, 3, 4} else []
        result[field] = sum(values) if values and all(value is not None for value in values) else None
    q4 = by_q.get(4, {})
    for field in STOCK_FIELDS:
        result[field] = q4.get(field)
    # Standalone-quarter EPS is not safely additive across changing weighted-average share counts.
    result["eps"] = None
    result["eps_note"] = "not_derived_from_standalone_quarters"
    return result


def aggregate() -> dict[str, Any]:
    universe = load_json(UNIVERSE_PATH)
    companies_out = []
    missing = []
    canonical_count = 0
    quarantined_count = 0
    fetched_count = 0

    for company in universe["companies"]:
        code = company["edinet_code"]
        path = PROJECTIONS_ROOT / f"{projection_id(code)}.json"
        if not path.exists():
            missing.append(code)
            continue
        projection = load_json(path)
        records = []
        for raw in projection.get("records", []):
            row = dict(raw)
            eligible, reason = canonical_reason(row)
            row["canonical_eligible"] = eligible
            row["quarantine_reason"] = reason
            records.append(row)
            fetched_count += 1
            canonical_count += int(eligible)
            quarantined_count += int(not eligible)

        by_fy: dict[int, list[dict[str, Any]]] = {}
        for row in records:
            fy = row.get("fiscal_year")
            if isinstance(fy, int):
                by_fy.setdefault(fy, []).append(row)
        annual = [derive_annual(by_fy[fy]) for fy in sorted(by_fy)]
        companies_out.append(
            {
                **company,
                "projection": {
                    "projection_id": projection.get("projection_id"),
                    "request_fingerprint": projection.get("request_fingerprint"),
                    "provider_response_sha256": projection.get("response_sha256"),
                    "fetched_at": projection.get("fetched_at"),
                    "source_endpoint": projection.get("source_endpoint"),
                },
                "quarterly": records,
                "annual_derived_from_quarters": annual,
            }
        )

    if missing:
        raise RuntimeError(f"missing company projections: {', '.join(missing)}")

    fetched_times = [
        row["projection"]["fetched_at"]
        for row in companies_out
        if row.get("projection", {}).get("fetched_at")
    ]
    payload = {
        "schema_version": "investor2.kioxia-semiconductor-universe-financials.v1",
        "consumer": "KAFKA2306/investor2",
        "dataset_id": "kioxia-semiconductor-universe-50-5y-quarterly",
        "as_of": universe["as_of"],
        "retrieved_at_max": max(fetched_times) if fetched_times else None,
        "company_count": len(companies_out),
        "requested_years": 5,
        "period": "quarterly_standalone",
        "annual_policy": "derive annual flow totals only when Q1-Q4 standalone values are all present; use Q4 period-end stock values; do not derive annual EPS",
        "canonical_policy": {
            "allowlisted_source_types": sorted(CANONICAL_SOURCE_TYPES),
            "non_allowlisted_rows_are_retained": True,
            "non_allowlisted_rows_location": "company.quarterly with canonical_eligible=false and quarantine_reason",
            "null_is_never_zero": True,
        },
        "counts": {
            "fetched_quarter_rows": fetched_count,
            "canonical_eligible_quarter_rows": canonical_count,
            "quarantined_quarter_rows": quarantined_count,
        },
        "universe": universe,
        "companies": companies_out,
        "provider": "EDINET DB",
        "attribution": "Powered by EDINET DB",
        "provider_terms": "https://edinetdb.jp/legal/terms",
    }
    dump_json(OUTPUT_PATH, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--output", required=True)
    sub.add_parser("aggregate")
    args = parser.parse_args()

    if args.command == "plan":
        dump_json(Path(args.output), build_plan())
    else:
        payload = aggregate()
        print(
            json.dumps(
                {
                    "output": str(OUTPUT_PATH.relative_to(ROOT)),
                    "company_count": payload["company_count"],
                    **payload["counts"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
