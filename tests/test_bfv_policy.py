from pathlib import Path


POLICY = Path(__file__).resolve().parents[1] / "AGENTS.md"


def test_bfv_policy_contains_required_contracts_and_acceptance_criteria() -> None:
    text = POLICY.read_text(encoding="utf-8")

    required_contracts = (
        "### Functional Contract",
        "### Non-Functional Contract",
        "### Operational Contract",
    )
    for contract in required_contracts:
        assert contract in text

    required_criteria = (
        "Data provenance is reproducible.",
        "Audit results can be replayed.",
        "Rollback remains possible.",
        "Observability is preserved.",
    )
    for criterion in required_criteria:
        assert criterion in text


def test_bfv_policy_keeps_deletion_test_fixed_point_and_repo_evidence() -> None:
    text = POLICY.read_text(encoding="utf-8")

    assert "A claim becomes work only when deleting it makes one acceptance criterion unprovable." in text
    assert "## 6. Fixed Point" in text

    evidence_markers = (
        "data/earnings_ledger/",
        "audit_latest.json",
        "pytest",
        ".github/workflows/",
        "git revert",
    )
    for marker in evidence_markers:
        assert marker in text
