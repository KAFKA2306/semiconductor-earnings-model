from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
FINANCIAL_DB = ROOT / "site/public/api/v3/financial-database/index.json"

EXPECTED = {
    ("2025-11-27", "Cloud Memory Business Unit"): 0.55,
    ("2025-11-27", "Core Data Center Business Unit"): 0.37,
    ("2025-11-27", "Mobile and Client Business Unit"): 0.47,
    ("2025-11-27", "Automotive and Embedded Business Unit"): 0.36,
    ("2026-02-26", "Cloud Memory Business Unit"): 0.66,
    ("2026-02-26", "Core Data Center Business Unit"): 0.67,
    ("2026-02-26", "Mobile and Client Business Unit"): 0.76,
    ("2026-02-26", "Automotive and Embedded Business Unit"): 0.62,
    ("2026-05-28", "Cloud Memory Business Unit"): 0.78,
    ("2026-05-28", "Core Data Center Business Unit"): 0.83,
    ("2026-05-28", "Mobile and Client Business Unit"): 0.86,
    ("2026-05-28", "Automotive and Embedded Business Unit"): 0.75,
}


def test_micron_fy2026_business_unit_operating_margin_chain_is_complete() -> None:
    payload = json.loads(FINANCIAL_DB.read_text(encoding="utf-8"))
    rows = {
        (row["period_end"], row["segment"]): row
        for row in payload["observations"]
        if row.get("entity_id") == "micron"
        and row.get("concept_id") == "operating_margin"
        and row.get("scope") == "segment"
        and row.get("segment") in {segment for _, segment in EXPECTED}
        and row.get("period_end") in {period for period, _ in EXPECTED}
    }

    assert set(rows) == set(EXPECTED)
    for key, expected_value in EXPECTED.items():
        row = rows[key]
        assert row["value"] == expected_value
        assert row["unit"] == "ratio"
        assert row["value_type"] == "actual"
        assert row["fiscal_year"] == 2026
        assert row["fiscal_period"] == {
            "2025-11-27": "Q1",
            "2026-02-26": "Q2",
            "2026-05-28": "Q3",
        }[row["period_end"]]
        assert row["source_tier"] == "primary_company"
        assert row["source_url"].startswith("https://investors.micron.com/")
        assert row["reported_text"]
