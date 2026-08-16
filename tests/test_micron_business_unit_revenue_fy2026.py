from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
FINANCIAL_DB = ROOT / "site/public/api/v3/financial-database/index.json"

EXPECTED = {
    ("2025-11-27", "Cloud Memory Business Unit"): 5_284_000_000,
    ("2025-11-27", "Core Data Center Business Unit"): 2_379_000_000,
    ("2025-11-27", "Mobile and Client Business Unit"): 4_255_000_000,
    ("2025-11-27", "Automotive and Embedded Business Unit"): 1_720_000_000,
    ("2026-02-26", "Cloud Memory Business Unit"): 7_749_000_000,
    ("2026-02-26", "Core Data Center Business Unit"): 5_687_000_000,
    ("2026-02-26", "Mobile and Client Business Unit"): 7_711_000_000,
    ("2026-02-26", "Automotive and Embedded Business Unit"): 2_708_000_000,
    ("2026-05-28", "Cloud Memory Business Unit"): 13_769_000_000,
    ("2026-05-28", "Core Data Center Business Unit"): 11_524_000_000,
    ("2026-05-28", "Mobile and Client Business Unit"): 11_521_000_000,
    ("2026-05-28", "Automotive and Embedded Business Unit"): 4_634_000_000,
}


def test_micron_fy2026_business_unit_revenue_chain_is_complete() -> None:
    payload = json.loads(FINANCIAL_DB.read_text(encoding="utf-8"))
    rows = {
        (row["period_end"], row["segment"]): row
        for row in payload["observations"]
        if row.get("entity_id") == "micron"
        and row.get("concept_id") == "revenue"
        and row.get("scope") == "segment"
        and row.get("segment") in {segment for _, segment in EXPECTED}
        and row.get("period_end") in {period for period, _ in EXPECTED}
    }

    assert set(rows) == set(EXPECTED)
    for key, expected_value in EXPECTED.items():
        row = rows[key]
        assert row["value"] == expected_value
        assert row["unit"] == "USD"
        assert row["value_type"] == "actual"
        assert row["fiscal_year"] == 2026
        assert row["fiscal_period"] == {
            "2025-11-27": "Q1",
            "2026-02-26": "Q2",
            "2026-05-28": "Q3",
        }[row["period_end"]]
        assert row["source_url"].startswith("https://")
        assert row["reported_text"]
