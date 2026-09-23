from __future__ import annotations

from scripts.factor_inputs import (
    build_factor_panel,
    entity_yahoo_symbols,
    factor_signature,
    visible_date,
)
from scripts.factor_lab import (
    attach_forward_returns,
    build_factor_lab,
    pearson,
    quantile_labels,
    spearman,
)


def _prices() -> list[dict]:
    rows = []
    for entity, multipliers in [
        ("A", [1.00, 1.10, 1.20, 1.30, 1.40]),
        ("B", [1.00, 1.05, 1.10, 1.15, 1.20]),
        ("C", [1.00, 0.98, 0.96, 0.94, 0.92]),
    ]:
        for day, multiplier in zip(
            ["2025-01-02", "2025-02-03", "2025-04-03", "2025-07-03", "2026-01-05"],
            multipliers,
            strict=True,
        ):
            rows.append({"entity_id": entity, "date": day, "close": 100 * multiplier})
    return rows


def _factors() -> list[dict]:
    return [
        {
            "entity_id": "A",
            "factor_name": "quality",
            "as_of": "2025-01-01",
            "value": 3.0,
            "evidence_ids": ["a"],
        },
        {
            "entity_id": "B",
            "factor_name": "quality",
            "as_of": "2025-01-01",
            "value": 2.0,
            "evidence_ids": ["b"],
        },
        {
            "entity_id": "C",
            "factor_name": "quality",
            "as_of": "2025-01-01",
            "value": 1.0,
            "evidence_ids": ["c"],
        },
    ]


def _financial() -> dict:
    return {
        "entities": [
            {"id": "US:MU", "ticker": "MU"},
            {"id": "JP:3436", "ticker": "3436"},
            {"id": "kioxia-holdings", "ticker": "285A", "exchange": "TSE Prime"},
            {"id": "KR:000660", "ticker": "000660"},
            {"id": "sk-hynix", "ticker": "000660", "exchange": "Korea Exchange"},
            {"id": "samsung-electronics", "ticker": "005930", "exchange": "Korea Exchange"},
        ],
        "observations": [
            {
                "id": "a1",
                "entity_id": "US:MU",
                "concept_id": "revenue",
                "value_type": "actual",
                "value": 10.0,
                "unit": "USD",
                "period_type": "quarter",
                "scope": "consolidated",
                "segment": None,
                "source_tier": "primary_regulatory",
                "filed_at": "2025-02-10",
                "as_of": "2024-12-31",
            },
            {
                "id": "a2",
                "entity_id": "US:MU",
                "concept_id": "revenue",
                "value_type": "actual",
                "value": 12.0,
                "unit": "USD",
                "period_type": "quarter",
                "scope": "consolidated",
                "segment": None,
                "source_tier": "primary_regulatory",
                "filed_at": "2025-05-10",
                "as_of": "2025-03-31",
            },
            {
                "id": "b1",
                "entity_id": "JP:3436",
                "concept_id": "revenue",
                "value_type": "actual",
                "value": 20.0,
                "unit": "JPY",
                "period_type": "annual",
                "scope": "consolidated",
                "segment": None,
                "source_tier": "primary_regulatory",
                "filed_at": "2025-03-01",
                "as_of": "2024-12-31",
            },
        ],
    }


def test_correlations_and_ties() -> None:
    assert pearson([1, 2, 3], [2, 4, 6]) == 1.0
    assert round(spearman([1, 1, 3], [3, 3, 9]), 12) == 1.0


def test_quantile_labels_are_monotonic() -> None:
    assert quantile_labels([40, 10, 30, 20], 4) == [4, 1, 3, 2]


def test_forward_return_uses_start_price_as_denominator() -> None:
    rows = attach_forward_returns(_factors(), _prices(), horizons={"1m": 30})
    a = next(row for row in rows if row["entity_id"] == "A")
    assert round(a["forward_returns"]["1m"], 6) == 0.10


def test_factor_lab_emits_rank_ic_quantiles_and_lineage() -> None:
    payload = build_factor_lab(
        _factors(),
        _prices(),
        horizons={"1m": 30},
        bins=3,
        min_cross_section=3,
    )
    result = payload["factor_tests"][0]
    assert payload["schema_version"] == "factor-lab.v1"
    assert result["pooled_rank_ic"] == 1.0
    assert result["rank_ic_mean"] == 1.0
    assert result["quantile_mean_returns"]["3"] > result["quantile_mean_returns"]["1"]
    assert result["top_minus_bottom"] > 0
    observation = next(row for row in payload["factor_observations"] if row["entity_id"] == "A")
    assert observation["evidence_ids"] == ["a"]
    assert payload["content_hash"]


def test_visible_date_does_not_use_period_end_for_regulatory_fact() -> None:
    assert (
        visible_date(
            {
                "source_tier": "primary_regulatory",
                "filed_at": "2026-02-10",
                "as_of": "2025-12-31",
            }
        )
        == "2026-02-10"
    )
    assert (
        visible_date(
            {
                "source_tier": "primary_regulatory",
                "filed_at": None,
                "observed_at": None,
                "as_of": "2025-12-31",
            }
        )
        is None
    )


def test_factor_signature_preserves_semantic_boundaries() -> None:
    usd = {
        "value_type": "actual",
        "concept_id": "revenue",
        "unit": "USD",
        "period_type": "quarter",
        "scope": "consolidated",
        "segment": None,
    }
    jpy = {**usd, "unit": "JPY"}
    assert factor_signature(usd) != factor_signature(jpy)


def test_month_end_panel_carries_only_already_known_values() -> None:
    rows = build_factor_panel(_financial(), max_age_days=550)
    micron = [row for row in rows if row["entity_id"] == "US:MU"]
    february = next(row for row in micron if row["as_of"] == "2025-02-28")
    may = next(row for row in micron if row["as_of"] == "2025-05-31")
    assert february["value"] == 10.0
    assert february["known_at"] == "2025-02-10"
    assert may["value"] == 12.0
    assert may["known_at"] == "2025-05-10"


def test_yahoo_symbol_mapping_is_explicit_by_market() -> None:
    assert entity_yahoo_symbols(_financial()) == {
        "US:MU": "MU",
        "JP:3436": "3436.T",
        "kioxia-holdings": "285A.T",
        "KR:000660": "000660.KS",
        "sk-hynix": "000660.KS",
        "samsung-electronics": "005930.KS",
    }