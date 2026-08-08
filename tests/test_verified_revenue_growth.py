from scripts.derive_verified_revenue_growth import derive_yoy


def base_docs():
    metric = {
        "event_id": "evt1",
        "company_id": "lam-research",
        "ticker": "LRCX",
        "accession_number": "0000707549-26-000037",
        "period_end": "2026-06-28",
        "document_type": "10-K",
        "metric": "revenue",
        "value": 120.0,
        "unit": "USD",
        "taxonomy": "us-gaap",
        "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "fiscal_period": "FY",
        "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000707549.json",
    }
    metrics = {"status": "PASS", "issues": [], "verified_metrics_total": 1, "metrics": [metric]}
    lineage = {"status": "PASS", "issues": [], "checked_metrics_total": 1}
    payload = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "accn": "0000707549-26-000037",
                                "form": "10-K",
                                "start": "2025-06-30",
                                "end": "2026-06-28",
                                "val": 120.0,
                                "fp": "FY",
                            },
                            {
                                "accn": "0000707549-26-000037",
                                "form": "10-K",
                                "start": "2024-07-01",
                                "end": "2025-06-29",
                                "val": 100.0,
                                "fp": "FY",
                            },
                        ]
                    }
                }
            }
        }
    }
    return metrics, lineage, {metric["source_url"]: payload}


def test_same_filing_comparable_yoy_is_calculated():
    result = derive_yoy(*base_docs())
    assert result["status"] == "PASS"
    assert result["calculated_yoy_total"] == 1
    assert result["growth"][0]["yoy_percent"] == 20.0
    assert result["growth"][0]["prior_period_end"] == "2025-06-29"


def test_missing_comparable_persists_no_growth_value():
    metrics, lineage, payloads = base_docs()
    payload = next(iter(payloads.values()))
    payload["facts"]["us-gaap"][metrics["metrics"][0]["concept"]]["units"]["USD"] = [
        payload["facts"]["us-gaap"][metrics["metrics"][0]["concept"]]["units"]["USD"][0]
    ]
    result = derive_yoy(metrics, lineage, payloads)
    assert result["status"] == "PASS"
    assert result["calculated_yoy_total"] == 0
    assert result["growth"] == []
    assert result["not_calculated"][0]["reason"] == "NO_COMPARABLE_PRIOR_YEAR_FACT_IN_SAME_FILING"


def test_lineage_failure_fails_closed():
    metrics, lineage, payloads = base_docs()
    lineage["status"] = "FAIL"
    result = derive_yoy(metrics, lineage, payloads)
    assert result["status"] == "FAIL"
    assert {issue["code"] for issue in result["issues"]} >= {"VERIFIED_REVENUE_LINEAGE_NOT_PASS"}


def test_non_primary_source_fails_closed():
    metrics, lineage, payloads = base_docs()
    metric = metrics["metrics"][0]
    old_url = metric["source_url"]
    metric["source_url"] = "https://example.com/companyfacts.json"
    payloads[metric["source_url"]] = payloads.pop(old_url)
    result = derive_yoy(metrics, lineage, payloads)
    assert result["status"] == "FAIL"
    assert {issue["code"] for issue in result["issues"]} >= {"UNSAFE_CURRENT_METRIC"}


def test_duration_mismatch_is_not_calculated():
    metrics, lineage, payloads = base_docs()
    payload = next(iter(payloads.values()))
    rows = payload["facts"]["us-gaap"][metrics["metrics"][0]["concept"]]["units"]["USD"]
    rows[1]["start"] = "2025-01-01"
    result = derive_yoy(metrics, lineage, payloads)
    assert result["status"] == "PASS"
    assert result["growth"] == []


def test_ambiguous_prior_year_values_fail_closed():
    metrics, lineage, payloads = base_docs()
    payload = next(iter(payloads.values()))
    rows = payload["facts"]["us-gaap"][metrics["metrics"][0]["concept"]]["units"]["USD"]
    rows.append({
        "accn": "0000707549-26-000037",
        "form": "10-K",
        "start": "2024-07-01",
        "end": "2025-06-29",
        "val": 101.0,
        "fp": "FY",
    })
    result = derive_yoy(metrics, lineage, payloads)
    assert result["status"] == "FAIL"
    assert {issue["code"] for issue in result["issues"]} >= {"AMBIGUOUS_PRIOR_YEAR_FACT"}


def test_zero_prior_value_fails_closed():
    metrics, lineage, payloads = base_docs()
    payload = next(iter(payloads.values()))
    rows = payload["facts"]["us-gaap"][metrics["metrics"][0]["concept"]]["units"]["USD"]
    rows[1]["val"] = 0
    result = derive_yoy(metrics, lineage, payloads)
    assert result["status"] == "FAIL"
    assert {issue["code"] for issue in result["issues"]} >= {"ZERO_PRIOR_VALUE"}
