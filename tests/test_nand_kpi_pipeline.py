from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parents[1]
CORE_PATH = ROOT / "scripts/nand_kpi_core.py"
BUILDER_PATH = ROOT / "scripts/build_financial_database_with_nand.py"
LEDGER_PATH = ROOT / "data/financial_db/nand_kpi_observations.json"
FINANCIAL_JSON = ROOT / "site/public/api/v3/financial-database/index.json"
FINANCIAL_DB = ROOT / "site/public/api/v3/financial-database/financial.db"

core_spec = importlib.util.spec_from_file_location("nand_kpi_core", CORE_PATH)
core = importlib.util.module_from_spec(core_spec)
assert core_spec.loader
core_spec.loader.exec_module(core)

builder_spec = importlib.util.spec_from_file_location("nand_builder", BUILDER_PATH)
builder = importlib.util.module_from_spec(builder_spec)
assert builder_spec.loader
builder_spec.loader.exec_module(builder)


def test_qualitative_percentage_policy_is_deterministic() -> None:
    assert core.percentage_interval("mid-single-digit", direction="increase") == (0.04, 0.06)
    assert core.percentage_interval("mid-single-digit", direction="decline") == (-0.06, -0.04)
    assert core.percentage_interval("mid-to-high-single-digit", direction="increase") == (0.04, 0.09)
    assert core.percentage_interval("mid-teens", direction="increase") == (0.14, 0.16)
    assert core.percentage_interval("high-70s", direction="increase") == (0.77, 0.79)
    assert core.percentage_interval("mid-80s", direction="increase") == (0.84, 0.86)


def test_micron_parser_preserves_reported_text() -> None:
    text = """
    NAND
    Fiscal Q3 NAND revenue was a record. Bit shipments increased in the mid-single-digit
    percentage range. Prices increased in the mid-80s percentage range, driven by conditions.
    """
    result = core.extract_micron_nand_kpis(text)
    assert (result["bit_shipments"]["value_low"], result["bit_shipments"]["value_high"]) == (0.04, 0.06)
    assert (result["asp"]["value_low"], result["asp"]["value_high"]) == (0.84, 0.86)
    assert "increased" in result["bit_shipments"]["reported_text"]
    assert "increased" in result["asp"]["reported_text"]


def test_four_quarter_yoy_range_is_compounded_not_summed() -> None:
    asp = core.compound_intervals([(0.07, 0.09), (0.14, 0.16), (0.77, 0.79), (0.84, 0.86)])
    bits = core.compound_intervals([(-0.06, -0.04), (0.04, 0.09), (0.01, 0.03), (0.04, 0.06)])
    assert asp == (2.97264464, 3.20969336)
    assert bits == (0.02687104, 0.14245952)


def test_guidance_range_comparison_has_three_states() -> None:
    assert core.compare_intervals((0.10, 0.12), (0.05, 0.08))["result"] == "above"
    assert core.compare_intervals((0.01, 0.03), (0.05, 0.08))["result"] == "below"
    assert core.compare_intervals((0.05, 0.07), (0.06, 0.08))["result"] == "overlap"


def test_seed_ledger_is_source_traceable_and_complete() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    rows = ledger["observations"]
    assert len(rows) >= 8
    assert {row["concept_id"] for row in rows} >= {"nand_asp_change_qoq", "nand_bit_shipments_change_qoq"}
    assert all(row["source_url"].startswith("https://investors.micron.com/") for row in rows if row["entity_id"] == "micron")
    assert all(row.get("reported_text") for row in rows if row["value_type"] == "actual")
    assert all(row.get("normalization_method") == core.BAND_POLICY_ID for row in rows if row["value_type"] == "actual")


def test_generated_database_exposes_nand_comparison_view() -> None:
    payload = json.loads(FINANCIAL_JSON.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "financial-database.v3"
    assert "nand-operating-kpis.v1" in payload["extensions"]
    assert payload["audit"]["status"] == "PASS"
    assert payload["audit"]["counts"]["nand_actual_observations"] >= 8
    assert payload["audit"]["counts"]["nand_derived_observations"] >= 2
    view = payload["views"]["nand_kpi_comparisons"]
    latest_micron = max((item for item in view if item["entity_id"] == "micron"), key=lambda item: item["period_end"])
    assert latest_micron["asp"]["qoq_actual"]
    assert latest_micron["asp"]["yoy_derived"]
    assert latest_micron["asp"]["guidance_status"] == "not_disclosed_or_not_comparable"
    entity_ids = {row["id"] for row in payload["entities"]}
    assert {"kioxia-holdings", "sandisk", "samsung-electronics", "sk-hynix"} <= entity_ids

    connection = sqlite3.connect(FINANCIAL_DB)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        count = connection.execute(
            "SELECT COUNT(*) FROM observations WHERE concept_id IN ('nand_asp_change_qoq','nand_bit_shipments_change_qoq','nand_asp_change_yoy','nand_bit_shipments_change_yoy')"
        ).fetchone()[0]
        assert count >= 10
    finally:
        connection.close()
