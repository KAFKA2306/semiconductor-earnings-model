from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_ledger_page_publication_boundary.py"
SPEC = importlib.util.spec_from_file_location("check_ledger_page_publication_boundary", MODULE_PATH)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def publication(event_ids: list[str], *, expired: int = 0) -> dict:
    return {
        "schema_version": "earnings-ledger-publication.v1",
        "audit_status": "PASS",
        "accepted_events_total": len(event_ids),
        "ledger_accepted_events_total": len(event_ids) + expired,
        "expired_events_total": expired,
        "events": [{"event_id": event_id} for event_id in event_ids],
        "contract": {
            "primary_sources_only": True,
            "freshness_gate_hours": 24,
            "publication_rechecks_freshness": True,
            "fail_closed": True,
            "unverified_values_published": False,
        },
    }


def revenue(event_ids: list[str]) -> dict:
    return {"metrics": [{"event_id": event_id} for event_id in event_ids]}


def html(*event_ids: str, fresh: int, expired: int, visible: int, hidden: int) -> str:
    cards = "".join(f'<article data-event-id="{event_id}"></article>' for event_id in event_ids)
    return (
        f'<body data-fresh-event-count="{fresh}" data-expired-event-count="{expired}" '
        f'data-visible-metric-count="{visible}" data-hidden-by-freshness-count="{hidden}">'
        f"{cards}</body>"
    )


def test_fresh_metric_is_renderable():
    issues = checker.audit_rendered_ledger(
        html("fresh", fresh=1, expired=0, visible=1, hidden=0),
        publication(["fresh"]),
        revenue(["fresh"]),
    )
    assert issues == []


def test_stale_metric_must_not_be_rendered():
    issues = checker.audit_rendered_ledger(
        html("stale", fresh=0, expired=1, visible=0, hidden=1),
        publication([], expired=1),
        revenue(["stale"]),
    )
    assert "STALE_EVENT_RENDERED:stale" in issues


def test_stale_metric_can_be_hidden_while_history_is_retained():
    issues = checker.audit_rendered_ledger(
        html(fresh=0, expired=1, visible=0, hidden=1),
        publication([], expired=1),
        revenue(["stale"]),
    )
    assert issues == []


def test_publication_contract_cannot_be_relaxed():
    artifact = publication(["fresh"])
    artifact["contract"]["freshness_gate_hours"] = 48
    issues = checker.audit_rendered_ledger(
        html("fresh", fresh=1, expired=0, visible=1, hidden=0),
        artifact,
        revenue(["fresh"]),
    )
    assert "INVALID_CONTRACT_FRESHNESS_GATE_HOURS" in issues


def test_rendered_counts_must_match_publication_boundary():
    issues = checker.audit_rendered_ledger(
        html(fresh=1, expired=0, visible=1, hidden=0),
        publication([], expired=1),
        revenue(["stale"]),
    )
    assert "RENDERED_FRESH_COUNT_MISMATCH" in issues
    assert "RENDERED_EXPIRED_COUNT_MISMATCH" in issues
    assert "RENDERED_VISIBLE_COUNT_MISMATCH" in issues
    assert "RENDERED_HIDDEN_COUNT_MISMATCH" in issues
