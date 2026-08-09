from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_earnings_source_state.py"
SPEC = importlib.util.spec_from_file_location("build_earnings_source_state", MODULE_PATH)
assert SPEC and SPEC.loader
source_state = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = source_state
SPEC.loader.exec_module(source_state)


def registry() -> dict:
    return {
        "sources": [
            {"id": "amd", "adapter": "sec_edgar", "enabled": True},
            {"id": "tdnet-japan-priority", "adapter": "tdnet_public", "enabled": True},
            {"id": "sk-hynix", "adapter": "opendart", "enabled": False},
        ]
    }


def audit() -> dict:
    return {
        "status": "PASS",
        "issues": [],
        "run_at": "2026-08-09T07:00:00Z",
        "source_status": [
            {"source_id": "amd", "status": "success"},
            {"source_id": "tdnet-japan-priority", "status": "success"},
            {"source_id": "sk-hynix", "status": "disabled"},
        ],
    }


def state() -> dict:
    return {"audit_status": "PASS", "last_run_at": "2026-08-09T07:00:00Z"}


def row(event_id: str, company_id: str, adapter: str, published_at: str) -> dict:
    return {
        "event_id": event_id,
        "company_id": company_id,
        "source_adapter": adapter,
        "published_at": published_at,
    }


def test_persists_latest_seen_across_accepted_and_rejected_ledgers():
    result = source_state.build_source_state(
        registry(),
        audit(),
        state(),
        [row("amd-old", "amd", "sec_edgar", "2026-08-09T04:00:00Z")],
        [
            row("amd-new", "amd", "sec_edgar", "2026-08-09T06:00:00Z"),
            row("tdnet-new", "tokyo-electron", "tdnet_public", "2026-08-09T05:00:00Z"),
        ],
    )
    by_id = {item["source_id"]: item for item in result["sources"]}
    assert by_id["amd"]["last_seen_id"] == "amd-new"
    assert by_id["amd"]["last_seen_published_at"] == "2026-08-09T06:00:00Z"
    assert by_id["amd"]["last_seen_disposition"] == "rejected"
    assert by_id["tdnet-japan-priority"]["last_seen_id"] == "tdnet-new"
    assert by_id["sk-hynix"]["last_seen_id"] is None
    assert by_id["sk-hynix"]["collection_status"] == "disabled"


def test_audit_state_run_binding_mismatch_fails_closed():
    bad_state = state()
    bad_state["last_run_at"] = "2026-08-09T06:00:00Z"
    try:
        source_state.build_source_state(registry(), audit(), bad_state, [], [])
    except RuntimeError as exc:
        assert "run binding mismatch" in str(exc)
    else:
        raise AssertionError("stale state must fail closed")


def test_failed_source_status_fails_closed():
    bad_audit = audit()
    bad_audit["source_status"][0]["status"] = "error"
    try:
        source_state.build_source_state(registry(), bad_audit, state(), [], [])
    except RuntimeError as exc:
        assert "failed source collection" in str(exc)
    else:
        raise AssertionError("failed collection must not produce source cursor state")


def test_source_status_must_cover_registry_exactly():
    bad_audit = audit()
    bad_audit["source_status"] = bad_audit["source_status"][:-1]
    try:
        source_state.build_source_state(registry(), bad_audit, state(), [], [])
    except RuntimeError as exc:
        assert "cover registry sources exactly" in str(exc)
    else:
        raise AssertionError("partial source status coverage must fail closed")


def test_unknown_adapter_mapping_fails_closed():
    try:
        source_state.build_source_state(
            registry(),
            audit(),
            state(),
            [row("x", "unknown-company", "unknown_adapter", "2026-08-09T05:00:00Z")],
            [],
        )
    except RuntimeError as exc:
        assert "cannot be mapped" in str(exc)
    else:
        raise AssertionError("unmapped ledger row must fail closed")


def test_timezone_less_timestamp_fails_closed():
    try:
        source_state.build_source_state(
            registry(),
            audit(),
            state(),
            [row("x", "amd", "sec_edgar", "2026-08-09T05:00:00")],
            [],
        )
    except RuntimeError as exc:
        assert "timezone missing" in str(exc)
    else:
        raise AssertionError("timezone-less cursor input must fail closed")


def test_future_timestamp_fails_closed():
    try:
        source_state.build_source_state(
            registry(),
            audit(),
            state(),
            [row("future", "amd", "sec_edgar", "2026-08-09T07:06:00Z")],
            [],
        )
    except RuntimeError as exc:
        assert "future published_at" in str(exc)
    else:
        raise AssertionError("future cursor input must fail closed")
