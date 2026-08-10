from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "build_financial_analysis_projection.py"
SPEC = importlib.util.spec_from_file_location("financial_analysis", MODULE)
assert SPEC and SPEC.loader
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def test_financial_analysis_formulas_and_basis_gate() -> None:
    source = {"provider":"EDINET DB","source_endpoint":"/v1/companies/E00000/financials","request_fingerprint":"abc","response_sha256":"def","fetched_at":"2026-08-10T00:00:00Z","records":[
        {"fiscal_year":2024,"accounting_standard":"IFRS","basis":"standalone","revenue":100.0,"operating_income":20.0,"net_income":10.0,"eps":1.0,"cf_operating":30.0,"cf_investing":-10.0},
        {"fiscal_year":2025,"accounting_standard":"IFRS","basis":"consolidated","revenue":120.0,"operating_income":24.0,"net_income":12.0,"eps":2.0,"cf_operating":40.0,"cf_investing":-15.0},
        {"fiscal_year":2026,"accounting_standard":"IFRS","basis":"consolidated","revenue":150.0,"operating_income":45.0,"net_income":15.0,"eps":3.0,"cf_operating":50.0,"cf_investing":-20.0},
    ]}
    rows = analysis.build(source, "fixture.json")["records"]
    assert rows[1]["revenue_yoy"] is None
    assert rows[1]["revenue_yoy_null_reason"] == "no_comparable_prior_period"
    assert rows[2]["revenue_yoy"] == 0.25
    assert rows[2]["operating_margin"] == 0.3
    assert rows[2]["net_margin"] == 0.1
    assert rows[2]["free_cash_flow"] == 30.0
