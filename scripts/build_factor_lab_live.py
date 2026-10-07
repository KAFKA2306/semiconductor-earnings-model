from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from factor_inputs import build_factor_panel, entity_yahoo_symbols
from factor_lab import build_factor_lab


def _close_series(raw: Any, symbol: str, symbol_count: int) -> Any:
    if symbol_count > 1:
        try:
            frame = raw[symbol]
        except KeyError:
            return None
    else:
        frame = raw
        if getattr(frame.columns, "nlevels", 1) > 1:
            first_level = set(map(str, frame.columns.get_level_values(0)))
            if symbol in first_level:
                frame = frame[symbol]
    if "Close" not in frame:
        return None
    series = frame["Close"]
    if getattr(series, "ndim", 1) > 1:
        series = series.iloc[:, 0]
    return series.dropna()


def download_prices(
    symbols: dict[str, str],
    start: str,
    end: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import pandas as pd
    import yfinance as yf

    reverse = {symbol: entity for entity, symbol in symbols.items()}
    requested = sorted(reverse)
    if not requested:
        return [], {
            "source": "Yahoo Finance via yfinance",
            "symbols": {},
            "raw_sha256": None,
            "raw_persisted": False,
        }

    raw = yf.download(
        requested,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        actions=False,
        repair=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError("Yahoo price download returned no rows")

    rows: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for symbol in requested:
        series = _close_series(raw, symbol, len(requested))
        if series is None:
            continue
        for index, value in series.items():
            day = pd.Timestamp(index).date().isoformat()
            close = float(value)
            entity = reverse[symbol]
            rows.append({"entity_id": entity, "date": day, "close": close})
            digest.update(f"{entity}|{day}|{close:.12g}\n".encode())

    rows.sort(key=lambda row: (row["entity_id"], row["date"]))
    if not rows:
        raise RuntimeError("Yahoo price download contained no usable closes")
    return rows, {
        "source": "Yahoo Finance via yfinance",
        "symbols": symbols,
        "raw_sha256": digest.hexdigest(),
        "raw_persisted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build live Factor Lab output without persisting raw market prices."
    )
    parser.add_argument("--financial-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-age-days", type=int, default=550)
    parser.add_argument("--min-cross-section", type=int, default=3)
    args = parser.parse_args()

    financial = json.loads(args.financial_db.read_text(encoding="utf-8"))
    factor_rows = build_factor_panel(financial, max_age_days=args.max_age_days)
    if not factor_rows:
        raise RuntimeError("factor panel is empty")

    symbols = entity_yahoo_symbols(financial)
    start = min(row["as_of"] for row in factor_rows)
    end = (date.today() + timedelta(days=1)).isoformat()
    prices, market_evidence = download_prices(symbols, start, end)
    payload = build_factor_lab(
        factor_rows,
        prices,
        bins=5,
        min_cross_section=args.min_cross_section,
    )
    payload["market_data"] = market_evidence
    payload["input_contract"] = {
        "financial_schema_version": financial.get("schema_version"),
        "factor_panel_rows": len(factor_rows),
        "raw_market_prices_persisted": False,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
