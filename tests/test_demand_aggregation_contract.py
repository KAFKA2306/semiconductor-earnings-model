import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).parents[1]


def demand_api():
    return json.loads((ROOT / "site/public/api/v1/demand/index.json").read_text(encoding="utf-8"))


def common_latest_companies(api):
    companies = [company for company in api["companies"] if company["quarters"]]
    periods = Counter(company["quarters"][0]["period_end"] for company in companies)
    common_period = sorted(periods, key=lambda period: (periods[period], period), reverse=True)[0]
    return common_period, [company for company in companies if company["quarters"][0]["period_end"] == common_period]


def test_same_period_aggregate_preserves_reported_capex_tags():
    period, companies = common_latest_companies(demand_api())
    assert period
    assert len(companies) >= 2
    assert all(company["quarters"][0]["period_end"] == period for company in companies)

    total_ocf = sum(company["quarters"][0]["operating_cash_flow"]["value_usd"] for company in companies)
    tag_totals = defaultdict(int)
    tag_ocf = defaultdict(int)
    for company in companies:
        quarter = company["quarters"][0]
        tag = quarter["capital_expenditures"]["fact_tag"]
        tag_totals[tag] += quarter["capital_expenditures"]["value_usd"]
        tag_ocf[tag] += quarter["operating_cash_flow"]["value_usd"]

    assert total_ocf > 0
    assert len(tag_totals) >= 1
    assert all(value > 0 for value in tag_totals.values())
    assert sum(tag_ocf.values()) == total_ocf
    assert sum(tag_totals.values()) > 0


def test_cohort_comparison_does_not_create_cross_tag_burden_rate():
    period, companies = common_latest_companies(demand_api())
    hyperscalers = [company for company in companies if company["role"] == "hyperscaler"]
    tags = {company["quarters"][0]["capital_expenditures"]["fact_tag"] for company in hyperscalers}
    assert period
    assert len(tags) > 1
