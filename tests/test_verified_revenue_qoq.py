from scripts.derive_verified_revenue_qoq import derive_qoq


def base_docs():
    metric = {
        "event_id": "evt-q1",
        "company_id": "example",
        "ticker": "EX",
        "accession_number": "0000000000-26-000010",
        "period_end": "2026-06-30",
        "document_type": "10-Q",
        "metric": "revenue",
        "value": 120.0,
        "unit": "USD",
        "taxonomy": "us-gaap",
        "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "fiscal_period": "Q2",
        "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
    }
    metrics = {"status": "PASS", "issues": [], "verified_metrics_total": 1, "metrics": [metric]}
    lineage = {"status": "PASS", "issues": [], "checked_metrics_total": 1}
    payload = {
        "facts": {
            "us-gaap": {
                metric["concept"]: {
                    "units": {
                        "USD": [
                            {
                                "accn": metric["accession_number"],
                                "form": "10-Q",
                                "start": "2026-04-01",
                                "end": "2026-06-30",
                                "val": 120.0,
                                "fp": "Q2",
                            },
                            {
                                "accn": "0000000000-26-000005",
                                "form": "10-Q",
                                "start": "2026-01-01",
                                "end": "2026-03-31",
                                "val": 100.0,
                                "fp": "Q1",
                            },
                        ]
                    }
                }
            }
        }
    }
    return metrics, lineage, {metric["source_url"]: payload}


def test_comparable_standalone_quarters_calculate_qoq():
    result = derive_qoq(*base_docs())
    assert result["status"] == "PASS"
    assert result["calculated_qoq_total"] == 1
    assert result["growth"][0]["qoq_percent"] == 20.0
    assert result["growth"][0]["prior_period_end"] == "2026-03-31"


def test_non_quarter_current_fact_persists_no_qoq_value():
    metrics, lineage, payloads = base_docs()
    metric = metrics["metrics"][0]
    rows = payloads[metric["source_url"]]["facts"]["us-gaap"][metric["concept"]]["units"]["USD"]
    rows[0]["start"] = "2025-07-01"
    result = derive_qoq(metrics, lineage, payloads)
    assert result["status"] == "PASS"
    assert result["growth"] == []
    assert result["not_calculated"][0]["reason"] == "CURRENT_FACT_NOT_STANDALONE_QUARTER"


def test_missing_prior_quarter_persists_no_qoq_value():
    metrics, lineage, payloads = base_docs()
    metric = metrics["metrics"][0]
    rows = payloads[metric["source_url"]]["facts"]["us-gaap"][metric["concept"]]["units"]["USD"]
    del rows[1:]
    result = derive_qoq(metrics, lineage, payloads)
    assert result["status"] == "PASS"
    assert result["growth"] == []
    assert result["not_calculated"][0]["reason"] == "NO_COMPARABLE_PRIOR_QUARTER_FACT"


def test_ambiguous_prior_quarter_fails_closed():
    metrics, lineage, payloads = base_docs()
    metric = metrics["metrics"][0]
    rows = payloads[metric["source_url"]]["facts"]["us-gaap"][metric["concept"]]["units"]["USD"]
    rows.append({
        "accn": "0000000000-26-000006",
        "form": "10-Q",
        "start": "2026-01-01",
        "end": "2026-03-31",
        "val": 101.0,
        "fp": "Q1",
    })
    result = derive_qoq(metrics, lineage, payloads)
    assert result["status"] == "FAIL"
    assert "AMBIGUOUS_PRIOR_QUARTER_FACT" in {issue["code"] for issue in result["issues"]}


def test_zero_prior_value_fails_closed():
    metrics, lineage, payloads = base_docs()
    metric = metrics["metrics"][0]
    rows = payloads[metric["source_url"]]["facts"]["us-gaap"][metric["concept"]]["units"]["USD"]
    rows[1]["val"] = 0
    result = derive_qoq(metrics, lineage, payloads)
    assert result["status"] == "FAIL"
    assert "ZERO_PRIOR_VALUE" in {issue["code"] for issue in result["issues"]}


def test_non_primary_source_fails_closed():
    metrics, lineage, payloads = base_docs()
    metric = metrics["metrics"][0]
    old_url = metric["source_url"]
    metric["source_url"] = "https://example.com/companyfacts.json"
    payloads[metric["source_url"]] = payloads.pop(old_url)
    result = derive_qoq(metrics, lineage, payloads)
    assert result["status"] == "FAIL"
    assert "UNSAFE_CURRENT_METRIC" in {issue["code"] for issue in result["issues"]}
