from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cleanup_merged_branches.py"
SPEC = importlib.util.spec_from_file_location("cleanup_merged_branches", MODULE_PATH)
assert SPEC and SPEC.loader
gc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gc
SPEC.loader.exec_module(gc)

REPO = "KAFKA2306/semiconductor-earnings-model"


def decision_map(*, branches, open_heads=(), closed_heads=(), default_sha="main-sha"):
    decisions = gc.select_branch_decisions(
        branches=branches,
        default_branch="main",
        default_sha=default_sha,
        open_pr_heads=open_heads,
        closed_pr_heads=closed_heads,
        repo_full_name=REPO,
    )
    return {item.branch: (item.action, item.reason) for item in decisions}


def head(ref: str, sha: str, *, merged: bool, repo: str = REPO):
    return gc.PullRequestHead(
        ref=ref,
        sha=sha,
        merged=merged,
        repo_full_name=repo,
    )


def test_exact_merged_pr_head_is_deleted() -> None:
    result = decision_map(
        branches=[gc.Branch("main", "main-sha"), gc.Branch("agent/done", "abc")],
        closed_heads=[head("agent/done", "abc", merged=True)],
    )
    assert result["agent/done"] == ("delete", "exact_merged_pr_head")


def test_open_pr_always_preserves_branch() -> None:
    result = decision_map(
        branches=[gc.Branch("main", "main-sha"), gc.Branch("feat/live", "abc")],
        open_heads=[head("feat/live", "abc", merged=False)],
        closed_heads=[head("feat/live", "abc", merged=True)],
    )
    assert result["feat/live"] == ("keep", "open_pull_request")


def test_protected_branch_is_never_deleted() -> None:
    result = decision_map(
        branches=[
            gc.Branch("main", "main-sha"),
            gc.Branch("fix/protected", "abc", protected=True),
        ],
        closed_heads=[head("fix/protected", "abc", merged=True)],
    )
    assert result["fix/protected"] == ("keep", "protected")


def test_ephemeral_branch_equal_to_default_is_safe_to_delete() -> None:
    result = decision_map(
        branches=[
            gc.Branch("main", "main-sha"),
            gc.Branch("agent/reset-after-merge", "main-sha"),
        ]
    )
    assert result["agent/reset-after-merge"] == ("delete", "same_as_default")


def test_unmerged_ephemeral_branch_without_proof_is_preserved() -> None:
    result = decision_map(
        branches=[gc.Branch("main", "main-sha"), gc.Branch("agent/wip", "abc")],
        closed_heads=[head("agent/wip", "abc", merged=False)],
    )
    assert result["agent/wip"] == ("keep", "no_merge_proof")


def test_ancestry_proof_upgrades_only_unresolved_branch() -> None:
    decisions = [
        gc.Decision("agent/old", "old-sha", "keep", "no_merge_proof"),
        gc.Decision("agent/live", "live-sha", "keep", "open_pull_request"),
        gc.Decision("main", "main-sha", "keep", "default_branch"),
    ]
    result = {
        item.branch: (item.action, item.reason)
        for item in gc.apply_ancestry_proof(decisions, ancestor_shas={"old-sha", "live-sha", "main-sha"})
    }
    assert result["agent/old"] == ("delete", "ancestor_of_default")
    assert result["agent/live"] == ("keep", "open_pull_request")
    assert result["main"] == ("keep", "default_branch")


def test_no_ancestry_proof_keeps_unresolved_branch() -> None:
    decisions = [gc.Decision("agent/diverged", "abc", "keep", "no_merge_proof")]
    result = gc.apply_ancestry_proof(decisions, ancestor_shas=set())
    assert result[0] == gc.Decision("agent/diverged", "abc", "keep", "no_merge_proof")


def test_long_lived_prefix_is_preserved_even_if_merged() -> None:
    result = decision_map(
        branches=[gc.Branch("main", "main-sha"), gc.Branch("release/2026", "abc")],
        closed_heads=[head("release/2026", "abc", merged=True)],
    )
    assert result["release/2026"] == ("keep", "non_ephemeral_prefix")


def test_foreign_fork_pr_does_not_authorize_deletion() -> None:
    result = decision_map(
        branches=[gc.Branch("main", "main-sha"), gc.Branch("fix/name", "abc")],
        closed_heads=[
            head("fix/name", "abc", merged=True, repo="someone/fork"),
        ],
    )
    assert result["fix/name"] == ("keep", "no_merge_proof")
