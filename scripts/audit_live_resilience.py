#!/usr/bin/env python3
"""Audit deployed semiconductor research workbench and emit compact evidence."""

from __future__ import annotations

import json
import os
import time
import urllib.request


def fetch(url: str, token: str | None = None) -> bytes:
    headers = {"Accept": "application/json", "User-Agent": "semiconductor-research-live-audit"}
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
    research: dict = {}
    for attempt in range(1, 43):
        nonce = f"{audit_sha}-{attempt}-{time.time_ns()}"
        html = fetch(f"{base}/resilience/?proof={nonce}").decode("utf-8")
        resilience = json.loads(fetch(f"{base}/api/v1/semiconductor-resilience/index.json?proof={nonce}"))
        research = json.loads(fetch(f"{base}/api/v2/semiconductor-research/index.json?proof={nonce}"))
        resilience_hash = resilience.get("content_hash", "")
        research_hash = research.get("content_hash", "")
        if (
            f'data-build-sha="{main_sha}"' in html
            and resilience_hash
            and research_hash
            and f'data-resilience-api-hash="{resilience_hash}"' in html
            and f'data-research-api-hash="{research_hash}"' in html
        ):
            break
        print(f"PROPAGATION attempt={attempt} expected_main={main_sha}")
        time.sleep(10)
    else:
        raise AssertionError(f"Live Pages never reached main SHA {main_sha}")

    companies = research["companies"]
    database = research["database"]
    summary = research["summary"]
    assert resilience["schema_version"] == "semiconductor-resilience-api.v1"
    assert research["schema_version"] == "semiconductor-research-workbench.v2"
    assert len(companies) == 12 == summary["company_count"]
    assert summary["reported_fact_count"] >= 250
    assert summary["derived_metric_count"] >= 180
    assert summary["evaluation_count"] >= 72
    assert summary["evidence_edge_count"] >= 100
    assert summary["benchmark_platform_count"] >= 12
    assert all(company["latest_annual_period"] >= "2024-01-01" for company in companies)
    assert all(len(company["evaluations"]) == 6 for company in companies)
    assert all(len(company["peer_context"]) >= 10 for company in companies)
    assert all(fact["source_url"].startswith("https://www.sec.gov/") for fact in database["reported_facts"])
    assert {edge["relationship"] for edge in database["evidence_edges"]} >= {"derived_from", "uses_metric"}
    assert all(
        next(item for item in company["evaluations"] if item["rule_id"] == "minimum_two_year_runway")["result"] == "pass"
        for company in companies
        if company["metrics"]["severe_runway_band"] == "self_funding"
    )

    markers = [
        'id="definition"', 'id="quality"', 'id="actuals"', 'id="peers"',
        'id="scenario"', 'id="ranking"', 'id="history"', 'id="ontology"',
        'id="benchmark"', 'id="limits"',
    ]
    positions = [html.index(marker) for marker in markers]
    assert positions == sorted(positions)
    for phrase in (
        "RESEARCH WORKBENCH",
        "成長しながら下振れに耐えられるか。",
        "企業検索",
        "DATABASE &amp; ONTOLOGY",
        "MARKET BENCHMARK",
        "利益剰余金は現金ではない",
    ):
        assert phrase in html
    assert html.count("data-company-row") == 12
    assert html.count("data-company-card") == 12
    assert 'id="company-search"' in html
    assert 'id="role-filter"' in html
    assert 'id="classification-filter"' in html

    classifications: dict[str, int] = {}
    company_results = []
    for company in sorted(companies, key=lambda item: item["ticker"]):
        classifications[company["classification"]] = classifications.get(company["classification"], 0) + 1
        company_results.append({
            "ticker": company["ticker"],
            "classification": company["classification"],
            "quality": company["metrics"]["data_completeness"],
            "revenue_yoy": company["metrics"]["revenue_yoy"],
            "operating_margin": company["metrics"]["operating_margin"],
            "fcf_margin": company["metrics"]["free_cash_flow_margin"],
            "severe_runway_band": company["metrics"]["severe_runway_band"],
            "severe_runway_years": company["metrics"]["severe_runway_years"],
            "annual_period": company["latest_annual_period"],
            "quarter_period": company["latest_quarter_period"],
        })

    proof = {
        "status": "PASS",
        "pages_url": f"{base}/resilience/",
        "research_api_url": f"{base}/api/v2/semiconductor-research/index.json",
        "main_sha": main_sha,
        "generated_at": research["generated_at"],
        "resilience_hash": resilience["content_hash"],
        "research_hash": research["content_hash"],
        "companies": len(companies),
        "reported_facts": len(database["reported_facts"]),
        "derived_metrics": len(database["derived_metrics"]),
        "evaluations": len(database["evaluations"]),
        "evidence_edges": len(database["evidence_edges"]),
        "ontology_entity_types": len(research["ontology"]["entity_types"]),
        "ontology_relationship_types": len(research["ontology"]["relationship_types"]),
        "benchmark_platforms": len(research["benchmark"]["platforms"]),
        "classification_counts": classifications,
        "view_contract": {
            "ordered_sections": [marker[4:-1] for marker in markers],
            "company_rows": html.count("data-company-row"),
            "company_cards": html.count("data-company-card"),
            "search": True,
            "role_filter": True,
            "classification_filter": True,
            "sortable_peer_columns": html.count("data-sort=") >= 5,
        },
        "company_results": company_results,
    }
    print("LIVE_RESEARCH_WORKBENCH_PROOF=" + json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
