from pathlib import Path

from scripts.build_verified_revenue_actuals_ledger import build_actuals
from scripts.derive_persisted_revenue_growth import derive_persisted_growth


def docs():
    metric = {
        "event_id": "evt-q2", "company_id": "example", "ticker": "EX",
        "accession_number": "0000000000-26-000010", "period_end": "2026-06-30",
        "document_type": "10-Q", "metric": "revenue", "value": 120.0, "unit": "USD",
        "taxonomy": "us-gaap", "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "fiscal_period": "Q2", "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
    }
    metrics = {"status": "PASS", "issues": [], "verified_metrics_total": 1, "metrics": [metric]}
    lineage = {"status": "PASS", "issues": [], "checked_metrics_total": 1}
    rows = [
        {"accn": metric["accession_number"], "form": "10-Q", "start": "2026-04-01", "end": "2026-06-30", "val": 120.0, "fy": 2026, "fp": "Q2", "filed": "2026-07-20"},
        {"accn": "0000000000-26-000005", "form": "10-Q", "start": "2026-01-01", "end": "2026-03-31", "val": 100.0, "fy": 2026, "fp": "Q1", "filed": "2026-04-20"},
        {"accn": metric["accession_number"], "form": "10-Q", "start": "2025-04-01", "end": "2025-06-30", "val": 80.0, "fy": 2026, "fp": "Q2", "filed": "2026-07-20"},
    ]
    payload = {"facts": {"us-gaap": {metric["concept"]: {"units": {"USD": rows}}}}}
    return metrics, lineage, {metric["source_url"]: payload}


def test_builder_persists_multi_period_actuals_then_comparator_joins_them():
    metrics, lineage, payloads = docs()
    actuals, issues = build_actuals(metrics, lineage, payloads)
    assert issues == []
    assert len(actuals) == 3
    manifest = {"status": "PASS", "issues": [], "actuals_total": len(actuals)}
    result = derive_persisted_growth(metrics, lineage, manifest, actuals)
    assert result["status"] == "PASS"
    values = {row["growth_type"]: row for row in result["growth"]}
    assert values["QoQ"]["qoq_percent"] == 20.0
    assert values["YoY"]["yoy_percent"] == 50.0
    assert all(row["actuals_ledger"].endswith("verified_revenue_actuals.ndjson") for row in result["growth"])


def test_missing_prior_is_explicit_not_calculated():
    metrics, lineage, payloads = docs()
    payloads[metrics["metrics"][0]["source_url"]]["facts"]["us-gaap"][metrics["metrics"][0]["concept"]]["units"]["USD"] = payloads[metrics["metrics"][0]["source_url"]]["facts"]["us-gaap"][metrics["metrics"][0]["concept"]]["units"]["USD"][:1]
    actuals, issues = build_actuals(metrics, lineage, payloads)
    result = derive_persisted_growth(metrics, lineage, {"status": "PASS", "issues": [], "actuals_total": len(actuals)}, actuals)
    assert issues == [] and result["status"] == "PASS" and result["growth"] == []
    assert {row["growth_type"] for row in result["not_calculated"]} == {"QoQ", "YoY"}


def test_ambiguous_prior_quarter_fails_closed():
    metrics, lineage, payloads = docs()
    rows = payloads[metrics["metrics"][0]["source_url"]]["facts"]["us-gaap"][metrics["metrics"][0]["concept"]]["units"]["USD"]
    rows.append({"accn": "0000000000-26-000006", "form": "10-Q", "start": "2026-01-01", "end": "2026-03-31", "val": 101.0, "fp": "Q1"})
    actuals, issues = build_actuals(metrics, lineage, payloads)
    result = derive_persisted_growth(metrics, lineage, {"status": "PASS", "issues": [], "actuals_total": len(actuals)}, actuals)
    assert issues == []
    assert result["status"] == "FAIL"
    assert "AMBIGUOUS_PRIOR_QUARTER_ACTUAL" in {item["code"] for item in result["issues"]}


def test_non_primary_metric_source_fails_closed_before_persistence():
    metrics, lineage, payloads = docs()
    old = metrics["metrics"][0]["source_url"]
    metrics["metrics"][0]["source_url"] = "https://example.com/companyfacts.json"
    payloads[metrics["metrics"][0]["source_url"]] = payloads.pop(old)
    actuals, issues = build_actuals(metrics, lineage, payloads)
    assert actuals == []
    assert "UNSAFE_CURRENT_METRIC" in {item["code"] for item in issues}


def test_comparator_source_contains_no_network_client():
    source = Path("scripts/derive_persisted_revenue_growth.py").read_text(encoding="utf-8")
    assert "urllib.request" not in source
    assert "urlopen(" not in source
    assert "requests." not in source
