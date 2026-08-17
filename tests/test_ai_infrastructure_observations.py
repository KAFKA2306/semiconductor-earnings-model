import json
from pathlib import Path


REQUIRED = {"id", "entity", "concept_id", "value_type", "value", "unit", "period_end", "as_of", "source_tier", "source_url"}


def test_ai_infrastructure_observations_keep_value_type_and_primary_source():
    path = Path(__file__).resolve().parents[1] / "data" / "financial_db" / "ai_infrastructure_observations.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["observations"]
    assert rows
    ids = set()
    for row in rows:
        assert REQUIRED <= row.keys()
        assert row["id"] not in ids
        ids.add(row["id"])
        assert row["value_type"] in {"actual", "company_guidance"}
        assert row["source_tier"] == "primary_company"
        assert row["source_url"].startswith("https://")
    assert any(row["value_type"] == "actual" for row in rows)
    assert any(row["value_type"] == "company_guidance" for row in rows)


def test_micron_q3_data_center_ssd_revenue_preserves_reported_lower_bound():
    path = Path(__file__).resolve().parents[1] / "data" / "financial_db" / "ai_infrastructure_observations.json"
    rows = json.loads(path.read_text(encoding="utf-8"))["observations"]
    row = next(item for item in rows if item["id"] == "micron:2026-05-28:data-center-ssd-revenue:actual")
    assert row["entity"] == "Micron Technology, Inc."
    assert row["ticker"] == "MU"
    assert row["concept_id"] == "data_center_ssd_revenue"
    assert row["value"] == 5_000_000_000
    assert row["qualifier"] == "greater_than"
    assert row["unit"] == "USD"
    assert row["period_end"] == "2026-05-28"
    assert row["fiscal_year"] == 2026
    assert row["fiscal_period"] == "Q3"
    assert row["as_of"] == "2026-06-24"
