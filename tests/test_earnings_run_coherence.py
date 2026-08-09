import json
from pathlib import Path

from scripts.audit_earnings_run_coherence import REQUIRED, audit


RUN_AT = "2026-08-09T00:00:00Z"


def write_artifact(root: Path, name: str, *, status: str = "PASS", issues=None, schema=True) -> None:
    payload = {"status": status, "issues": [] if issues is None else issues}
    if schema:
        payload["schema_version"] = f"test-{name}.v1"
    if name == "audit_latest.json":
        payload["accepted_events_total"] = 1
        payload["run_at"] = RUN_AT
    if name == "publication_latest.json":
        payload["events_total"] = 1
        payload["generated_from_run_at"] = RUN_AT
    (root / name).write_text(json.dumps(payload), encoding="utf-8")


def valid_ledger(tmp_path: Path) -> Path:
    for name in REQUIRED:
        write_artifact(tmp_path, name)
    return tmp_path


def test_passes_when_all_required_artifacts_are_clean(tmp_path):
    result = audit(valid_ledger(tmp_path))
    assert result["status"] == "PASS"
    assert result["issues"] == []
    assert result["checked_artifacts_total"] == len(REQUIRED)


def test_fails_when_required_artifact_is_missing(tmp_path):
    valid_ledger(tmp_path)
    (tmp_path / "evidence_latest.json").unlink()
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert "MISSING_ARTIFACT:evidence_latest.json" in result["issues"]


def test_fails_when_an_artifact_is_non_pass(tmp_path):
    valid_ledger(tmp_path)
    write_artifact(tmp_path, "published_at_audit_latest.json", status="FAIL")
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert "NON_PASS_STATUS:published_at_audit_latest.json:FAIL" in result["issues"]


def test_fails_when_an_artifact_has_issues(tmp_path):
    valid_ledger(tmp_path)
    write_artifact(tmp_path, "rejection_reason_audit_latest.json", issues=["x"])
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert "ARTIFACT_HAS_ISSUES:rejection_reason_audit_latest.json:1" in result["issues"]


def test_fails_when_schema_version_is_missing(tmp_path):
    valid_ledger(tmp_path)
    write_artifact(tmp_path, "accounting_basis_audit_latest.json", schema=False)
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert "MISSING_SCHEMA_VERSION:accounting_basis_audit_latest.json" in result["issues"]


def test_fails_when_publication_ledger_count_disagrees(tmp_path):
    valid_ledger(tmp_path)
    payload = json.loads((tmp_path / "publication_latest.json").read_text())
    payload["events_total"] = 2
    (tmp_path / "publication_latest.json").write_text(json.dumps(payload))
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert "PUBLICATION_LEDGER_COUNT_MISMATCH:1:2" in result["issues"]


def test_allows_expired_events_when_counts_reconcile(tmp_path):
    valid_ledger(tmp_path)
    payload = json.loads((tmp_path / "publication_latest.json").read_text())
    payload.pop("events_total")
    payload["ledger_accepted_events_total"] = 1
    payload["accepted_events_total"] = 0
    payload["expired_events_total"] = 1
    (tmp_path / "publication_latest.json").write_text(json.dumps(payload))
    result = audit(tmp_path)
    assert result["status"] == "PASS"
    assert result["issues"] == []


def test_fails_when_freshness_counts_do_not_reconcile(tmp_path):
    valid_ledger(tmp_path)
    payload = json.loads((tmp_path / "publication_latest.json").read_text())
    payload.pop("events_total")
    payload["ledger_accepted_events_total"] = 1
    payload["accepted_events_total"] = 0
    payload["expired_events_total"] = 0
    (tmp_path / "publication_latest.json").write_text(json.dumps(payload))
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert "PUBLICATION_FRESHNESS_COUNT_MISMATCH:1:0:0" in result["issues"]


def test_fails_when_publication_is_from_a_different_ledger_run(tmp_path):
    valid_ledger(tmp_path)
    payload = json.loads((tmp_path / "publication_latest.json").read_text())
    payload["generated_from_run_at"] = "2026-08-08T22:00:00Z"
    (tmp_path / "publication_latest.json").write_text(json.dumps(payload))
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert any(issue.startswith("STALE_PUBLICATION_RUN:") for issue in result["issues"])


def test_fails_when_run_binding_metadata_is_missing(tmp_path):
    valid_ledger(tmp_path)
    ledger = json.loads((tmp_path / "audit_latest.json").read_text())
    ledger.pop("run_at")
    (tmp_path / "audit_latest.json").write_text(json.dumps(ledger))
    publication = json.loads((tmp_path / "publication_latest.json").read_text())
    publication.pop("generated_from_run_at")
    (tmp_path / "publication_latest.json").write_text(json.dumps(publication))
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert "MISSING_LEDGER_RUN_AT" in result["issues"]
    assert "MISSING_PUBLICATION_SOURCE_RUN_AT" in result["issues"]
