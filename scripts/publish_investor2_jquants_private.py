#!/usr/bin/env python3
"""Build private-only J-Quants bars/analysis for investor2.

J-Quants rows are never committed to GitHub. The caller must upload the output
only to private storage and verify read-back integrity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

CONTENTS_API = "https://api.github.com/repos/KAFKA2306/investor2/contents/data/market_snapshots"
BARS_ENDPOINT = "https://api.jquants.com/v2/equities/bars/daily"
TERMS_URL = "https://jpx-jquants.com/"
USER_AGENT = "KAFKA2306 investor2 private J-Quants collector"


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def first_number(record: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = number(record.get(name))
        if value is not None:
            return value
    return None


def normalize_bar(record: Mapping[str, Any]) -> dict[str, Any] | None:
    day = str(record.get("Date") or "").strip()
    code = str(record.get("Code") or "").strip()
    close = first_number(record, "AdjC", "C", "AdjustmentClose", "Close")
    if not day or not code or close is None:
        return None
    return {
        "date": day,
        "code": code,
        "open": first_number(record, "AdjO", "O", "AdjustmentOpen", "Open"),
        "high": first_number(record, "AdjH", "H", "AdjustmentHigh", "High"),
        "low": first_number(record, "AdjL", "L", "AdjustmentLow", "Low"),
        "close": close,
        "volume": first_number(record, "AdjVo", "Vo", "AdjustmentVolume", "Volume"),
    }


def analyze_bars(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda row: str(row["date"]))
    closes = [float(row["close"]) for row in ordered]
    if not closes:
        raise ValueError("empty bar series")
    log_returns = [
        math.log(current / previous)
        for previous, current in zip(closes, closes[1:])
        if previous > 0 and current > 0
    ]
    peak = closes[0]
    max_drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        if peak > 0:
            max_drawdown = min(max_drawdown, close / peak - 1)

    def trailing(n: int) -> float | None:
        if len(closes) <= n or closes[-(n + 1)] <= 0:
            return None
        return (closes[-1] / closes[-(n + 1)] - 1) * 100

    volatility = None
    if len(log_returns) >= 2:
        volatility = statistics.stdev(log_returns) * math.sqrt(252) * 100
    return {
        "row_count": len(ordered),
        "first_date": str(ordered[0]["date"]),
        "last_date": str(ordered[-1]["date"]),
        "first_adjusted_close": closes[0],
        "last_adjusted_close": closes[-1],
        "period_return_pct": (closes[-1] / closes[0] - 1) * 100 if closes[0] > 0 else None,
        "return_63_observations_pct": trailing(63),
        "return_252_observations_pct": trailing(252),
        "return_504_observations_pct": trailing(504),
        "annualized_volatility_pct": volatility,
        "max_drawdown_pct": max_drawdown * 100,
    }


class Pacer:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.last: float | None = None

    def wait(self) -> None:
        if self.last is not None:
            remaining = self.interval - (time.monotonic() - self.last)
            if remaining > 0:
                time.sleep(remaining)
        self.last = time.monotonic()


def get_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_snapshot() -> tuple[dict[str, Any], str]:
    entries = get_json(CONTENTS_API)
    if not isinstance(entries, list):
        raise ValueError("investor2 snapshot listing is not an array")
    candidates = sorted(
        [
            item for item in entries
            if isinstance(item, dict)
            and str(item.get("name", "")).startswith("edinet_top10_filing_marketcap_")
            and str(item.get("name", "")).endswith(".json")
            and item.get("download_url") and item.get("html_url")
        ],
        key=lambda item: str(item["name"]),
    )
    if not candidates:
        raise ValueError("no EDINET top-10 snapshot in investor2")
    selected = candidates[-1]
    payload = get_json(str(selected["download_url"]))
    if not isinstance(payload, dict):
        raise ValueError("investor2 snapshot is not an object")
    return payload, str(selected["html_url"])


def jquants_page(
    *, api_key: str, params: dict[str, Any], pacer: Pacer, attempts: int = 5
) -> tuple[dict[str, Any], str]:
    target = f"{BARS_ENDPOINT}?{urllib.parse.urlencode(params)}"
    for attempt in range(attempts):
        pacer.wait()
        try:
            request = urllib.request.Request(
                target,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json", "x-api-key": api_key},
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("J-Quants response is not an object")
                return payload, response.geturl()
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                raise
            retry_after = exc.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 15 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 >= attempts:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable retry state")


def fetch_bars(code: str, *, api_key: str, start: date, end: date, pacer: Pacer) -> tuple[list[dict[str, Any]], list[str]]:
    params: dict[str, Any] = {"code": code, "from": start.isoformat(), "to": end.isoformat()}
    bars: list[dict[str, Any]] = []
    urls: list[str] = []
    seen: set[str] = set()
    while True:
        payload, response_url = jquants_page(api_key=api_key, params=params, pacer=pacer)
        urls.append(response_url)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ValueError(f"J-Quants {code} response has no data array")
        bars.extend(
            bar for row in rows if isinstance(row, dict) and (bar := normalize_bar(row)) is not None
        )
        key = str(payload.get("pagination_key") or "")
        if not key:
            break
        if key in seen:
            raise ValueError(f"repeated pagination key for {code}")
        seen.add(key)
        params["pagination_key"] = key
    unique = {(bar["date"], bar["code"]): bar for bar in bars}
    return sorted(unique.values(), key=lambda row: (row["date"], row["code"])), urls


def build_dataset(*, lookback_days: int, interval: float) -> dict[str, Any]:
    api_key = os.environ.get("JQUANTS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("JQUANTS_API_KEY is required; fail-closed")
    snapshot, snapshot_url = latest_snapshot()
    records = snapshot.get("records")
    if not isinstance(records, list) or len(records) != 10:
        raise ValueError("EDINET universe must contain exactly 10 records")
    universe: list[tuple[str, str, str]] = []
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("non-object universe record")
        code = str(row.get("secCode") or "").strip()
        edinet_code = str(row.get("edinetCode") or "").strip()
        name = str(row.get("name") or "").strip()
        if len(code) != 5 or not code.isdigit() or not edinet_code or not name:
            raise ValueError(f"invalid universe record: {row}")
        universe.append((code, edinet_code, name))
    if len({item[0] for item in universe}) != 10:
        raise ValueError("duplicate security codes")

    end = date.today()
    start = end - timedelta(days=lookback_days)
    pacer = Pacer(interval)
    series: list[dict[str, Any]] = []
    for code, edinet_code, name in universe:
        bars, urls = fetch_bars(code, api_key=api_key, start=start, end=end, pacer=pacer)
        if not bars:
            raise ValueError(f"no J-Quants bars for {code} {name}")
        series.append({
            "security_code": code,
            "edinet_code": edinet_code,
            "name": name,
            "analysis": analyze_bars(bars),
            "bars": bars,
            "response_url_sha256": [canonical_hash(url) for url in urls],
        })

    payload: dict[str, Any] = {
        "schema_version": "investor2.jquants-private-bars.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "visibility_contract": {
            "storage": "private_only",
            "redistribution": "prohibited",
            "public_git_storage": False,
            "source_terms_url": TERMS_URL,
        },
        "source": {
            "provider": "J-Quants API V2",
            "endpoint": BARS_ENDPOINT,
            "requested_from": start.isoformat(),
            "requested_to": end.isoformat(),
            "authentication": "GitHub Actions secret only",
        },
        "universe": {
            "provider": "EDINET DB MCP via KAFKA2306/investor2",
            "snapshot_url": snapshot_url,
            "snapshot_schema_version": snapshot.get("schema_version"),
            "snapshot_observed_at": snapshot.get("observed_at"),
            "company_count": len(series),
        },
        "record_count": sum(len(item["bars"]) for item in series),
        "series": series,
    }
    payload["series_sha256"] = canonical_hash(series)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lookback-days", type=int, default=730)
    parser.add_argument("--minimum-interval-seconds", type=float, default=13.0)
    args = parser.parse_args()
    if args.lookback_days < 30 or args.minimum_interval_seconds < 0:
        raise SystemExit("invalid collection bounds")
    payload = build_dataset(lookback_days=args.lookback_days, interval=args.minimum_interval_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "company_count": payload["universe"]["company_count"],
        "record_count": payload["record_count"],
        "series_sha256": payload["series_sha256"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
