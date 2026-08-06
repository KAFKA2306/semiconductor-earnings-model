"""Normalization and point-in-time calculations for market positioning data."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from statistics import fmean
from typing import Any

SCHEMA_VERSION = "1.0.0"


class DataContractError(ValueError):
    pass


class _HtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self.links.extend(v for k, v in attrs if k.lower() == "href" and v)

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.text.append(value)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    raise DataContractError(f"unsupported date: {text!r}")


def _first(record: Mapping[str, Any], names: Sequence[str]) -> float | None:
    for name in names:
        value = as_number(record.get(name))
        if value is not None:
            return value
    return None


def _obs(
    source: str,
    entity: str,
    metric: str,
    day: str,
    value: float | int,
    unit: str,
    url: str,
    fetched_at: str,
    raw: Any,
    frequency: str,
    quality: str = "reported",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": source,
        "entity": entity,
        "metric": metric,
        "observed_date": normalize_date(day),
        "value": value,
        "unit": unit,
        "frequency": frequency,
        "quality": quality,
        "source_url": url,
        "fetched_at": fetched_at,
        "raw_sha256": canonical_json_hash(raw),
    }


def _jpx_entity(code: Any) -> str:
    value = str(code or "285A")
    return f"JPX:{value[:-1] if len(value) == 5 and value.endswith('0') else value}"


def parse_jquants_margin_interest(
    records: Sequence[Mapping[str, Any]], *, source_url: str, fetched_at: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        long_value = _first(record, ("LongVol", "LongMarginTradeVolume"))
        short_value = _first(record, ("ShrtVol", "ShortMarginTradeVolume"))
        if long_value is None or short_value is None:
            raise DataContractError("J-Quants margin record lacks LongVol or ShrtVol")
        entity, day = _jpx_entity(record.get("Code")), normalize_date(record.get("Date"))
        out.extend(
            [
                _obs("jquants_v2_margin_interest", entity, "margin_long_balance_shares", day, int(long_value), "shares", source_url, fetched_at, record, "weekly"),
                _obs("jquants_v2_margin_interest", entity, "margin_short_balance_shares", day, int(short_value), "shares", source_url, fetched_at, record, "weekly"),
            ]
        )
    return out


def parse_jquants_daily_bars(
    records: Sequence[Mapping[str, Any]], *, source_url: str, fetched_at: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        entity, day = _jpx_entity(record.get("Code")), normalize_date(record.get("Date"))
        for metric, aliases, unit in (
            ("close_price", ("AdjC", "C", "Close", "AdjustmentClose"), "JPY_per_share"),
            ("trading_volume_shares", ("AdjVo", "Vo", "Volume", "AdjustmentVolume"), "shares"),
        ):
            value = _first(record, aliases)
            if value is not None:
                out.append(_obs("jquants_v2_daily_bars", entity, metric, day, int(value) if unit == "shares" else value, unit, source_url, fetched_at, record, "daily"))
    return out


def _kofia_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    response = payload.get("response")
    if not isinstance(response, Mapping):
        raise DataContractError("KOFIA response envelope is missing")
    header = response.get("header")
    if isinstance(header, Mapping) and str(header.get("resultCode") or "") not in {"", "0", "00"}:
        raise DataContractError(f"KOFIA error: {header.get('resultMsg')}")
    body = response.get("body") if isinstance(response, Mapping) else None
    items = body.get("items") if isinstance(body, Mapping) else None
    rows = items.get("item") if isinstance(items, Mapping) else None
    if isinstance(rows, Mapping):
        return [rows]
    return [row for row in rows or [] if isinstance(row, Mapping)]


def _parse_kofia(
    payload: Mapping[str, Any], fields: Mapping[str, tuple[str, str]], source: str, url: str, fetched_at: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _kofia_rows(payload):
        day = normalize_date(row.get("basDt"))
        for field, (metric, unit) in fields.items():
            value = as_number(row.get(field))
            if value is not None:
                out.append(_obs(source, "KR:equity_market", metric, day, int(value) if unit == "KRW" else value, unit, url, fetched_at, row, "daily"))
    return out


def parse_kofia_credit_balance(payload: Mapping[str, Any], *, source_url: str, fetched_at: str) -> list[dict[str, Any]]:
    return _parse_kofia(payload, {
        "crdTrFingWhl": ("credit_financing_total_won", "KRW"),
        "crdTrFingScrs": ("credit_financing_kospi_won", "KRW"),
        "crdTrFingKosdaq": ("credit_financing_kosdaq_won", "KRW"),
        "crdTrLndrWhl": ("credit_lending_total_won", "KRW"),
    }, "data_go_kr_kofia_credit", source_url, fetched_at)


def parse_kofia_market_funds(payload: Mapping[str, Any], *, source_url: str, fetched_at: str) -> list[dict[str, Any]]:
    return _parse_kofia(payload, {
        "invrDpsgAmt": ("investor_deposits_won", "KRW"),
        "brkTrdUcolMny": ("unsettled_margin_amount_won", "KRW"),
        "brkTrdUcolMnyVsOppsTrdAmt": ("forced_liquidation_amount_won", "KRW"),
        "ucolMnyVsOppsTrdRlImpt": ("forced_liquidation_ratio_pct", "percent"),
    }, "data_go_kr_kofia_market_funds", source_url, fetched_at)


_MONTHS = {month.lower(): index for index, month in enumerate(
    "January February March April May June July August September October November December".split(), 1
)}
_SIA = re.compile(
    r"(?:global|worldwide)\s+(?:semiconductor(?:\s+industry)?\s+)?sales[^.]{0,100}?"
    r"(?:were|was|totaled|reached)\s+\$?(?P<value>[\d,.]+)\s+billion[^.]{0,100}?"
    r"(?:during|in|for)\s+(?:the\s+month\s+of\s+)?(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<year>20\d{2})",
    re.IGNORECASE,
)


def html_text_and_links(html: str) -> tuple[str, list[str]]:
    parser = _HtmlParser()
    parser.feed(html)
    return " ".join(parser.text), parser.links


def parse_sia_monthly_sales(text: str, *, source_url: str, fetched_at: str) -> list[dict[str, Any]]:
    for sentence in re.split(r"(?<=[.!?])\s+", " ".join(text.replace("\xa0", " ").split())):
        match = _SIA.search(sentence)
        if not match:
            continue
        value = as_number(match.group("value"))
        if value is None or not 1 <= value <= 1000:
            continue
        day = date(int(match.group("year")), _MONTHS[match.group("month").lower()], 1).isoformat()
        return [_obs("sia_wsts_monthly_sales", "WORLD:semiconductors", "monthly_sales_usd_bn_3mma", day, value, "USD_billion", source_url, fetched_at, {"sentence": sentence}, "monthly")]
    raise DataContractError("SIA release lacks an unambiguous monthly sales fact")


def observation_key(item: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(item[key]) for key in ("source_id", "entity", "metric", "observed_date"))  # type: ignore[return-value]


def merge_observations(existing: Iterable[Mapping[str, Any]], new: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged = {observation_key(item): dict(item) for item in [*existing, *new]}
    return sorted(merged.values(), key=lambda item: (item["entity"], item["metric"], item["observed_date"], item["source_id"]))


def _series(observations: Sequence[Mapping[str, Any]], entity: str, metric: str) -> list[tuple[str, float]]:
    out = [(normalize_date(item["observed_date"]), value) for item in observations if item.get("entity") == entity and item.get("metric") == metric and (value := as_number(item.get("value"))) is not None]
    return sorted(out)


def _derived(entity: str, metric: str, day: str, value: float, unit: str, fetched_at: str, raw: Any, frequency: str, url: str) -> dict[str, Any]:
    return _obs("derived_market_positioning", entity, metric, day, round(value, 8), unit, url, fetched_at, raw, frequency, "derived")


def build_derived_observations(observations: Sequence[Mapping[str, Any]], *, fetched_at: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    entities = sorted({str(item.get("entity")) for item in observations if str(item.get("entity", "")).startswith("JPX:")})
    for entity in entities:
        longs = _series(observations, entity, "margin_long_balance_shares")
        shorts = dict(_series(observations, entity, "margin_short_balance_shares"))
        volumes = _series(observations, entity, "trading_volume_shares")
        for index, (day, long_value) in enumerate(longs):
            short_value = shorts.get(day)
            if short_value and short_value > 0:
                out.append(_derived(entity, "margin_buy_to_sell_ratio", day, long_value / short_value, "ratio", fetched_at, {"long": long_value, "short": short_value}, "weekly", "derived://jquants_v2_margin_interest"))
            if index and longs[index - 1][1]:
                previous = longs[index - 1][1]
                out.append(_derived(entity, "margin_long_wow_pct", day, (long_value / previous - 1) * 100, "percent", fetched_at, {"current": long_value, "previous": previous}, "weekly", "derived://jquants_v2_margin_interest"))
            window = [value for volume_day, value in volumes if volume_day <= day][-20:]
            if window and fmean(window) > 0:
                out.append(_derived(entity, "margin_long_to_20_observation_volume_days", day, long_value / fmean(window), "trading_days", fetched_at, {"long": long_value, "volume_hash": canonical_json_hash(window)}, "weekly", "derived://jquants_v2"))
        bases: dict[str, float] = {}
        for day, close in _series(observations, entity, "close_price"):
            bases.setdefault(day[:4], close)
            if bases[day[:4]] > 0:
                out.append(_derived(entity, "calendar_year_close_index_base100", day, close / bases[day[:4]] * 100, "index", fetched_at, {"year": day[:4], "close_hash": canonical_json_hash(close), "base_hash": canonical_json_hash(bases[day[:4]])}, "daily", "derived://jquants_v2_daily_bars"))

    credit = dict(_series(observations, "KR:equity_market", "credit_financing_total_won"))
    deposits = dict(_series(observations, "KR:equity_market", "investor_deposits_won"))
    for day in sorted(set(credit) & set(deposits)):
        if deposits[day] > 0:
            out.append(_derived("KR:equity_market", "credit_to_investor_deposits_ratio", day, credit[day] / deposits[day], "ratio", fetched_at, {"credit": credit[day], "deposits": deposits[day]}, "daily", "derived://data_go_kr_kofia"))
    credit_series = sorted(credit.items())
    for index, (day, value) in enumerate(credit_series):
        window = [v for _, v in credit_series[max(0, index - 59): index + 1]]
        if window and max(window) > 0:
            out.append(_derived("KR:equity_market", "credit_drawdown_from_60_observation_peak_pct", day, (1 - value / max(window)) * 100, "percent", fetched_at, {"value": value, "peak": max(window)}, "daily", "derived://data_go_kr_kofia"))
    forced = _series(observations, "KR:equity_market", "forced_liquidation_amount_won")
    for index, (day, _) in enumerate(forced):
        window = [v for _, v in forced[max(0, index - 4): index + 1]]
        out.append(_derived("KR:equity_market", "forced_liquidation_5_observation_average_won", day, fmean(window), "KRW", fetched_at, {"window": window}, "daily", "derived://data_go_kr_kofia"))
    sales = _series(observations, "WORLD:semiconductors", "monthly_sales_usd_bn_3mma")
    for index in range(1, len(sales)):
        day, value = sales[index]
        previous = sales[index - 1][1]
        if previous:
            out.append(_derived("WORLD:semiconductors", "monthly_sales_mom_pct", day, (value / previous - 1) * 100, "percent", fetched_at, {"current": value, "previous": previous}, "monthly", "derived://sia_wsts_monthly_sales"))
    return out


def latest_by_metric(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    latest: dict[str, Mapping[str, Any]] = {}
    for item in observations:
        key = f"{item['entity']}::{item['metric']}"
        if key not in latest or item["observed_date"] > latest[key]["observed_date"]:
            latest[key] = item
    return {key: dict(value) for key, value in sorted(latest.items())}


def build_public_api(observations: Sequence[Mapping[str, Any]], generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "observation_count": len(observations),
        "latest": latest_by_metric(observations),
        "observations": list(observations),
        "methodology_url": "https://github.com/KAFKA2306/semiconductor-earnings-model/blob/main/docs/market-positioning-pipeline.md",
    }
