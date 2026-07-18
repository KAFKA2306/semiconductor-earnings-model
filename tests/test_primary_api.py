import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_api() -> dict:
    return json.loads((ROOT / "site/public/api/v1/index.json").read_text(encoding="utf-8"))


def test_api_keeps_reported_values_and_source_provenance():
    api = load_api()
    assert len(api["content_hash"]) == 64
    facts = [fact for company in api["companies"] for fact in company["facts"]]
    assert facts
    assert all(isinstance(fact["reported_value"], int) for fact in facts)
    assert all(fact["source_kind"] == "SEC EDGAR Companyfacts / 10-Q" for fact in facts)
    assert all(fact["source_api_url"].startswith("https://data.sec.gov/") for fact in facts)
    assert all("value_usd_billions" not in fact for fact in facts)


def test_space_x_is_visible_without_estimation():
    spacex = next(company for company in load_api()["companies"] if company["id"] == "spacex")
    assert spacex["class"] == "public"
    assert spacex["quantitative_status"] == "public_no_10q_facts_yet"
    assert spacex["facts"] == []
