#!/usr/bin/env python3
"""Deterministic parsing and comparison helpers for disclosed NAND KPIs."""

from __future__ import annotations

import re
from math import prod
from typing import Any, Iterable

BAND_POLICY_ID = "qualitative-percentage-band.v1"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("–", "-").replace("—", "-")).strip().lower()


def percentage_interval(phrase: str, *, direction: str = "increase") -> tuple[float, float]:
    """Map a disclosed qualitative percentage phrase to an auditable ratio interval."""
    text = _clean(phrase)
    sign = -1.0 if direction in {"decline", "decrease", "down"} else 1.0
    exact = re.search(r"(?:approximately|about|around)?\s*(\d+(?:\.\d+)?)\s*%", text)
    if exact:
        value = float(exact.group(1)) / 100.0
        spread = 0.005 if any(word in text for word in ("approximately", "about", "around")) else 0.0
        low, high = max(value - spread, 0.0), value + spread
        return (round(-high, 6), round(-low, 6)) if sign < 0 else (round(low, 6), round(high, 6))
    decade = re.search(r"\b(low|mid|high)(?:-to-(low|mid|high))?[- ]?(\d{2})s\b", text)
    if decade:
        offsets = {"low": (1, 3), "mid": (4, 6), "high": (7, 9)}
        base = int(decade.group(3))
        low = (base + offsets[decade.group(1)][0]) / 100.0
        high = (base + offsets[decade.group(2) or decade.group(1)][1]) / 100.0
        return (-high, -low) if sign < 0 else (low, high)
    teens = re.search(r"\b(low|mid|high)(?:-to-(low|mid|high))?[- ]?teens\b", text)
    if teens:
        offsets = {"low": (11, 13), "mid": (14, 16), "high": (17, 19)}
        low = offsets[teens.group(1)][0] / 100.0
        high = offsets[teens.group(2) or teens.group(1)][1] / 100.0
        return (-high, -low) if sign < 0 else (low, high)
    single = re.search(r"\b(low|mid|high)(?:-to-(low|mid|high))?[- ]?single[- ]digit", text)
    if single:
        offsets = {"low": (1, 3), "mid": (4, 6), "high": (7, 9)}
        low = offsets[single.group(1)][0] / 100.0
        high = offsets[single.group(2) or single.group(1)][1] / 100.0
        return (-high, -low) if sign < 0 else (low, high)
    double = re.search(r"\b(low|mid|high)(?:-to-(low|mid|high))?[- ]?double[- ]digit", text)
    if double:
        offsets = {"low": (10, 13), "mid": (14, 16), "high": (17, 19)}
        low = offsets[double.group(1)][0] / 100.0
        high = offsets[double.group(2) or double.group(1)][1] / 100.0
        return (-high, -low) if sign < 0 else (low, high)
    raise ValueError(f"Unsupported qualitative percentage phrase: {phrase!r}")


def compound_intervals(intervals: Iterable[tuple[float, float]]) -> tuple[float, float]:
    materialized = list(intervals)
    if not materialized:
        raise ValueError("At least one interval is required")
    return (
        round(prod(1.0 + low for low, _ in materialized) - 1.0, 8),
        round(prod(1.0 + high for _, high in materialized) - 1.0, 8),
    )


def compare_intervals(actual: tuple[float, float], guidance: tuple[float, float]) -> dict[str, Any]:
    actual_low, actual_high = actual
    guide_low, guide_high = guidance
    result = "above" if actual_low > guide_high else "below" if actual_high < guide_low else "overlap"
    return {
        "result": result,
        "difference_low": round(actual_low - guide_high, 8),
        "difference_high": round(actual_high - guide_low, 8),
    }


def extract_micron_nand_kpis(text: str) -> dict[str, Any]:
    """Extract only the NAND paragraph and reject an earlier DRAM paragraph."""
    normalized = re.sub(r"\s+", " ", text.replace("–", "-").replace("—", "-"))
    normalized = re.sub(r"(?i)\b(low|mid|high)-\s*to-", r"\1-to-", normalized)
    match = re.search(
        r"\bNAND\b\s+Fiscal\s+Q[1-4]\s+NAND\s+revenue.{0,700}?"
        r"(?:NAND\s+)?Bit shipments\s+"
        r"(?P<bits>(?:increased|were up|declined|decreased).*?percentage range)"
        r"(?:\.\s+|,\s+and\s+)"
        r"Prices\s+"
        r"(?P<prices>(?:increased|were up|declined|decreased).*?percentage range)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("Micron NAND KPI paragraph not found")

    def parse(statement: str) -> tuple[tuple[float, float], str]:
        lowered = statement.lower()
        direction = "decline" if any(word in lowered for word in ("declined", "decreased", "down")) else "increase"
        phrase_match = re.search(
            r"((?:low|mid|high)(?:-to-(?:low|mid|high))?[- ]?(?:single[- ]digit|double[- ]digit|teens|\d{2}s))",
            lowered,
        )
        if not phrase_match:
            raise ValueError(f"No supported percentage phrase in {statement!r}")
        phrase = phrase_match.group(1)
        return percentage_interval(phrase, direction=direction), phrase

    bits, bits_phrase = parse(match.group("bits"))
    prices, price_phrase = parse(match.group("prices"))
    return {
        "bit_shipments": {
            "value_low": bits[0],
            "value_high": bits[1],
            "reported_text": match.group("bits").strip(),
            "reported_phrase": bits_phrase,
        },
        "asp": {
            "value_low": prices[0],
            "value_high": prices[1],
            "reported_text": match.group("prices").strip(),
            "reported_phrase": price_phrase,
        },
    }
