#!/usr/bin/env python3
"""Audit the deployed research workbench and financial database."""

from __future__ import annotations

from html import unescape
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import urllib.request


def fetch(url: str, token: str | None = None) -> bytes:
    headers = {"Accept": "application/json", "User-Agent": "financial-research-live-audit"}
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
    financial: dict = {}
    for attempt in range(1, 43):
        nonce = f"{audit_sha}-{attempt}-{time.time_ns()}"
        html = fetch(f"{base}/resilience/?proof={nonce}").decode("utf-8")
        resilience = json.loads(fetch(f"{base}/api/v1/semiconductor-resilience/index.json?proof={nonce}"))
        research = json.loads(fetch(f"{base}/api/v2/semiconductor-research/index.json?proof={nonce}"))
        financial = json.loads(fetch(f"{base}/api/v3/financial-database/index.json?proof={nonce}"))
        resilience_hash = resilience.get("content_hash", "")
        research_hash = research.get("content_hash", "")
        financial_hash = financial.get("content_hash", "")
        if (
            f'data-build-sha="{main_sha}"' in html
            and resilience_hash
            and research_hash
            and financial_hash
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

    allowed_value_types = {
        "actual",
        "company_guidance",
        "analyst_consensus",
        "internal_estimate",
        "scenario",
        "market_observation",
    }
    financial_counts = financial["audit"]["counts"]
    observations = financial["observations"]
    assert financial["schema_version"] == "financial-database.v3"
    assert financial["audit"]["status"] == "PASS"
    assert financial_counts["entities"] == len(financial["entities"])
    assert financial_counts["observations"] == len(observations)
    assert financial_counts["metrics"] == len(financial["derived_metrics"])
    assert financial_counts["actual_observations"] > 0
    assert financial_counts["concepts_catalogued"] >= 40
    assert len({row["id"] for row in observations}) == len(observations)
    assert all(row["value_type"] in allowed_value_types for row in observations)
    assert all(row["source_url"].startswith("https://") for row in observations)
    assert all(row["period_type"] in {"annual", "quarter", "duration", "instant", "point_in_time", "unknown"} for row in observations)
    latest_actual_pairs = [(row["entity_id"], row["concept_id"]) for row in financial["views"]["latest_actuals"]]
    latest_metric_pairs = [(row.get("issuer_id"), row.get("metric_id")) for row in financial["views"]["latest_metrics"]]
    assert len(latest_actual_pairs) == len(set(latest_actual_pairs))
    assert len(latest_metric_pairs) == len(set(latest_metric_pairs))

    db_bytes = fetch(f"{base}/api/v3/financial-database/financial.db?proof={time.time_ns()}")
    with tempfile.TemporaryDirectory() as temporary_directory:
        db_path = Path(temporary_directory) / "financial.db"
        db_path.write_bytes(db_bytes)
        connection = sqlite3.connect(db_path)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        table_counts = {
            "entities": len(financial["entities"]),
            "concepts": len(financial["catalog"]["concepts"]),
            "sources": len(financial["sources"]),
            "observations": len(observations),
            "metrics": len(financial["derived_metrics"]),
            "evaluations": len(financial["evaluations"]),
            "evidence_edges": len(financial["evidence_edges"]),
            "audit_issues": len(financial["audit"]["issues"]),
        }
        for table, expected in table_counts.items():
            actual = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert actual == expected, (table, actual, expected)
        connection.close()

    markers = [
        'id="definition"', 'id="quality"', 'id="actuals"', 'id="peers"',
        'id="scenario"', 'id="ranking"', 'id="history"', 'id="ontology"',
        'id="benchmark"', 'id="limits"',
    ]
    positions = [html.index(marker) for marker in markers]
    assert positions == sorted(positions)
    visible_text = unescape(html)
    phrases = (
        "RESEARCH WORKBENCH",
        "成長しながら下振れに耐えられるか。",
        "企業検索",
        "DATABASE & ONTOLOGY",
        "MARKET BENCHMARK",
        "利益剰余金は現金ではない",
    )
    missing_phrases = [phrase for phrase in phrases if phrase not in visible_text]
    assert not missing_phrases, missing_phrases
    company_row_count = len(re.findall(r"<tr[^>]*data-company-row", html))
    company_card_count = len(re.findall(r"<article[^>]*data-company-card", html))
    assert company_row_count == 12, company_row_count
    assert company_card_count == 12, company_card_count
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
        "financial_api_url": f"{base}/api/v3/financial-database/index.json",
        "financial_sqlite_url": f"{base}/api/v3/financial-database/financial.db",
        "main_sha": main_sha,
        "generated_at": research["generated_at"],
        "financial_generated_at": financial["generated_at"],
        "resilience_hash": resilience["content_hash"],
        "research_hash": research["content_hash"],
        "financial_hash": financial["content_hash"],
        "companies": len(companies),
        "reported_facts": len(database["reported_facts"]),
        "derived_metrics": len(database["derived_metrics"]),
        "evaluations": len(database["evaluations"]),
        "evidence_edges": len(database["evidence_edges"]),
        "financial_counts": financial_counts,
        "financial_sqlite_bytes": len(db_bytes),
        "financial_sqlite_tables": table_counts,
        "ontology_entity_types": len(research["ontology"]["entity_types"]),
        "ontology_relationship_types": len(research["ontology"]["relationship_types"]),
        "benchmark_platforms": len(research["benchmark"]["platforms"]),
        "classification_counts": classifications,
        "view_contract": {
            "ordered_sections": [marker.split('"')[1] for marker in markers],
            "company_rows": company_row_count,
            "company_cards": company_card_count,
            "search": True,
            "role_filter": True,
            "classification_filter": True,
            "sortable_peer_columns": html.count("data-sort=") >= 5,
        },
        "company_results": company_results,
    }
    print("LIVE_FINANCIAL_RESEARCH_PROOF=" + json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
