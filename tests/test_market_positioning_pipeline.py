from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_positioning_core import (  # noqa: E402
    build_derived_observations,
    merge_observations,
    parse_jquants_margin_interest,
    parse_kofia_credit_balance,
    parse_kofia_market_funds,
    parse_sia_monthly_sales,
)

FETCHED_AT = "2026-08-06T03:00:00+00:00"


def _kofia_payload(items):
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"items": {"item": items}},
        }
    }


def test_jquants_margin_ratio_uses_buy_divided_by_sell():
    observations = parse_jquants_margin_interest(
        [
            {
                "Date": "2026-07-31",
                "Code": "285A0",
                "IssType": "2",
                "LongVol": 12_321_600,
                "ShrtVol": 544_600,
                "LongNegVol": 0,
                "LongStdVol": 12_321_600,
                "ShrtNegVol": 0,
                "ShrtStdVol": 544_600,
            }
        ],
        source_url="https://api.jquants.com/v2/markets/margin-interest",
        fetched_at=FETCHED_AT,
    )
    derived = build_derived_observations(observations, fetched_at=FETCHED_AT)
    ratio = next(
        item for item in derived if item["metric"] == "margin_buy_to_sell_ratio"
    )
    assert ratio["entity"] == "JPX:285A"
    assert round(ratio["value"], 2) == 22.63


def test_kofia_credit_and_forced_liquidation_fields_are_kept_in_raw_won():
    credit = parse_kofia_credit_balance(
        _kofia_payload(
            {
                "basDt": "20260803",
                "crdTrFingWhl": "27443853960691",
                "crdTrFingScrs": "21614091173422",
                "crdTrFingKosdaq": "5829762787269",
                "crdTrLndrWhl": "17040486631",
            }
        ),
        source_url="official-credit",
        fetched_at=FETCHED_AT,
    )
    funds = parse_kofia_market_funds(
        _kofia_payload(
            {
                "basDt": "20260803",
                "invrDpsgAmt": "102825552619394",
                "brkTrdUcolMny": "1566321843028",
                "brkTrdUcolMnyVsOppsTrdAmt": "22370737743",
                "ucolMnyVsOppsTrdRlImpt": "1.3",
            }
        ),
        source_url="official-funds",
        fetched_at=FETCHED_AT,
    )
    total_credit = next(
        item for item in credit if item["metric"] == "credit_financing_total_won"
    )
    forced = next(
        item for item in funds if item["metric"] == "forced_liquidation_amount_won"
    )
    assert total_credit["value"] == 27_443_853_960_691
    assert forced["value"] == 22_370_737_743
    assert forced["unit"] == "KRW"


def test_sia_monthly_release_parser_requires_explicit_month_year_and_value():
    observations = parse_sia_monthly_sales(
        "The Semiconductor Industry Association announced global semiconductor sales "
        "were $120.6 billion during the month of May 2026. Other forecasts are excluded.",
        source_url="https://www.semiconductors.org/example",
        fetched_at=FETCHED_AT,
    )
    assert observations[0]["observed_date"] == "2026-05-01"
    assert observations[0]["value"] == 120.6


def test_merge_is_idempotent_and_new_record_replaces_same_source_key():
    old = {
        "source_id": "x",
        "entity": "e",
        "metric": "m",
        "observed_date": "2026-01-01",
        "value": 1,
    }
    new = {**old, "value": 2}
    merged = merge_observations([old], [new, new])
    assert len(merged) == 1
    assert merged[0]["value"] == 2


def test_derived_korea_credit_ratio_and_drawdown_are_point_in_time():
    rows = []
    for day, credit, deposits in (
        ("2026-01-01", 100, 200),
        ("2026-01-02", 120, 240),
        ("2026-01-03", 90, 180),
    ):
        rows.extend(
            [
                {
                    "source_id": "credit",
                    "entity": "KR:equity_market",
                    "metric": "credit_financing_total_won",
                    "observed_date": day,
                    "value": credit,
                },
                {
                    "source_id": "deposit",
                    "entity": "KR:equity_market",
                    "metric": "investor_deposits_won",
                    "observed_date": day,
                    "value": deposits,
                },
            ]
        )
    derived = build_derived_observations(rows, fetched_at=FETCHED_AT)
    ratios = [
        item
        for item in derived
        if item["metric"] == "credit_to_investor_deposits_ratio"
    ]
    drawdowns = [
        item
        for item in derived
        if item["metric"] == "credit_drawdown_from_60_observation_peak_pct"
    ]
    assert [item["value"] for item in ratios] == [0.5, 0.5, 0.5]
    assert drawdowns[-1]["value"] == 25.0


def test_jquants_price_and_margin_load_are_persistable_as_derived_only():
    source = parse_jquants_margin_interest(
        [
            {
                "Date": "2026-01-09",
                "Code": "285A0",
                "LongVol": 200,
                "ShrtVol": 20,
            },
            {
                "Date": "2026-01-16",
                "Code": "285A0",
                "LongVol": 220,
                "ShrtVol": 20,
            },
        ],
        source_url="margin",
        fetched_at=FETCHED_AT,
    )
    from market_positioning_core import parse_jquants_daily_bars

    source.extend(
        parse_jquants_daily_bars(
            [
                {"Date": "2026-01-05", "Code": "285A0", "C": 100, "Vo": 100},
                {"Date": "2026-01-06", "Code": "285A0", "C": 110, "Vo": 100},
                {"Date": "2026-01-16", "Code": "285A0", "C": 120, "Vo": 100},
            ],
            source_url="bars",
            fetched_at=FETCHED_AT,
        )
    )
    derived = build_derived_observations(source, fetched_at=FETCHED_AT)
    metrics = {item["metric"]: item for item in derived}
    assert metrics["margin_long_wow_pct"]["value"] == 10.0
    assert metrics["margin_long_to_20_observation_volume_days"]["value"] == 2.2
    close_indices = [
        item["value"]
        for item in derived
        if item["metric"] == "calendar_year_close_index_base100"
    ]
    assert close_indices == [100.0, 110.0, 120.0]
