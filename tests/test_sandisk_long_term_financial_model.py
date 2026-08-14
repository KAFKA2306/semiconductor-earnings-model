from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "data" / "financial_analysis" / "sandisk-long-term-financial-model-2026.json"


def load_model() -> dict:
    return json.loads(MODEL.read_text(encoding="utf-8"))


def test_sandisk_issuer_guidance_values_are_canonical() -> None:
    model = load_model()
    financial = model["long_term_financial_model"]

    assert model["value_type"] == "issuer_guidance"
    assert financial["period"] == "FY2028-FY2030"
    assert financial["revenue_growth"]["value"] == "mid-to-high teens"
    assert financial["revenue_growth"]["numeric_range"] is None
    assert financial["non_gaap_gross_margin"]["approx_value"] == 80
    assert financial["non_gaap_operating_margin"]["approx_value"] == 75
    assert financial["operating_expense"]["approx_value"] == 5
    assert financial["adjusted_free_cash_flow_margin"]["approx_value"] == 50
    assert financial["excess_cash_return_after_business_investment"]["value"] == 100


def test_sandisk_growth_metrics_are_dimensioned_and_not_interchangeable() -> None:
    model = load_model()
    financial = model["long_term_financial_model"]
    revenue = financial["revenue_growth"]
    bits = financial["bit_growth_relation"]

    assert revenue["metric"] == "revenue_growth"
    assert revenue["scope"] == "Sandisk consolidated revenue"
    assert revenue["unit"] == "percent"
    assert revenue["period"] == "FY2028-FY2030"
    assert revenue["rate_basis"] == "issuer_long_term_model_target"
    assert revenue["comparison_basis"] is None
    assert "consistent with bit growth" in revenue["source_wording"]

    assert bits["metric"] == "bit_growth"
    assert bits["scope"] == "unspecified_in_canonical_source_capture"
    assert bits["rate_basis"] == "unspecified_in_canonical_source_capture"
    assert bits["numeric_value"] is None
    assert bits["relation_to_revenue_growth"] == "consistent_with"

    required = set(model["growth_metric_contract"]["required_dimensions"])
    assert {"metric", "scope", "unit", "period", "rate_basis", "value_type"}.issubset(required)


def test_sandisk_actual_growth_is_not_long_term_target() -> None:
    model = load_model()
    actual = model["actual_growth_context"]["q3_fy2026"]
    target = model["long_term_financial_model"]["revenue_growth"]

    assert actual["revenue_usd_billion"] == 5.95
    assert actual["revenue_qoq_growth_pct"] == 97
    assert actual["revenue_yoy_growth_pct"] == 251
    assert "higher pricing" in actual["driver_disclosure"]
    assert actual["period"] != target["period"]
    assert target["rate_basis"] != "qoq"
    assert target["rate_basis"] != "yoy"


def test_sandisk_image_contract_blocks_unsourced_model_values() -> None:
    model = load_model()
    blocked = set(model["image_generation_contract"]["do_not_infer"])

    assert "annual revenue values" in blocked
    assert "annual free cash flow values" in blocked
    assert "WACC" in blocked
    assert "terminal growth rate" in blocked
    assert "enterprise value" in blocked
    assert "price target" in blocked
    assert "numeric endpoints for mid-to-high teens revenue growth" in blocked
    assert "YoY or CAGR basis for the long-term revenue growth target unless explicitly stated by the issuer" in blocked
    assert "scope or numeric value of bit growth from the phrase consistent with bit growth" in blocked
    assert "revenue growth attribution to bit growth alone" in blocked


def test_sandisk_model_has_primary_source_urls() -> None:
    model = load_model()
    sources = model["primary_sources"]

    assert len(sources) >= 4
    assert any(source["publisher"] == "Sandisk Corporation" for source in sources)
    assert any(source["publisher"] == "U.S. Securities and Exchange Commission" for source in sources)
    assert all(source["url"].startswith("https://") for source in sources)
