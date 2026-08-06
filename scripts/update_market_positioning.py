#!/usr/bin/env python3
"""Collect official positioning and semiconductor-sales observations.

The collector is fail-closed: it retains existing observations when a source is
unavailable and never substitutes estimates for missing official values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from market_positioning_core import (
    DataContractError,
    build_derived_observations,
    build_public_api,
    canonical_json_hash,
    html_text_and_links,
    merge_observations,
    parse_jquants_daily_bars,
    parse_jquants_margin_interest,
    parse_kofia_credit_balance,
    parse_kofia_market_funds,
    parse_sia_monthly_sales,
    utc_now_iso,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "market_positioning"
OBSERVATIONS_PATH = DATA_DIR / "observations.json"
STATE_PATH = DATA_DIR / "collection_state.json"
PUBLIC_API_PATH = ROOT / "site" / "public" / "api" / "v1" / "market-positioning" / "index.json"
REGISTRY_PATH = DATA_DIR / "source_registry.json"

JQUANTS_BASE = "https://api.jquants.com/v2"
KOFIA_BASE = "https://apis.data.go.kr/1160100/service/GetKofiaStatisticsInfoService"
SIA_ARCHIVE_URLS = (
    "https://www.semiconductors.org/policies/market-data/",
    "https://www.semiconductors.org/policies/tax/market-data/?type=post",
)
DEFAULT_USER_AGENT = "KAFKA2306 semiconductor-earnings-model market positioning collector"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return
    path.write_text(rendered, encoding="utf-8")


def request_bytes(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
    timeout: int = 30,
) -> tuple[bytes, str]:
    query = urllib.parse.urlencode(params or {})
    target = f"{url}?{query}" if query else url
    request_headers = {"User-Agent": DEFAULT_USER_AGENT, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(target, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), response.geturl()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"request failed after {retries} attempts: {target}: {last_error}")


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    raw, final_url = request_bytes(url, params=params, headers=headers)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise DataContractError(f"expected JSON object from {final_url}")
    return payload, final_url


def jquants_paginated(
    path: str, *, api_key: str, params: dict[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    query = dict(params)
    final_url = f"{JQUANTS_BASE}{path}"
    while True:
        payload, final_url = request_json(
            f"{JQUANTS_BASE}{path}",
            params=query,
            headers={"x-api-key": api_key},
        )
        batch = payload.get("data")
        if isinstance(batch, list):
            records.extend(item for item in batch if isinstance(item, dict))
        pagination_key = payload.get("pagination_key")
        if not pagination_key:
            break
        query["pagination_key"] = pagination_key
    return records, final_url


def collect_jquants(*, fetched_at: str, lookback_days: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    api_key = os.environ.get("JQUANTS_API_KEY", "").strip()
    if not api_key:
        return [], {"status": "disabled_missing_secret", "secret": "JQUANTS_API_KEY"}
    end = date.today()
    start = end - timedelta(days=lookback_days)
    params = {"code": "285A", "from": start.isoformat(), "to": end.isoformat()}
    margin_records, margin_url = jquants_paginated(
        "/markets/margin-interest", api_key=api_key, params=params
    )
    bars_records, bars_url = jquants_paginated(
        "/equities/bars/daily", api_key=api_key, params=params
    )
    observations = parse_jquants_margin_interest(
        margin_records,
        source_url="https://api.jquants.com/v2/markets/margin-interest",
        fetched_at=fetched_at,
    )
    observations.extend(
        parse_jquants_daily_bars(
            bars_records,
            source_url="https://api.jquants.com/v2/equities/bars/daily",
            fetched_at=fetched_at,
        )
    )
    return observations, {
        "status": "ok",
        "records": len(margin_records) + len(bars_records),
        "observations": len(observations),
        "response_urls": [margin_url, bars_url],
    }


def collect_kofia(*, fetched_at: str, rows: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not raw_key:
        return [], {
            "status": "disabled_missing_secret",
            "secret": "DATA_GO_KR_SERVICE_KEY",
        }
    service_key = urllib.parse.unquote(raw_key)
    common = {
        "serviceKey": service_key,
        "resultType": "json",
        "pageNo": 1,
        "numOfRows": rows,
    }
    credit_payload, credit_url = request_json(
        f"{KOFIA_BASE}/getGrantingOfCreditBalanceInfo", params=common
    )
    funds_payload, funds_url = request_json(
        f"{KOFIA_BASE}/getSecuritiesMarketTotalCapitalInfo", params=common
    )
    observations = parse_kofia_credit_balance(
        credit_payload,
        source_url=f"{KOFIA_BASE}/getGrantingOfCreditBalanceInfo",
        fetched_at=fetched_at,
    )
    observations.extend(
        parse_kofia_market_funds(
            funds_payload,
            source_url=f"{KOFIA_BASE}/getSecuritiesMarketTotalCapitalInfo",
            fetched_at=fetched_at,
        )
    )
    return observations, {
        "status": "ok",
        "observations": len(observations),
        "response_urls": [credit_url, funds_url],
    }


def _absolute_link(link: str, base: str) -> str:
    return urllib.parse.urljoin(base, link)


def collect_sia(*, fetched_at: str, max_releases: int = 24) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    archive_errors: list[str] = []
    links: list[str] = []
    for archive_url in SIA_ARCHIVE_URLS:
        try:
            raw, final_url = request_bytes(archive_url)
            _, discovered = html_text_and_links(raw.decode("utf-8", errors="replace"))
            links.extend(
                _absolute_link(link, final_url)
                for link in discovered
                if "global-semiconductor-sales" in link.lower()
            )
        except Exception as exc:
            archive_errors.append(f"{archive_url}: {exc}")
    unique_links = list(dict.fromkeys(links))[:max_releases]
    observations: list[dict[str, Any]] = []
    release_errors: list[str] = []
    for link in unique_links:
        try:
            raw, final_url = request_bytes(link)
            text, _ = html_text_and_links(raw.decode("utf-8", errors="replace"))
            observations.extend(
                parse_sia_monthly_sales(text, source_url=final_url, fetched_at=fetched_at)
            )
        except Exception as exc:
            release_errors.append(f"{link}: {exc}")
    observations = merge_observations([], observations)
    status = "ok" if observations else "error"
    return observations, {
        "status": status,
        "release_links": len(unique_links),
        "observations": len(observations),
        "archive_errors": archive_errors,
        "release_errors": release_errors[:10],
    }


def source_run(name: str, callback: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        observations, state = callback()
        return observations, {"source": name, **state}
    except Exception as exc:
        return [], {"source": name, "status": "error", "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback-days", type=int, default=400)
    parser.add_argument("--kofia-rows", type=int, default=250)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail when a configured authenticated source or the public SIA source errors",
    )
    args = parser.parse_args()

    fetched_at = utc_now_iso()
    existing_payload = load_json(
        OBSERVATIONS_PATH, {"schema_version": "1.0.0", "observations": []}
    )
    existing = existing_payload.get("observations", [])
    if not isinstance(existing, list):
        raise DataContractError("observations.json observations must be a list")

    all_new: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    collectors = (
        (
            "jquants_v2",
            lambda: collect_jquants(
                fetched_at=fetched_at, lookback_days=args.lookback_days
            ),
        ),
        (
            "data_go_kr_kofia",
            lambda: collect_kofia(fetched_at=fetched_at, rows=args.kofia_rows),
        ),
        ("sia_wsts", lambda: collect_sia(fetched_at=fetched_at)),
    )
    for name, callback in collectors:
        observations, state = source_run(name, callback)
        all_new.extend(observations)
        states.append(state)

    existing_source = [
        item for item in existing if item.get("source_id") != "derived_market_positioning"
    ]
    existing_derived = [
        item for item in existing if item.get("source_id") == "derived_market_positioning"
    ]
    source_for_calculation = merge_observations(existing_source, all_new)
    new_derived = build_derived_observations(source_for_calculation, fetched_at=fetched_at)
    derived = merge_observations(existing_derived, new_derived)

    persistable_source = [
        item
        for item in source_for_calculation
        if not str(item.get("source_id", "")).startswith("jquants_v2_")
    ]
    merged = merge_observations(persistable_source, derived)

    payload = {
        "schema_version": "1.0.0",
        "generated_at": fetched_at,
        "source_registry_sha256": canonical_json_hash(load_json(REGISTRY_PATH, {})),
        "observations": merged,
    }
    state_payload = {
        "schema_version": "1.0.0",
        "generated_at": fetched_at,
        "sources": states,
        "new_observations": len(all_new),
        "total_observations": len(merged),
    }
    write_json(OBSERVATIONS_PATH, payload)
    write_json(STATE_PATH, state_payload)
    write_json(PUBLIC_API_PATH, build_public_api(merged, fetched_at))

    errors = [state for state in states if state.get("status") == "error"]
    configured_source_errors = [
        state
        for state in errors
        if state.get("source") == "sia_wsts"
        or (
            state.get("source") == "jquants_v2"
            and os.environ.get("JQUANTS_API_KEY", "").strip()
        )
        or (
            state.get("source") == "data_go_kr_kofia"
            and os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
        )
    ]
    print(json.dumps(state_payload, ensure_ascii=False, indent=2))
    if args.strict and configured_source_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
