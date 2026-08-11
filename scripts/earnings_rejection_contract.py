from __future__ import annotations

from typing import Any

CANONICAL_REJECTION_REASONS = frozenset(
    {
        "OUTSIDE_TIME_WINDOW",
        "UNKNOWN_PUBLISHED_TIME",
        "STALE_FISCAL_PERIOD",
        "DUPLICATE",
        "NOT_PRIMARY_SOURCE",
        "FUTURE_EARNINGS_EVENT",
        "REPOST",
        "MISMATCHED_COMPANY",
        "UNVERIFIED_NUMBER",
    }
)

DISCOVERY_DETAIL_REASONS = frozenset(
    {
        "NOT_EARNINGS_RELATED",
        "UNVERIFIED_6K",
        "SOURCE_FETCH_FAILED",
    }
)


def classify_rejection(row: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic rejection contract without rewriting immutable evidence.

    earnings-event.v1 historically stored discovery/filter diagnostics in the
    ``rejection_reason`` field. Those values are not canonical validator reasons
    and must never be silently relabelled. A row that already carries a
    canonical reason is classified separately.
    """

    raw_reason = row.get("rejection_reason")
    if raw_reason in DISCOVERY_DETAIL_REASONS:
        return {
            "rejection_stage": "DISCOVERY_FILTER",
            "canonical_rejection_reason": None,
            "detail_reason": raw_reason,
        }
    if raw_reason in CANONICAL_REJECTION_REASONS:
        return {
            "rejection_stage": "CANONICAL_VALIDATION",
            "canonical_rejection_reason": raw_reason,
            "detail_reason": row.get("detail_reason"),
        }
    return {
        "rejection_stage": "UNKNOWN",
        "canonical_rejection_reason": None,
        "detail_reason": raw_reason,
    }
