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


def test_sandisk_model_has_primary_source_urls() -> None:
    model = load_model()
    sources = model["primary_sources"]

    assert len(sources) >= 2
    assert all(source["publisher"] == "Sandisk Corporation" for source in sources)
    assert all(source["url"].startswith("https://investor.sandisk.com/") for source in sources)
