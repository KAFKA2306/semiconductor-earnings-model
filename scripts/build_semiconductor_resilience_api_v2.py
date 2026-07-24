#!/usr/bin/env python3
"""Run the resilience builder with recency-aware SEC XBRL tag selection."""

from __future__ import annotations

from typing import Any, Iterable

import build_semiconductor_resilience_api as legacy


def choose_recency_aware_tag_rows(
    facts: dict[str, Any],
    tags: Iterable[str],
    *,
    annual: bool,
) -> tuple[str | None, dict[Any, dict[str, Any]]]:
    """Choose the tag with the newest usable period, then the broadest history.

    SEC issuers can migrate between equivalent XBRL concepts. Selecting the first
    tag with any history can therefore pin a company to a stale period. Declared
    tag order remains the final tie-breaker only.
    """
    candidates: list[tuple[tuple[str, int, int], str, dict[Any, dict[str, Any]]]] = []
    for priority, tag in enumerate(tags):
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
