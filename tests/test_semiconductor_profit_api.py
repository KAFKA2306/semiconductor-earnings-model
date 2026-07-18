import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_api() -> dict:
    return json.loads((ROOT / "site/public/api/v1/semiconductor-profit/index.json").read_text(encoding="utf-8"))


def test_profit_api_is_direct_and_keeps_five_year_history():
    api = load_api()
    assert api["schema_version"] == "semiconductor-profit-api.v1"
    assert api["target"]["id"] == "sox"
    companies = [company for company in api["companies"] if company["quarters"]]
    assert len(companies) >= 10
    assert min(len(company["quarters"]) for company in companies) >= 19
    assert all(
        len(company["quarters"]) <= 20
        and company["quarters"] == sorted(company["quarters"], key=lambda quarter: quarter["period_end"], reverse=True)
        and all(
            quarter["revenue"]["period_start"] == quarter["operating_income"]["period_start"]
            and quarter["revenue"]["period_end"] == quarter["operating_income"]["period_end"]
            for quarter in company["quarters"]
        )
        for company in companies
    )
    assert all(
        isinstance(fact["reported_value"], int)
        and fact["source_kind"] == "SEC EDGAR Companyfacts / 10-Q"
        and fact["source_api_url"].startswith("https://data.sec.gov/")
        and "value_usd_billions" not in fact
        for company in companies
        for fact in company["facts"]
    )


def test_ambiguous_common_period_is_preserved_without_aggregation():
    api = load_api()
    assert api["cohort"]["status"] == "ambiguous"
    assert api["cohort"]["company_ids"] == []
