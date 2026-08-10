#!/usr/bin/env python3
"""Build a private-only J-Quants market dataset for investor2.

J-Quants API data is licensed for personal use and must not be redistributed in
viewable form. This collector therefore writes only to a temporary local path;
the GitHub Actions caller is responsible for uploading that file directly to a
private Hugging Face bucket and verifying a read-back hash. No J-Quants rows are
committed to GitHub.
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

INVESTOR2_CONTENTS_API = (
    "https://api.github.com/repos/KAFKA2306/investor2/contents/data/market_snapshots"
)
JQUANTS_BASE = "https://api.jquants.com/v2"
JQUANTS_BARS_ENDPOINT = f"{JQUANTS_BASE}/equities/bars/daily"
JQUANTS_TERMS_URL = "https://jpx-jquants.com/"
USER_AGENT = "KAFKA2306 investor2 private J-Quants collector"


def canonical_json_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _first_number(record: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = _number(record.get(name))
        if value is not None:
            return value
    return None


def normalize_bar(record: Mapping[str, Any]) -> dict[str, Any] | None:
    day = str(record.get("Date") or "").strip()
    code = str(record.get("Code") or "").strip()
    close = _first_number(record, "AdjC", "C", "AdjustmentClose", "Close")
    if not day or not code or close is None:
        return None
    return {
        "date": day,
        "code": code,
        "open": _first_number(record, "AdjO", "O", "AdjustmentOpen", "Open"),
        "high": _first_number(record, "AdjH", "H", "AdjustmentHigh", "High"),
        "low": _first_number(record, "AdjL", "L", "AdjustmentLow", "Low"),
        "close": close,
        "volume": _first_number(record, "AdjVo", "Vo", "AdjustmentVolume", "Volume"),
    }


def analyze_bars(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda item: str(item["date"]))
    closes = [float(item["close"]) for item in ordered]
    if not closes:
        raise ValueError("cannot analyze an empty bar series")

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
            max_drawdown = min(max_drawdown, close / peak - 1.0)

    def trailing_return(observations: int) -> float | None:
        if len(closes) <= observations:
            return None
        base = closes[-(observations + 1)]
        return (closes[-1] / base - 1.0) * 100 if base > 0 else None

    annualized_volatility = None
    if len(log_returns) >= 2:
        annualized_volatility = statistics.stdev(log_returns) * math.sqrt(252) * 100

    return {
        "row_count": len(ordered),
        "first_date": str(ordered[0]["date"]),
        "last_date": str(ordered[-1]["date"]),
        "first_adjusted_close": closes[0],
        "last_adjusted_close": closes[-1],
        "period_return_pct": (closes[-1] / closes[0] - 1.0) * 100 if closes[0] > 0 else None,
        "return_63_observations_pct": trailing_return(63),
        "return_252_observations_pct": trailing_return(252),
        "return_504_observations_pct": trailing_return(504),
        "annualized_volatility_pct": annualized_volatility,
        "max_drawdown_pct": max_drawdown * 100,
    }


class Pacer:
    def __init__(self, minimum_interval_seconds: float) -> None:
        self.minimum_interval_seconds = minimum_interval_seconds
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            remaining = self.minimum_interval_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    pacer: Pacer | None = None,
    attempts: int = 5,
) -> tuple[dict[str, Any], str]:
    query = urllib.parse.urlencode(params or {})
    target = f"{url}?{query}" if query else url
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(attempts):
        if pacer is not None:
            pacer.wait()
        try:
            request = urllib.request.Request(target, headers=request_headers)
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError(f"expected object response from {response.geturl()}")
                return payload, response.geturl()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                raise
            retry_after = exc.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 15 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"request failed: {target}: {last_error}")


def load_latest_investor2_snapshot() -> tuple[dict[str, Any], str]:
    listing, _ = request_json(INVESTOR2_CONTENTS_API)
    # GitHub's contents API returns an array, so request it directly here rather than
    # using request_json's object-only contract.
    request = urllib.request.Request(
        INVESTOR2_CONTENTS_API,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        entries = json.loads(response.read().decode("utf-8"))
    if not isinstance(entries, list):
        raise ValueError("investor2 market snapshot listing is not an array")
    candidates = sorted(
        (
            item
            for item in entries
            if isinstance(item, dict)
            and str(item.get("name", "")).startswith("edinet_top10_filing_marketcap_")
            and str(item.get("name", "")).endswith(".json")
            and item.get("download_url")
        ),
        key=lambda item: str(item["name"]),
    )
    if not candidates:
        raise ValueError("no EDINET top-10 snapshot exists in investor2")
    selected = candidates[-1]
    request = urllib.request.Request(
        str(selected["download_url"]), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("investor2 snapshot is not an object")
    return payload, str(selected["html_url"])


def fetch_bars_for_code(
    code: str,
    *,
    api_key: str,
    start: date,
    end: date,
    pacer: Pacer,
) -> tuple[list[dict[str, Any]], list[str]]:
    query: dict[str, Any] = {"code": code, "from": start.isoformat(), "to": end.isoformat()}
    normalized: list[dict[str, Any]] = []
    response_urls: list[str] = []
    seen_pages: set[str] = set()
    while True:
        payload, response_url = request_json(
            JQUANTS_BARS_ENDPOINT,
            params=query,
            headers={"x-api-key": api_key},
            pacer=pacer,
        )
        response_urls.append(response_url)
        records = payload.get("data")
        if not isinstance(records, list):
            raise ValueError(f"J-Quants response for {code} has no data array")
        normalized.extend(
            bar for item in records if isinstance(item, dict) and (bar := normalize_bar(item)) is not None
        )
        pagination_key = str(payload.get("pagination_key") or "")
        if not pagination_key:
            break
        if pagination_key in seen_pages:
            raise ValueError(f"repeated J-Quants pagination key for {code}")
        seen_pages.add(pagination_key)
        query["pagination_key"] = pagination_key
    unique = {(bar["date"], bar["code"]): bar for bar in normalized}
    return sorted(unique.values(), key=lambda item: (item["date"], item["code"])), response_urls


def build_dataset(*, lookback_days: int, minimum_interval_seconds: float) -> dict[str, Any]:
    api_key = os.environ.get("JQUANTS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("JQUANTS_API_KEY is required; fail-closed")

    snapshot, snapshot_url = load_latest_investor2_snapshot()
    records = snapshot.get("records")
    if not isinstance(records, list) or len(records) != 10:
        raise ValueError("investor2 EDINET universe must contain exactly 10 records")
    universe: list[tuple[str, str, str]] = []
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("investor2 EDINET universe contains a non-object")
        code = str(item.get("secCode") or "").strip()
        edinet_code = str(item.get("edinetCode") or "").strip()
        name = str(item.get("name") or "").strip()
        if len(code) != 5 or not code.isdigit() or not edinet_code or not name:
            raise ValueError(f"invalid investor2 universe record: {item}")
        universe.append((code, edinet_code, name))
    if len({code for code, _, _ in universe}) != len(universe):
        raise ValueError("investor2 universe has duplicate security codes")

    end = date.today()
    start = end - timedelta(days=lookback_days)
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    pacer = Pacer(minimum_interval_seconds)
    series: list[dict[str, Any]] = []
    total_rows = 0
    for code, edinet_code, name in universe:
        bars, response_urls = fetch_bars_for_code(
            code, api_key=api_key, start=start, end=end, pacer=pacer
        )
        if not bars:
            raise ValueError(f"J-Quants returned no daily bars for {code} {name}")
        analysis = analyze_bars(bars)
        total_rows += len(bars)
        series.append(
            {
                "security_code": code,
                "edinet_code": edinet_code,
                "name": name,
                "analysis": analysis,
                "bars": bars,
                "response_url_sha256": [canonical_json_hash(url) for url in response_urls],
            }
        )

    payload = {
        "schema_version": "investor2.jquants-private-bars.v1",
        "generated_at": fetched_at,
        "visibility_contract": {
            "storage": "private_only",
            "redistribution": "prohibited",
            "public_git_storage": false,
            "source_terms_url": JQUANTS_TERMS_URL,
        },
        "source": {
            "provider": "J-Quants API V2",
            "endpoint": JQUANTS_BARS_ENDPOINT,
            "requested_from": start.isoformat(),
            "requested_to": end.isoformat(),
            "authentication": "API key supplied only via GitHub Actions secret",
        },
        "universe": {
            "provider": "EDINET DB MCP via KAFKA2306/investor2",
            "snapshot_url": snapshot_url,
            "snapshot_schema_version": snapshot.get("schema_version"),
            "snapshot_observed_at": snapshot.get("observed_at"),
            "company_count": len(series),
        },
        "record_count": total_rows,
        "series": series,
    }
    payload["series_sha256"] = canonical_json_hash(series)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lookback-days", type=int, default=730)
    parser.add_argument(
        "--minimum-interval-seconds",
        type=float,
        default=float(os.environ.get("JQUANTS_MIN_INTERVAL_SECONDS", "13")),
    )
    args = parser.parse_args()
    if args.lookback_days < 30:
        raise SystemExit("lookback-days must be >= 30")
    if args.minimum_interval_seconds < 0:
        raise SystemExit("minimum-interval-seconds must be >= 0")
    payload = build_dataset(
        lookback_days=args.lookback_days,
        minimum_interval_seconds=args.minimum_interval_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": "PASS",
                "output": str(args.output),
                "company_count": payload["universe"]["company_count"],
                "record_count": payload["record_count"],
                "series_sha256": payload["series_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
