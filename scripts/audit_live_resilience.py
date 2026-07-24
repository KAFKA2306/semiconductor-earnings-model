#!/usr/bin/env python3
"""Audit the deployed semiconductor resilience Pages route and print evidence."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import date


def fetch(url: str, token: str | None = None, user_agent: str = "semiconductor-resilience-live-audit") -> bytes:
    headers = {"Accept": "application/json", "User-Agent": user_agent}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def print_revenue_candidates(company: dict) -> None:
    user_agent = os.environ.get("SEC_USER_AGENT", "semiconductor-resilience-audit contact via github.com/KAFKA2306")
    cik = str(company["cik"]).zfill(10)
    data = json.loads(fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", user_agent=user_agent))
    candidates = []
    for tag, fact in data["facts"]["us-gaap"].items():
        if "Revenue" not in tag and "Sales" not in tag:
            continue
        periods = set()
        for row in fact.get("units", {}).get("USD", []):
            if row.get("form") != "10-K" or not row.get("start") or not row.get("end"):
                continue
            days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
            if 300 <= days <= 450:
                periods.add((row["start"], row["end"]))
        if periods:
            candidates.append((max(end for _, end in periods), len(periods), tag))
    for latest_end, count, tag in sorted(candidates, reverse=True)[:20]:
        print(f"SEC_REVENUE_CANDIDATE {company['ticker']} latest={latest_end} periods={count} tag={tag}", flush=True)


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
        try:
            html = fetch(f"{base}/resilience/?proof={nonce}").decode("utf-8")
            resilience = json.loads(fetch(f"{base}/api/v1/semiconductor-resilience/index.json?proof={nonce}"))
        except Exception as exc:
            print(f"PROPAGATION attempt={attempt} error={type(exc).__name__}", flush=True)
            time.sleep(10)
            continue
        content_hash = resilience.get("content_hash", "")
        if f'data-build-sha="{main_sha}"' in html and content_hash and f'data-resilience-api-hash="{content_hash}"' in html:
            break
        print(f"PROPAGATION attempt={attempt} live_build_not_main={main_sha}", flush=True)
        time.sleep(10)
    else:
        raise AssertionError(f"Live Pages never reached main SHA {main_sha}")

    companies = [company for company in resilience["companies"] if company["years"]]
    print(f"OBSERVED main_sha={main_sha} generated_at={resilience.get('generated_at')} companies={len(companies)}", flush=True)
    for company in companies:
        latest = company["years"][0]
        print(f"OBSERVED {company['ticker']} period={latest['period_end']} revenue_tag={company['selected_tags']['revenue']} cash_tag={company['selected_tags']['cash']}", flush=True)

    stale_companies = [company for company in companies if company["years"][0]["period_end"] < "2024-01-01"]
    for company in stale_companies:
        print_revenue_candidates(company)

    assert resilience["schema_version"] == "semiconductor-resilience-api.v1"
    assert len(companies) >= 10, len(companies)
    assert all(1 <= len(company["years"]) <= 5 for company in companies)
    assert all(len(company["scenarios"]) == 3 for company in companies)
    stale = [(company["ticker"], company["years"][0]["period_end"]) for company in stale_companies]
    assert not stale, f"stale annual periods: {stale}"
    assert all(company["years"][0]["operating_cash_flow"]["source_url"].startswith("https://www.sec.gov/") for company in companies)
    for marker in ("半導体企業は、", "下振れに何年耐えられるか。", "利益剰余金は現金ではない"):
        assert marker in html

    severe_rows = []
    bands: dict[str, int] = {}
    for company in companies:
        latest = company["years"][0]
        severe = next(item for item in company["scenarios"] if item["scenario_id"] == "severe")
        bands[severe["runway_band"]] = bands.get(severe["runway_band"], 0) + 1
        severe_rows.append({
            "ticker": company["ticker"], "period_end": latest["period_end"],
            "revenue_tag": company["selected_tags"]["revenue"], "cash_tag": company["selected_tags"]["cash"],
            "liquid_reserve_usd": latest["liquid_reserve"]["reported_value"],
            "stressed_fcf_usd": severe["stressed_free_cash_flow_usd"],
            "runway_years": severe["liquid_reserve_runway_years"], "runway_band": severe["runway_band"],
            "sec_source": latest["operating_cash_flow"]["source_url"],
        })

    print(f"PROOF pages_url={base}/resilience/")
    print(f"PROOF main_sha={main_sha}")
    print(f"PROOF generated_at={resilience['generated_at']}")
    print(f"PROOF content_hash={resilience['content_hash']}")
    print(f"PROOF companies={len(companies)} severe_bands={json.dumps(bands, sort_keys=True)}")
    for row in sorted(severe_rows, key=lambda item: item["ticker"]):
        print("COMPANY " + json.dumps(row, sort_keys=True))
    print("LIVE_RESILIENCE_AUDIT=PASS")


if __name__ == "__main__":
    main()
