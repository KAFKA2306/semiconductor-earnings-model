#!/usr/bin/env python3
"""Audit deployed semiconductor resilience Pages and emit compact evidence."""

from __future__ import annotations

import json
import os
import time
import urllib.request


def fetch(url: str, token: str | None = None) -> bytes:
    headers = {"Accept": "application/json", "User-Agent": "semiconductor-resilience-live-audit"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def main() -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    audit_sha = os.environ["GITHUB_SHA"]
    api_root = f"https://api.github.com/repos/{repository}"
    main_sha = json.loads(fetch(f"{api_root}/commits/main", token))["sha"]
    pages = json.loads(fetch(f"{api_root}/pages", token))
    base = pages["html_url"].rstrip("/")

    html = ""
    resilience: dict = {}
    for attempt in range(1, 43):
        nonce = f"{audit_sha}-{attempt}-{time.time_ns()}"
        html = fetch(f"{base}/resilience/?proof={nonce}").decode("utf-8")
        resilience = json.loads(fetch(f"{base}/api/v1/semiconductor-resilience/index.json?proof={nonce}"))
        content_hash = resilience.get("content_hash", "")
        if f'data-build-sha="{main_sha}"' in html and content_hash and f'data-resilience-api-hash="{content_hash}"' in html:
            break
        time.sleep(10)
    else:
        raise AssertionError(f"Live Pages never reached main SHA {main_sha}")

    companies = [company for company in resilience["companies"] if company["years"]]
    assert resilience["schema_version"] == "semiconductor-resilience-api.v1"
    assert len(companies) == 12, len(companies)
    assert all(1 <= len(company["years"]) <= 5 for company in companies)
    assert all(len(company["scenarios"]) == 3 for company in companies)
    assert all(company["years"][0]["period_end"] >= "2024-01-01" for company in companies)
    assert all(company["years"][0]["operating_cash_flow"]["source_url"].startswith("https://www.sec.gov/") for company in companies)
    for marker in ("半導体企業は、", "下振れに何年耐えられるか。", "利益剰余金は現金ではない"):
        assert marker in html

    bands: dict[str, int] = {}
    results = []
    for company in sorted(companies, key=lambda item: item["ticker"]):
        latest = company["years"][0]
        severe = next(item for item in company["scenarios"] if item["scenario_id"] == "severe")
        bands[severe["runway_band"]] = bands.get(severe["runway_band"], 0) + 1
        results.append({
            "ticker": company["ticker"],
            "period_end": latest["period_end"],
            "history_years": len(company["years"]),
            "liquid_reserve_usd": latest["liquid_reserve"]["reported_value"],
            "retained_earnings_usd": latest["retained_earnings"]["reported_value"] if latest["retained_earnings"] else None,
            "base_fcf_usd": latest["free_cash_flow"]["reported_value"],
            "severe_stressed_fcf_usd": severe["stressed_free_cash_flow_usd"],
            "runway_years": severe["liquid_reserve_runway_years"],
            "runway_band": severe["runway_band"],
            "capex_tag": company["selected_tags"]["capital_expenditures"],
            "sec_source": latest["operating_cash_flow"]["source_url"],
        })

    proof = {
        "status": "PASS",
        "pages_url": f"{base}/resilience/",
        "api_url": f"{base}/api/v1/semiconductor-resilience/index.json",
        "main_sha": main_sha,
        "generated_at": resilience["generated_at"],
        "content_hash": resilience["content_hash"],
        "companies": len(companies),
        "severe_bands": bands,
        "results": results,
    }
    print("LIVE_RESILIENCE_PROOF=" + json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
