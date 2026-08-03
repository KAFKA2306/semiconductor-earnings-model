from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nand_collection_state import (  # noqa: E402
    build_document_state,
    content_sha256,
    freshness_audit,
    prioritize_candidates,
    select_candidates,
    should_parse_document,
)


def candidate(index: int, year: int = 2025) -> dict[str, object]:
    return {
        "source_url": f"https://example.com/results/{year}-01-{index + 1:02d}/document.pdf",
        "period_end": f"{year}-01-{index + 1:02d}",
        "discovery_rank": index,
    }


def test_new_41st_document_is_selected_before_processed_old_documents() -> None:
    old = [candidate(index) for index in range(40)]
    previous = {
        item["source_url"]: {
            "source_url": item["source_url"],
            "parse_status": "parsed",
            "content_sha256": str(index),
        }
        for index, item in enumerate(old)
    }
    latest = {
        "source_url": "https://example.com/results/2026-08-01/latest.pdf",
        "period_end": "2026-08-01",
        "discovery_rank": 40,
    }

    selected, skipped = select_candidates(old + [latest], previous, limit=40)

    selected_urls = {item["source_url"] for item in selected}
    assert latest["source_url"] in selected_urls
    assert len(skipped) == 1
    assert skipped[0]["previously_processed"] is True
    assert skipped[0]["reason"] == "candidate_limit"


def test_newer_date_beats_url_lexical_order() -> None:
    candidates = [
        {
            "source_url": "https://example.com/z-old-2025-01-01.pdf",
            "period_end": "2025-01-01",
        },
        {
            "source_url": "https://example.com/a-new-2026-06-01.pdf",
            "period_end": "2026-06-01",
        },
    ]
    ordered = prioritize_candidates(candidates, {})
    assert ordered[0]["period_end"] == "2026-06-01"


def test_discovery_order_beats_url_order_when_dates_are_unknown() -> None:
    candidates = [
        {"source_url": "https://example.com/a.pdf", "discovery_rank": 9},
        {"source_url": "https://example.com/z.pdf", "discovery_rank": 1},
    ]
    ordered = prioritize_candidates(candidates, {})
    assert [item["source_url"] for item in ordered] == [
        "https://example.com/z.pdf",
        "https://example.com/a.pdf",
    ]


def test_unchanged_document_is_not_reparsed() -> None:
    content = b"official quarterly disclosure"
    digest = content_sha256(content)
    previous = {"content_sha256": digest, "parse_status": "parsed"}
    assert should_parse_document(previous, digest) is False
    assert should_parse_document(previous, content_sha256(content + b" updated")) is True


def test_document_state_preserves_discovery_and_increments_retry() -> None:
    previous = {
        "first_discovered_at": "2026-07-01T00:00:00+00:00",
        "retry_count": 2,
    }
    state = build_document_state(
        candidate={"source_url": "https://example.com/result.pdf"},
        previous=previous,
        checked_at="2026-08-03T00:00:00+00:00",
        content_hash=None,
        parse_status="error",
        error=RuntimeError("temporary failure"),
    )
    assert state["first_discovered_at"] == "2026-07-01T00:00:00+00:00"
    assert state["retry_count"] == 3
    assert state["error_type"] == "RuntimeError"


def test_freshness_audit_has_fresh_stale_and_missing_states() -> None:
    source = {
        "entity_id": "micron",
        "require_current_observation": True,
        "max_observation_age_days": 180,
    }
    fresh = freshness_audit(
        [{"entity_id": "micron", "period_end": "2026-05-28"}],
        source,
        today=date(2026, 8, 3),
    )
    stale = freshness_audit(
        [{"entity_id": "micron", "period_end": "2025-01-01"}],
        source,
        today=date(2026, 8, 3),
    )
    missing = freshness_audit([], source, today=date(2026, 8, 3))

    assert fresh["status"] == "fresh"
    assert stale["status"] == "stale"
    assert missing["status"] == "missing"
