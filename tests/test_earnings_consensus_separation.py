from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_earnings_consensus_separation.py"
SPEC = importlib.util.spec_from_file_location("consensus_separation", MODULE_PATH)
assert SPEC and SPEC.loader
consensus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(consensus)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_current_actual_only_artifacts_are_consensus_free():
    payload = consensus.audit_artifacts()
    assert payload["status"] == "PASS"
    assert payload["issues"] == []
    assert payload["checked_artifacts_total"] == len(consensus.ACTUAL_ONLY_ARTIFACTS)


def test_consensus_key_is_rejected_fail_closed(tmp_path: Path):
    artifact = tmp_path / "actual.json"
    write_json(artifact, {"metric": "revenue", "consensus_revenue": 123})
    payload = consensus.audit_artifacts((artifact,))
    assert payload["status"] == "FAIL"
    assert payload["issues"][0]["code"] == "CONSENSUS_FIELD_IN_ACTUAL_ONLY_ARTIFACT"
    assert payload["issues"][0]["matched_token"] == "consensus"


def test_nested_estimate_key_is_rejected(tmp_path: Path):
    artifact = tmp_path / "actual.json"
    write_json(artifact, {"events": [{"metrics": {"analyst_estimate": 10}}]})
    payload = consensus.audit_artifacts((artifact,))
    assert payload["status"] == "FAIL"
    assert any(issue["matched_token"] == "estimate" for issue in payload["issues"])
    assert any("events[0].metrics.analyst_estimate" in issue["key_path"] for issue in payload["issues"])


def test_consensus_words_in_provenance_values_do_not_trigger(tmp_path: Path):
    artifact = tmp_path / "actual.json"
    write_json(
        artifact,
        {
            "contract": "Consensus values require a separate source contract.",
            "source_url": "https://example.invalid/actual",
        },
    )
    payload = consensus.audit_artifacts((artifact,))
    assert payload["status"] == "PASS"


def test_missing_actual_only_artifact_fails_closed(tmp_path: Path):
    payload = consensus.audit_artifacts((tmp_path / "missing.json",))
    assert payload["status"] == "FAIL"
    assert payload["issues"] == [
        {
            "code": "ACTUAL_ONLY_ARTIFACT_MISSING",
            "artifact": str(tmp_path / "missing.json"),
        }
    ]


def test_forbidden_tokens_cover_consensus_and_expectation_language():
    required = {"consensus", "estimate", "expected", "forecast", "analyst", "beat", "miss", "surprise"}
    assert required.issubset(set(consensus.FORBIDDEN_KEY_TOKENS))
