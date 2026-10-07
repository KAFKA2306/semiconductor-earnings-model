from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, pstdev, stdev
from typing import Any, Iterable, Sequence

HORIZON_DAYS = {"1m": 30, "3m": 91, "6m": 182, "12m": 365}


def _iso_day(value: str) -> date:
    return date.fromisoformat(value[:10])


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        average_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            out[order[k]] = average_rank
        i = j
    return out


def pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    mx, my = mean(x), mean(y)
    dx = [value - mx for value in x]
    dy = [value - my for value in y]
    denominator = math.sqrt(sum(value * value for value in dx) * sum(value * value for value in dy))
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / denominator


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    return pearson(_rank(x), _rank(y))


def zscores(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    sigma = pstdev(values)
    if sigma == 0:
        return [0.0] * len(values)
    mu = mean(values)
    return [(value - mu) / sigma for value in values]


def quantile_labels(values: Sequence[float], bins: int) -> list[int]:
    if bins < 2:
        raise ValueError("bins must be >= 2")
    order = sorted(range(len(values)), key=values.__getitem__)
    labels = [0] * len(values)
    size = len(values)
    for position, index in enumerate(order):
        labels[index] = min(bins, position * bins // size + 1)
    return labels


def _sorted_prices(price_rows: Iterable[dict[str, Any]]) -> dict[str, list[tuple[date, float]]]:
    grouped: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in price_rows:
        entity = str(row.get("entity_id") or "").strip()
        day = str(row.get("date") or "").strip()
        close = _finite(row.get("close"))
        if not entity or not day or close is None or close <= 0:
            continue
        grouped[entity].append((_iso_day(day), close))
    for rows in grouped.values():
        rows.sort(key=lambda item: item[0])
    return grouped


def _first_on_or_after(rows: Sequence[tuple[date, float]], target: date) -> tuple[date, float] | None:
    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if rows[mid][0] < target:
            lo = mid + 1
        else:
            hi = mid
    return rows[lo] if lo < len(rows) else None


def attach_forward_returns(
    factor_rows: Iterable[dict[str, Any]],
    price_rows: Iterable[dict[str, Any]],
    horizons: dict[str, int] | None = None,
    max_price_lag_days: int = 7,
) -> list[dict[str, Any]]:
    horizons = horizons or HORIZON_DAYS
    prices = _sorted_prices(price_rows)
    out: list[dict[str, Any]] = []
    for raw in factor_rows:
        entity = str(raw.get("entity_id") or "").strip()
        factor = str(raw.get("factor_name") or "").strip()
        as_of_raw = str(raw.get("as_of") or "").strip()
        value = _finite(raw.get("value"))
        if not entity or not factor or not as_of_raw or value is None:
            continue
        as_of = _iso_day(as_of_raw)
        series = prices.get(entity, [])
        start = _first_on_or_after(series, as_of)
        row = {**raw, "value": value, "forward_returns": {}}
        if start is None or (start[0] - as_of).days > max_price_lag_days:
            row["missing_reason"] = "no_start_price_within_lag"
            out.append(row)
            continue
        row["start_price_date"] = start[0].isoformat()
        for label, days in horizons.items():
            target = as_of + timedelta(days=days)
            end = _first_on_or_after(series, target)
            if end is None or (end[0] - target).days > max_price_lag_days:
                row["forward_returns"][label] = None
                continue
            row["forward_returns"][label] = end[1] / start[1] - 1.0
        out.append(row)
    return out


def _bucket_rows(rows: Iterable[dict[str, Any]], horizon: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        forward_return = _finite(row.get("forward_returns", {}).get(horizon))
        value = _finite(row.get("value"))
        if forward_return is None or value is None:
            continue
        grouped[(str(row["factor_name"]), str(row["as_of"])[:10])].append(
            {**row, "_return": forward_return, "_value": value}
        )
    return grouped


def evaluate_factor(
    attached_rows: Sequence[dict[str, Any]],
    factor_name: str,
    horizon: str,
    bins: int = 5,
    min_cross_section: int = 3,
) -> dict[str, Any]:
    groups = _bucket_rows((row for row in attached_rows if row.get("factor_name") == factor_name), horizon)
    cross_sections: list[dict[str, Any]] = []
    pooled_x: list[float] = []
    pooled_y: list[float] = []
    quantile_returns: dict[int, list[float]] = defaultdict(list)

    for (_, as_of), rows in sorted(groups.items()):
        if len(rows) < min_cross_section:
            continue
        values = [row["_value"] for row in rows]
        returns = [row["_return"] for row in rows]
        rank_ic = spearman(values, returns)
        ic = pearson(values, returns)
        labels = quantile_labels(values, min(bins, len(rows)))
        for label, forward_return in zip(labels, returns, strict=True):
            quantile_returns[label].append(forward_return)
        pooled_x.extend(values)
        pooled_y.extend(returns)
        cross_sections.append({"as_of": as_of, "sample_size": len(rows), "ic": ic, "rank_ic": rank_ic})

    rank_ics = [float(row["rank_ic"]) for row in cross_sections if row["rank_ic"] is not None]
    quantiles = {str(key): mean(values) for key, values in sorted(quantile_returns.items()) if values}
    spread = None
    monotonicity = None
    if quantiles:
        low, high = str(min(map(int, quantiles))), str(max(map(int, quantiles)))
        spread = quantiles[high] - quantiles[low]
        ordered = sorted((int(key), value) for key, value in quantiles.items())
        if len(ordered) >= 2:
            monotonicity = spearman([float(key) for key, _ in ordered], [value for _, value in ordered])

    rank_ic_mean = mean(rank_ics) if rank_ics else None
    rank_ic_std = stdev(rank_ics) if len(rank_ics) > 1 else None
    rank_ic_ir = None if not rank_ic_std else rank_ic_mean / rank_ic_std
    rank_ic_tstat = None
    if rank_ic_std and rank_ics:
        rank_ic_tstat = rank_ic_mean / (rank_ic_std / math.sqrt(len(rank_ics)))
    return {
        "factor_name": factor_name,
        "horizon": horizon,
        "sample_size": len(pooled_x),
        "cross_section_count": len(cross_sections),
        "pooled_ic": pearson(pooled_x, pooled_y),
        "pooled_rank_ic": spearman(pooled_x, pooled_y),
        "rank_ic_mean": rank_ic_mean,
        "rank_ic_std": rank_ic_std,
        "rank_ic_ir": rank_ic_ir,
        "rank_ic_tstat": rank_ic_tstat,
        "rank_ic_positive_ratio": (sum(value > 0 for value in rank_ics) / len(rank_ics)) if rank_ics else None,
        "quantile_mean_returns": quantiles,
        "quantile_monotonicity": monotonicity,
        "top_minus_bottom": spread,
        "cross_sections": cross_sections,
    }


def build_factor_lab(
    factor_rows: Sequence[dict[str, Any]],
    price_rows: Sequence[dict[str, Any]],
    horizons: dict[str, int] | None = None,
    bins: int = 5,
    min_cross_section: int = 3,
) -> dict[str, Any]:
    horizons = horizons or HORIZON_DAYS
    attached = attach_forward_returns(factor_rows, price_rows, horizons=horizons)
    factors = sorted({str(row.get("factor_name")) for row in attached if row.get("factor_name")})
    tests = [
        evaluate_factor(attached, factor, horizon, bins=bins, min_cross_section=min_cross_section)
        for factor in factors
        for horizon in horizons
    ]
    normalized = []
    for factor in factors:
        subset = [row for row in attached if row.get("factor_name") == factor and _finite(row.get("value")) is not None]
        by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in subset:
            by_day[str(row["as_of"])[:10]].append(row)
        for day, rows in sorted(by_day.items()):
            values = [float(row["value"]) for row in rows]
            zs = zscores(values)
            for row, zscore in zip(rows, zs, strict=True):
                normalized.append({
                    "entity_id": row["entity_id"],
                    "factor_name": factor,
                    "as_of": day,
                    "known_at": row.get("known_at"),
                    "age_days": row.get("age_days"),
                    "unit": row.get("unit"),
                    "source_type": row.get("source_type"),
                    "raw_value": row["value"],
                    "zscore": zscore,
                    "forward_returns": row.get("forward_returns", {}),
                    "evidence_ids": row.get("evidence_ids", []),
                })
    payload = {
        "schema_version": "factor-lab.v1",
        "methodology": {
            "return_formula": "end_close / start_close - 1",
            "start_price_rule": "first close on or after factor as_of, bounded by max price lag",
            "rank_ic": "Spearman cross-sectional correlation with average ranks for ties",
            "ic": "Pearson cross-sectional correlation",
            "quantiles": bins,
            "min_cross_section": min_cross_section,
            "horizons_calendar_days": horizons,
            "anti_leakage": "factor value must be observable on or before as_of; future returns start no earlier than as_of",
        },
        "factor_observations": normalized,
        "factor_tests": tests,
        "audit": {
            "factor_row_count": len(factor_rows),
            "attached_row_count": len(attached),
            "factor_count": len(factors),
            "test_count": len(tests),
            "rows_without_start_price": sum(row.get("missing_reason") == "no_start_price_within_lag" for row in attached),
            "rows_with_any_forward_return": sum(any(value is not None for value in row.get("forward_returns", {}).values()) for row in attached),
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["content_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]
    raise ValueError(f"unsupported row container: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic factor IC and quantile research output.")
    parser.add_argument("--factors", type=Path, required=True)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bins", type=int, default=5)
    parser.add_argument("--min-cross-section", type=int, default=3)
    args = parser.parse_args()
    payload = build_factor_lab(
        _load_rows(args.factors),
        _load_rows(args.prices),
        bins=args.bins,
        min_cross_section=args.min_cross_section,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
