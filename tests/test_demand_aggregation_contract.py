import json
from collections import Counter, defaultdict
from pathlib import Path
import shutil
import subprocess

import pytest


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
    # Live SEC facts can legitimately use a single CapEx tag. Exercise the
    # actual frontend aggregator with a controlled mixed-tag cohort instead.
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to verify the frontend aggregation contract")

    script = """
import { buildDemandAggregation } from './site/src/lib/demand-aggregation.js';
const company = (name, role, tag, capex, ocf) => ({
  name, role,
  quarters: [{
    period_end: '2026-03-31',
    capital_expenditures: { fact_tag: tag, value_usd: capex },
    operating_cash_flow: { value_usd: ocf },
  }],
});
const api = { companies: [
  company('A', 'hyperscaler', 'PaymentsToAcquireProductiveAssets', 20, 100),
  company('B', 'hyperscaler', 'PaymentsToAcquirePropertyPlantAndEquipment', 30, 200),
  company('C', 'ai-cloud', 'PaymentsToAcquireProductiveAssets', 10, 100),
]};
const aggregation = buildDemandAggregation(api);
const mixed = aggregation.cohorts.find((cohort) => cohort.id === 'hyperscalers');
const single = aggregation.cohorts.find((cohort) => cohort.id === 'ai-cloud');
console.log(JSON.stringify({
  period: aggregation.commonPeriod,
  mixedTags: mixed.tags.map((tag) => tag.tag),
  mixedTotal: mixed.tags.reduce((total, tag) => total + tag.total, 0),
  mixedBurden: mixed.comparableBurden,
  singleTags: single.tags.map((tag) => tag.tag),
  singleTotal: single.tags[0].total,
  singleBurden: single.comparableBurden,
}));
"""
    output = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    actual = json.loads(output.stdout)
    assert actual["period"] == "2026-03-31"
    assert set(actual["mixedTags"]) == {
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantAndEquipment",
    }
    assert actual["mixedTotal"] == 50
    assert actual["mixedBurden"] is None
    assert actual["singleTags"] == ["PaymentsToAcquireProductiveAssets"]
    assert actual["singleTotal"] == 10
    assert actual["singleBurden"] == 0.1
