from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_earnings_lineage_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_earnings_lineage_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
lineage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lineage
SPEC.loader.exec_module(lineage)


def write(path: Path, value: object) -> None:
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    else:
        path.write_text(str(value), encoding="utf-8")


def make_ledger(tmp_path: Path, run_at: str = "2026-08-09T10:53:11Z") -> Path:
    ledger = tmp_path / "data" / "earnings_ledger"
    ledger.mkdir(parents=True)
    write(ledger / "events.ndjson", '{"event_id":"a"}\n')
    write(ledger / "rejected.ndjson", '{"event_id":"b"}\n')
    write(ledger / "source_registry.json", {"schema_version": "source-registry.v1", "sources": []})
    write(ledger / "state.json", {"last_run_at": run_at, "audit_status": "PASS"})
    write(ledger / "audit_latest.json", {"run_at": run_at, "status": "PASS", "issues": []})
    write(
        ledger / "publication_latest.json",
        {"generated_from_run_at": run_at, "audit_status": "PASS"},
    )
    write(ledger / "source_state.json", {"generated_from_run_at": run_at})
    return ledger


def test_manifest_binds_all_core_artifacts_with_sha256(tmp_path: Path):
    ledger = make_ledger(tmp_path)
    manifest = lineage.build_manifest(ledger)
    assert manifest["status"] == "PASS"
    assert manifest["generated_from_run_at"] == "2026-08-09T10:53:11Z"
    assert len(manifest["artifacts"]) == len(lineage.CORE_ARTIFACTS)
    assert all(len(item["sha256"]) == 64 for item in manifest["artifacts"])
    assert all(item["size_bytes"] > 0 for item in manifest["artifacts"])


def test_missing_core_artifact_fails_closed(tmp_path: Path):
    ledger = make_ledger(tmp_path)
    (ledger / "rejected.ndjson").unlink()
    try:
        lineage.build_manifest(ledger)
    except RuntimeError as exc:
        assert "missing required lineage artifacts" in str(exc)
    else:
        raise AssertionError("missing artifact must fail closed")


def test_stale_publication_run_binding_fails_closed(tmp_path: Path):
    ledger = make_ledger(tmp_path)
    write(
        ledger / "publication_latest.json",
        {"generated_from_run_at": "2026-08-09T09:00:00Z", "audit_status": "PASS"},
    )
    try:
        lineage.build_manifest(ledger)
    except RuntimeError as exc:
        assert "run binding mismatch" in str(exc)
    else:
        raise AssertionError("stale publication must fail closed")


def test_stale_source_state_run_binding_fails_closed(tmp_path: Path):
    ledger = make_ledger(tmp_path)
    write(ledger / "source_state.json", {"generated_from_run_at": "2026-08-09T09:00:00Z"})
    try:
        lineage.build_manifest(ledger)
    except RuntimeError as exc:
        assert "run binding mismatch" in str(exc)
    else:
        raise AssertionError("stale source state must fail closed")


def test_dirty_ledger_audit_fails_closed(tmp_path: Path):
    ledger = make_ledger(tmp_path)
    write(
        ledger / "audit_latest.json",
        {"run_at": "2026-08-09T10:53:11Z", "status": "PASS", "issues": [{"code": "X"}]},
    )
    try:
        lineage.build_manifest(ledger)
    except RuntimeError as exc:
        assert "clean PASS" in str(exc)
    else:
        raise AssertionError("audit issues must fail closed")


def test_non_pass_publication_fails_closed(tmp_path: Path):
    ledger = make_ledger(tmp_path)
    write(
        ledger / "publication_latest.json",
        {"generated_from_run_at": "2026-08-09T10:53:11Z", "audit_status": "FAIL"},
    )
    try:
        lineage.build_manifest(ledger)
    except RuntimeError as exc:
        assert "publication audit_status is not PASS" in str(exc)
    else:
        raise AssertionError("failed publication must fail closed")
