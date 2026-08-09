from scripts.audit_verified_revenue_growth_duration import audit_growth


def base_doc():
    return {
        "schema_version": "verified-revenue-growth.v1",
        "status": "PASS",
        "issues": [],
        "calculated_yoy_total": 1,
        "growth": [
            {
                "event_id": "evt1",
                "metric": "revenue",
                "growth_type": "YoY",
                "unit": "USD",
                "taxonomy": "us-gaap",
                "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "document_type": "10-K",
                "accession_number": "0000707549-26-000037",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000707549.json",
                "current_period_start": "2025-06-30",
                "current_period_end": "2026-06-28",
                "prior_period_start": "2024-07-01",
                "prior_period_end": "2025-06-29",
                "current_value": 120.0,
                "prior_value": 100.0,
                "yoy_percent": 20.0,
            }
        ],
        "not_calculated": [],
    }


def codes(result):
    return {issue["code"] for issue in result["issues"]}


def test_valid_same_duration_yoy_passes():
    result = audit_growth(base_doc())
    assert result["status"] == "PASS"
    assert result["checked_growth_rows_total"] == 1


def test_period_end_gap_outside_year_fails_closed():
    doc = base_doc()
    doc["growth"][0]["prior_period_end"] = "2025-02-01"
    result = audit_growth(doc)
    assert result["status"] == "FAIL"
    assert "INVALID_YOY_END_GAP" in codes(result)


def test_duration_gap_over_seven_days_fails_closed():
    doc = base_doc()
    doc["growth"][0]["prior_period_start"] = "2024-08-01"
    result = audit_growth(doc)
    assert result["status"] == "FAIL"
    assert "INVALID_YOY_DURATION_GAP" in codes(result)


def test_non_primary_companyfacts_url_fails_closed():
    doc = base_doc()
    doc["growth"][0]["source_url"] = "https://example.com/companyfacts.json"
    result = audit_growth(doc)
    assert result["status"] == "FAIL"
    assert "UNSAFE_GROWTH_PROVENANCE" in codes(result)


def test_uncalculated_row_cannot_smuggle_value():
    doc = base_doc()
    doc["calculated_yoy_total"] = 0
    doc["growth"] = []
    doc["not_calculated"] = [{"event_id": "evt2", "reason": "NO_COMPARABLE", "yoy_percent": 1.0}]
    result = audit_growth(doc)
    assert result["status"] == "FAIL"
    assert "UNCALCULATED_ROW_CONTAINS_GROWTH_VALUE" in codes(result)


def test_count_mismatch_fails_closed():
    doc = base_doc()
    doc["calculated_yoy_total"] = 2
    result = audit_growth(doc)
    assert result["status"] == "FAIL"
    assert "CALCULATED_COUNT_MISMATCH" in codes(result)
