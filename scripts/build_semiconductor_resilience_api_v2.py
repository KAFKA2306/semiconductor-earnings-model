#!/usr/bin/env python3
"""Run the resilience builder with recency-aware SEC XBRL tag selection."""

from __future__ import annotations

from typing import Any, Iterable

import build_semiconductor_resilience_api as legacy


REVENUE_EQUIVALENT_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
CAPEX_EQUIVALENT_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForAdditionsToPropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
)


def expanded_equivalent_tags(tags: Iterable[str], *, annual: bool) -> tuple[str, ...]:
    requested = tuple(tags)
    if not annual:
        return requested
    if len(requested) == 1 and requested[0] in REVENUE_EQUIVALENT_TAGS:
        return tuple(dict.fromkeys((*requested, *REVENUE_EQUIVALENT_TAGS)))
    if requested and all(tag in CAPEX_EQUIVALENT_TAGS for tag in requested):
        return tuple(dict.fromkeys((*requested, *CAPEX_EQUIVALENT_TAGS)))
    return requested


def choose_recency_aware_tag_rows(
    facts: dict[str, Any],
    tags: Iterable[str],
    *,
    annual: bool,
) -> tuple[str | None, dict[Any, dict[str, Any]]]:
    """Choose the newest equivalent SEC concept, then the broadest history.

    SEC issuers can migrate between equivalent XBRL concepts. Selecting the first
    tag with any history can pin a company to a stale period. Standard annual
    revenue concepts and CapEx concepts, including productive assets, are treated
    as explicit equivalent sets. Declared tag order is the final tie-breaker only.
    """
    candidates: list[tuple[tuple[str, int, int], str, dict[Any, dict[str, Any]]]] = []
    candidate_tags = expanded_equivalent_tags(tags, annual=annual)
    for priority, tag in enumerate(candidate_tags):
        rows = legacy.rows_for_tag(facts, tag, annual=annual)
        by_period = legacy.latest_by_period(rows, instant=not annual)
        if not by_period:
            continue
        latest_end = max(key if isinstance(key, str) else key[1] for key in by_period)
        candidates.append(((latest_end, len(by_period), -priority), tag, by_period))
    if not candidates:
        return None, {}
    _, tag, by_period = max(candidates, key=lambda item: item[0])
    return tag, by_period


def main() -> None:
    legacy.choose_tag_rows = choose_recency_aware_tag_rows
    legacy.main()


if __name__ == "__main__":
    main()
