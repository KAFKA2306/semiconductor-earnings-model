from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_earnings_ledger_markdown.py"
SPEC = importlib.util.spec_from_file_location("build_earnings_ledger_markdown", MODULE_PATH)
assert SPEC and SPEC.loader
md = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = md
SPEC.loader.exec_module(md)

RUN_AT = "2026-08-09T18:00:00Z"


def audit(**overrides):
    row = {
        "run_at": RUN_AT,
        "accepted_events_total": 1,
        "rejected_events_total": 14,
        "issues": [],
        "status": "PASS",
    }
    row.update(overrides)
    return row


def event(**overrides):
    row = {
        "event_id": "evt-1",
        "company_id": "example",
        "company_name": "Example Corp",
        "document_type": "10-Q",
        "published_at": "2026-08-09T17:00:00Z",
        "source_url": "https://example.com/primary",
        "freshness": "PASS",
    }
    row.update(overrides)
    return row


def publication(**overrides):
    row = {
        "schema_version": "earnings-ledger-publication.v1",
        "generated_from_run_at": RUN_AT,
        "audit_status": "PASS",
        "accepted_events_total": 1,
        "ledger_accepted_events_total": 1,
        "expired_events_total": 0,
        "rejected_events_total": 14,
        "unsupported_or_disabled_sources": ["disabled-source"],
        "events": [event()],
        "contract": {
            "primary_sources_only": True,
            "freshness_gate_hours": 24,
            "publication_rechecks_freshness": True,
            "fail_closed": True,
            "unverified_values_published": False,
        },
    }
    row.update(overrides)
    return row


def test_fresh_audited_event_is_rendered():
    text = md.build_markdown(publication(), audit())
    assert "Example Corp" in text
    assert "https://example.com/primary" in text
    assert "公開可能（24時間以内）: **1件**" in text


def test_zero_fresh_events_render_no_publication_message():
    pub = publication(accepted_events_total=0, expired_events_total=1, events=[])
    text = md.build_markdown(pub, audit())
    assert "24時間鮮度ゲートを通過した公開対象はありません" in text
    assert "期限切れ除外: **1件**" in text


def test_non_pass_audit_fails_closed():
    with pytest.raises(ValueError, match="ledger audit is not clean PASS"):
        md.build_markdown(publication(), audit(status="FAIL"))


def test_publication_run_must_match_audit_run():
    with pytest.raises(ValueError, match="publication/audit run mismatch"):
        md.build_markdown(publication(generated_from_run_at="2026-08-09T17:59:59Z"), audit())


def test_contract_cannot_relax_24_hour_gate():
    pub = publication()
    pub["contract"] = deepcopy(pub["contract"])
    pub["contract"]["freshness_gate_hours"] = 48
    with pytest.raises(ValueError, match="publication safety contract mismatch"):
        md.build_markdown(pub, audit())


def test_expired_event_fails_closed_even_if_artifact_claims_pass():
    pub = publication(events=[event(published_at="2026-08-08T17:59:59Z")])
    with pytest.raises(ValueError, match="expired event in publication"):
        md.build_markdown(pub, audit())


def test_exact_24_hour_boundary_is_allowed():
    pub = publication(events=[event(published_at="2026-08-08T18:00:00Z")])
    text = md.build_markdown(pub, audit())
    assert "Example Corp" in text


def test_future_event_fails_closed():
    pub = publication(events=[event(published_at="2026-08-09T18:00:01Z")])
    with pytest.raises(ValueError, match="future event in publication"):
        md.build_markdown(pub, audit())


def test_count_mismatch_fails_closed():
    with pytest.raises(ValueError, match="publication accepted event count mismatch"):
        md.build_markdown(publication(accepted_events_total=2), audit())


def test_non_https_source_fails_closed():
    pub = publication(events=[event(source_url="http://example.com/primary")])
    with pytest.raises(ValueError, match="verified HTTPS source_url missing"):
        md.build_markdown(pub, audit())


def test_duplicate_event_id_fails_closed():
    pub = publication(accepted_events_total=2, events=[event(), event()])
    with pytest.raises(ValueError, match="duplicate publication event_id"):
        md.build_markdown(pub, audit())
