from __future__ import annotations

import argparse
import calendar
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ALLOWED_VALUE_TYPES = {"actual", "company_guidance", "analyst_consensus", "market_observation"}


def visible_date(row: dict[str, Any]) -> str | None:
    source_tier = row.get("source_tier")
    value_type = row.get("value_type")
    if source_tier == "primary_regulatory":
        candidates = (row.get("filed_at"), row.get("observed_at"))
    elif value_type == "market_observation":
        candidates = (row.get("observed_at"), row.get("as_of"))
    else:
        candidates = (row.get("observed_at"), row.get("filed_at"), row.get("as_of"))
    for value in candidates:
        if value:
            return str(value)[:10]
    return None


def factor_signature(row: dict[str, Any]) -> str:
    fields = (
        row.get("value_type") or "unknown",
        row.get("concept_id") or "unknown",
        row.get("unit") or "unit_unknown",
        row.get("period_type") or "period_unknown",
        row.get("scope") or "scope_unknown",
        row.get("segment") or "all_segments",
    )
    return ":".join(str(value).replace(":", "_") for value in fields)


def month_end_days(start: date, end: date) -> list[date]:
    if end < start:
        return []
    out: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        current = date(year, month, calendar.monthrange(year, month)[1])
        if current >= start and current <= end:
            out.append(current)
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return out


def _point_candidates(financial: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in financial.get("observations", []):
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if row.get("value_type") not in ALLOWED_VALUE_TYPES:
            continue
        known_at = visible_date(row)
        if not known_at:
            continue
        out.append({
            "entity_id": row.get("entity_id"),
            "factor_name": factor_signature(row),
            "known_at": known_at,
            "value": float(value),
            "unit": row.get("unit"),
            "value_type": row.get("value_type"),
            "evidence_ids": [row.get("id")],
        })
    return [row for row in out if row["entity_id"] and row["evidence_ids"][0]]


def build_factor_panel(financial: dict[str, Any], max_age_days: int = 550) -> list[dict[str, Any]]:
    if max_age_days < 1:
        raise ValueError("max_age_days must be positive")
    candidates = _point_candidates(financial)
    if not candidates:
        return []

    by_factor_entity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_factor_entity[(row["factor_name"], row["entity_id"])].append(row)
    for rows in by_factor_entity.values():
        rows.sort(key=lambda row: (row["known_at"], row["evidence_ids"][0]))

    start = min(date.fromisoformat(row["known_at"]) for row in candidates)
    latest = max(date.fromisoformat(row["known_at"]) for row in candidates)
    end = date(latest.year, latest.month, calendar.monthrange(latest.year, latest.month)[1])
    evaluation_days = month_end_days(start, end)

    output: list[dict[str, Any]] = []
    factors = sorted({key[0] for key in by_factor_entity})
    entities = sorted({key[1] for key in by_factor_entity})
    for day in evaluation_days:
        day_text = day.isoformat()
        for factor in factors:
            for entity in entities:
                rows = by_factor_entity.get((factor, entity), [])
                eligible = [row for row in rows if row["known_at"] <= day_text]
                if not eligible:
                    continue
                latest_row = eligible[-1]
                age_days = (day - date.fromisoformat(latest_row["known_at"])).days
                if age_days > max_age_days:
                    continue
                output.append({
                    "entity_id": entity,
                    "factor_name": factor,
                    "as_of": day_text,
                    "value": latest_row["value"],
                    "known_at": latest_row["known_at"],
                    "age_days": age_days,
                    "unit": latest_row["unit"],
                    "source_type": latest_row["value_type"],
                    "evidence_ids": latest_row["evidence_ids"],
                })
    return output


def entity_yahoo_symbols(financial: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entity in financial.get("entities", []):
        entity_id = str(entity.get("id") or "")
        ticker = str(entity.get("ticker") or "").strip()
        if not entity_id:
            continue
        prefix, _, code = entity_id.partition(":")
        exchange = str(entity.get("exchange") or "").strip().lower()
        symbol = ""
        if "kosdaq" in exchange:
            symbol = f"{ticker.zfill(6)}.KQ" if ticker else ""
        elif "korea" in exchange or exchange in {"krx", "kospi"}:
            symbol = f"{ticker.zfill(6)}.KS" if ticker else ""
        elif exchange.startswith("tse") or "tokyo stock exchange" in exchange:
            symbol = f"{ticker}.T" if ticker else ""
        elif prefix == "JP" and code:
            symbol = f"{code}.T"
        elif prefix == "KR" and code:
            symbol = f"{code.zfill(6)}.KS"
        elif prefix == "TW" and code:
            symbol = f"{code}.TW"
        elif prefix == "US" and ticker:
            symbol = ticker
        elif ticker:
            symbol = ticker
        if symbol:
            result[entity_id] = symbol
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build point-in-time factor panel from Financial Database v3.")
    parser.add_argument("--financial-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-age-days", type=int, default=550)
    args = parser.parse_args()
    financial = json.loads(args.financial_db.read_text(encoding="utf-8"))
    rows = build_factor_panel(financial, max_age_days=args.max_age_days)
    payload = {
        "schema_version": "factor-input.v1",
        "rows": rows,
        "entity_yahoo_symbols": entity_yahoo_symbols(financial),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()