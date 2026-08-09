from scripts.extract_verified_sec_capex import CAPEX_CONCEPT, audit, extract_event_capex


def event(**overrides):
    base = {
        "event_id": "evt1",
        "company_id": "lam-research",
        "ticker": "LRCX",
        "cik": 707549,
        "accession_number": "0000707549-26-000037",
        "report_date": "2026-06-28",
        "document_type": "10-K",
        "source_adapter": "sec_edgar",
        "freshness": "PASS",
    }
    base.update(overrides)
    return base


def payload(value=723000000):
    return {
        "facts": {
            "us-gaap": {
                CAPEX_CONCEPT: {
                    "units": {
                        "USD": [
                            {
                                "accn": "0000707549-26-000037",
                                "form": "10-K",
                                "start": "2025-06-30",
                                "end": "2026-06-28",
                                "val": value,
                                "fy": 2026,
                                "fp": "FY",
                                "filed": "2026-08-07",
                                "frame": "CY2025",
                            }
                        ]
                    }
                }
            }
        }
    }


def test_extracts_exact_standard_us_gaap_capex():
    metric, issues = extract_event_capex(event(), payload())
    assert issues == []
    assert metric is not None
    assert metric["metric"] == "capital_expenditures"
    assert metric["value"] == 723000000
    assert metric["unit"] == "USD"
    assert metric["concept"] == CAPEX_CONCEPT
    assert metric["accession_number"] == "0000707549-26-000037"
    assert "inferred" in metric["definition"]


def test_rejects_fact_from_different_accession():
    data = payload()
    data["facts"]["us-gaap"][CAPEX_CONCEPT]["units"]["USD"][0]["accn"] = "other"
    metric, issues = extract_event_capex(event(), data)
    assert metric is None
    assert issues[0]["code"] == "NO_VERIFIED_STANDARD_CAPEX_FACT"


def test_rejects_missing_standard_concept():
    metric, issues = extract_event_capex(event(), {"facts": {"us-gaap": {}}})
    assert metric is None
    assert issues[0]["code"] == "NO_STANDARD_CAPEX_CONCEPT"


def test_rejects_conflicting_values_for_same_period():
    data = payload()
    data["facts"]["us-gaap"][CAPEX_CONCEPT]["units"]["USD"].append(
        {
            "accn": "0000707549-26-000037",
            "form": "10-K",
            "start": "2025-06-30",
            "end": "2026-06-28",
            "val": 1,
        }
    )
    metric, issues = extract_event_capex(event(), data)
    assert metric is None
    assert issues[0]["code"] == "AMBIGUOUS_STANDARD_CAPEX_FACT"


def test_does_not_extract_from_non_annual_or_quarterly_form():
    metric, issues = extract_event_capex(event(document_type="8-K"), payload())
    assert metric is None
    assert issues == []


def test_audit_ignores_non_fresh_events():
    result = audit([event(freshness="FAIL")], {707549: payload()})
    assert result["status"] == "PASS"
    assert result["eligible_events_total"] == 0
    assert result["verified_metrics_total"] == 0


def test_audit_fails_closed_when_companyfacts_missing():
    result = audit([event()], {})
    assert result["status"] == "FAIL"
    assert result["issues"][0]["code"] == "MISSING_COMPANYFACTS_PAYLOAD"
