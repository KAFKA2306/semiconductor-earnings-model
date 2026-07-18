import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_api() -> dict:
    return json.loads((ROOT / "site/public/api/v1/demand/index.json").read_text(encoding="utf-8"))


def test_demand_api_has_five_year_normalized_histories():
    api = load_api()
    companies = [company for company in api["companies"] if company["quarters"]]
    assert api["schema_version"] == "demand-side-api.v1"
    assert len(companies) == 7
    assert min(len(company["quarters"]) for company in companies) >= 5
    assert max(len(company["quarters"]) for company in companies) == 20
    for company in companies:
        assert company["normalization"]["method"] == "within_company_shared_absolute_max"
        assert company["normalization"]["scale_usd"] > 0
        for quarter in company["quarters"]:
            ocf = quarter["operating_cash_flow"]
            capex = quarter["capital_expenditures"]
            assert quarter["period_start"] == ocf["period_start"] == capex["period_start"]
            assert quarter["period_end"] == ocf["period_end"] == capex["period_end"]
            assert isinstance(ocf["value_usd"], int)
            assert isinstance(capex["value_usd"], int)
            assert -100 <= ocf["normalized_value"] <= 100
            assert -100 <= capex["normalized_value"] <= 100
            assert "value_usd_billions" not in ocf
            assert "value_usd_billions" not in capex
            assert len(ocf["source_facts"]) in {1, 2}
            assert len(capex["source_facts"]) in {1, 2}
            assert all(fact["source_api_url"].startswith("https://data.sec.gov/") for fact in ocf["source_facts"] + capex["source_facts"])
            for fact in (ocf, capex):
                if len(fact["source_facts"]) == 1:
                    assert fact["value_type"] == "reported_quarter"
                    assert fact["value_usd"] == fact["source_facts"][0]["reported_value"]
                else:
                    assert fact["value_type"] == "derived_from_reported_periods"
                    assert fact["value_usd"] == fact["source_facts"][0]["reported_value"] - fact["source_facts"][1]["reported_value"]


def test_demand_api_keeps_unavailable_entities_missing():
    api = load_api()
    spacex = next(company for company in api["companies"] if company["id"] == "spacex")
    digital_realty = next(company for company in api["companies"] if company["id"] == "digital-realty")
    assert spacex["quarters"] == []
    assert digital_realty["quarters"] == []
