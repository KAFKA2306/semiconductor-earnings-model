import json
from pathlib import Path

import pytest

from scripts.collect_ai_infrastructure_sec import CONCEPT, CONCEPT_ID, quarterly_capex
from scripts.build_ai_infrastructure_view import validate_comparability


REQUIRED = {"id", "entity", "concept_id", "value_type", "value", "unit", "period_end", "as_of", "source_tier", "source_url"}


def manual_rows():
    path = Path(__file__).resolve().parents[1] / "data" / "financial_db" / "ai_infrastructure_observations.json"
    return json.loads(path.read_text(encoding="utf-8"))["observations"]


def test_ai_infrastructure_observations_keep_value_type_and_primary_source():
    rows = manual_rows()
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
    rows = manual_rows()
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


def test_microsoft_total_capex_actual_and_guidance_use_same_company_definition():
    rows = manual_rows()
    q3 = next(item for item in rows if item["id"] == "microsoft:2026-03-31:capital-expenditures:actual")
    q4_guide = next(item for item in rows if item["id"] == "microsoft:2026-06-30:capital-expenditures:guidance")
    q4_actual = next(item for item in rows if item["id"] == "microsoft:2026-06-30:capital-expenditures:actual")
    q1_guide = next(item for item in rows if item["id"] == "microsoft:2026-09-30:capital-expenditures:guidance")

    assert q3["value"] == 31_900_000_000
    assert q4_guide["value"] == 40_000_000_000 and q4_guide["qualifier"] == "greater_than"
    assert q4_actual["value"] == 41_000_000_000
    assert q1_guide["value"] == 50_000_000_000 and q1_guide["qualifier"] == "greater_than"
    assert {row["concept_id"] for row in (q3, q4_guide, q4_actual, q1_guide)} == {"capital_expenditures"}
    assert all(row["source_tier"] == "primary_company" for row in (q3, q4_guide, q4_actual, q1_guide))
    assert q4_actual["definition"] == q3["definition"]


def test_sec_cumulative_cash_ppe_is_reconstructed_into_quarters_with_lineage():
    def fact(fp, end, val, filed, form):
        return {
            "start": "2025-01-01",
            "end": end,
            "val": val,
            "accn": f"0000000000-25-{len(end):06d}",
            "filed": filed,
            "form": form,
            "fy": 2025,
            "fp": fp,
        }

    payload = {
        "facts": {
            "us-gaap": {
                CONCEPT: {
                    "units": {
                        "USD": [
                            fact("Q1", "2025-03-31", 100, "2025-04-30", "10-Q"),
                            fact("Q2", "2025-06-30", 250, "2025-07-30", "10-Q"),
                            fact("Q3", "2025-09-30", 400, "2025-10-30", "10-Q"),
                            fact("FY", "2025-12-31", 600, "2026-02-15", "10-K"),
                        ]
                    }
                }
            }
        }
    }
    rows = quarterly_capex(payload, "TEST", "Test Corp", 123, "a" * 64)
    assert [row["value"] for row in rows] == [100, 150, 150, 200]
    assert [row["fiscal_period"] for row in rows] == ["Q1", "Q2", "Q3", "Q4"]
    assert rows[1]["formula"] == "Q2 year-to-date - Q1 year-to-date"
    assert len(rows[1]["source_facts"]) == 2
    assert rows[-1]["source_tier"] == "primary_regulatory"
    assert all(row["concept_id"] == CONCEPT_ID for row in rows)
    assert all("cash paid" in row["definition"].lower() for row in rows)


def test_cash_ppe_cannot_be_labeled_total_capex():
    invalid = [{
        "id": "bad",
        "concept_id": "capital_expenditures",
        "sec_concept": CONCEPT,
        "source_tier": "primary_regulatory",
    }]
    with pytest.raises(ValueError, match="cash PP&E"):
        validate_comparability(invalid)
