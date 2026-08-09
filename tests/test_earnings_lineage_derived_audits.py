from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_earnings_lineage_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_earnings_lineage_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
lineage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lineage)


def write(path: Path, value: object) -> None:
    if isinstance(value, dict):
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    else:
        path.write_text(str(value), encoding="utf-8")


def ledger_fixture(tmp_path: Path) -> Path:
    run_at = "2026-08-09T20:52:09Z"
    ledger = tmp_path / "data" / "earnings_ledger"
    ledger.mkdir(parents=True)
    write(ledger / "events.ndjson", '{"event_id":"a"}\n')
    write(ledger / "rejected.ndjson", '{"event_id":"b"}\n')
    write(ledger / "source_registry.json", {"sources": []})
    write(ledger / "state.json", {"last_run_at": run_at, "audit_status": "PASS"})
    write(ledger / "audit_latest.json", {"run_at": run_at, "status": "PASS", "issues": []})
    write(ledger / "publication_latest.json", {"generated_from_run_at": run_at, "audit_status": "PASS"})
    write(ledger / "source_state.json", {"generated_from_run_at": run_at})
    for name in lineage.DERIVED_AUDIT_ARTIFACTS:
        write(ledger / name, {"status": "PASS", "issues": []})
    return ledger


def test_manifest_hashes_derived_audits(tmp_path: Path):
    result = lineage.build_manifest(ledger_fixture(tmp_path))
    paths = {item["path"] for item in result["artifacts"]}
    assert result["schema_version"] == "earnings-ledger-lineage.v2"
    assert len(result["artifacts"]) == len(lineage.LINEAGE_ARTIFACTS)
    assert "data/earnings_ledger/period_normalization_latest.json" in paths
    assert result["contract"]["derived_audit_clean_pass_required"] is True


def test_missing_derived_audit_fails_closed(tmp_path: Path):
    ledger = ledger_fixture(tmp_path)
    (ledger / "period_normalization_latest.json").unlink()
    try:
        lineage.build_manifest(ledger)
    except RuntimeError as exc:
        assert "period_normalization_latest.json" in str(exc)
    else:
        raise AssertionError("missing derived audit must fail closed")


def test_failed_derived_audit_fails_closed(tmp_path: Path):
    ledger = ledger_fixture(tmp_path)
    write(ledger / "semantic_duplicate_audit_latest.json", {"status": "FAIL", "issues": []})
    try:
        lineage.build_manifest(ledger)
    except RuntimeError as exc:
        assert "derived audit is not PASS" in str(exc)
    else:
        raise AssertionError("failed derived audit must fail closed")


def test_derived_audit_issues_fail_closed(tmp_path: Path):
    ledger = ledger_fixture(tmp_path)
    write(ledger / "consensus_separation_audit_latest.json", {"status": "PASS", "issues": [{"code": "X"}]})
    try:
        lineage.build_manifest(ledger)
    except RuntimeError as exc:
        assert "derived audit has issues" in str(exc)
    else:
        raise AssertionError("dirty derived audit must fail closed")
