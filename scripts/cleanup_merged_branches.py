from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

EPHEMERAL_PREFIXES = (
    "agent/",
    "audit/",
    "chore/",
    "ci/",
    "design/",
    "docs/",
    "feat/",
    "fix/",
    "refactor/",
    "test/",
)


@dataclass(frozen=True)
class Branch:
    name: str
    sha: str
    protected: bool = False


@dataclass(frozen=True)
class PullRequestHead:
    ref: str
    sha: str
    merged: bool
    repo_full_name: str | None


@dataclass(frozen=True)
class Decision:
    branch: str
    sha: str
    action: str
    reason: str


def select_branch_decisions(
    *,
    branches: Iterable[Branch],
    default_branch: str,
    default_sha: str,
    open_pr_heads: Iterable[PullRequestHead],
    closed_pr_heads: Iterable[PullRequestHead],
    repo_full_name: str,
    prefixes: tuple[str, ...] = EPHEMERAL_PREFIXES,
) -> list[Decision]:
    open_refs = {
        head.ref
        for head in open_pr_heads
        if head.repo_full_name == repo_full_name
    }
    merged_heads: dict[str, set[str]] = {}
    for head in closed_pr_heads:
        if not head.merged or head.repo_full_name != repo_full_name:
            continue
        merged_heads.setdefault(head.ref, set()).add(head.sha)

    decisions: list[Decision] = []
    for branch in sorted(branches, key=lambda item: item.name):
        if branch.name == default_branch:
            decisions.append(
                Decision(branch.name, branch.sha, "keep", "default_branch")
            )
            continue
        if branch.protected:
            decisions.append(
                Decision(branch.name, branch.sha, "keep", "protected")
            )
            continue
        if not branch.name.startswith(prefixes):
            decisions.append(
                Decision(branch.name, branch.sha, "keep", "non_ephemeral_prefix")
            )
            continue
        if branch.name in open_refs:
            decisions.append(
                Decision(branch.name, branch.sha, "keep", "open_pull_request")
            )
            continue
        if branch.sha == default_sha:
            decisions.append(
                Decision(branch.name, branch.sha, "delete", "same_as_default")
            )
            continue
        if branch.sha in merged_heads.get(branch.name, set()):
            decisions.append(
                Decision(branch.name, branch.sha, "delete", "exact_merged_pr_head")
            )
            continue
        decisions.append(
            Decision(branch.name, branch.sha, "keep", "no_merge_proof")
        )
    return decisions


def apply_ancestry_proof(
    decisions: Iterable[Decision], *, ancestor_shas: set[str]
) -> list[Decision]:
    """Upgrade only unresolved ephemeral branches with exact ancestry proof.

    The caller must establish that every SHA in ``ancestor_shas`` is the merge
    base of ``sha...default`` with zero commits behind. Open/protected/default
    decisions are never reconsidered here.
    """

    upgraded: list[Decision] = []
    for decision in decisions:
        if decision.reason == "no_merge_proof" and decision.sha in ancestor_shas:
            upgraded.append(
                replace(decision, action="delete", reason="ancestor_of_default")
            )
        else:
            upgraded.append(decision)
    return upgraded


class GitHubApi:
    def __init__(self, *, repo: str, token: str) -> None:
        self.repo = repo
        self.token = token
        self.base = f"https://api.github.com/repos/{repo}"

    def _request(self, path: str, *, method: str = "GET") -> Any:
        request = urllib.request.Request(
            f"{self.base}{path}",
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "kafka2306-residue-free-branch-gc",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API {method} {path} failed: HTTP {exc.code}: {detail}"
            ) from exc
        if not body:
            return None
        return json.loads(body)

    def get_repo(self) -> dict[str, Any]:
        return self._request("")

    def paged(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        page = 1
        while True:
            chunk = self._request(f"{path}{separator}per_page=100&page={page}")
            if not isinstance(chunk, list):
                raise RuntimeError(f"expected list from GitHub API path {path}")
            items.extend(chunk)
            if len(chunk) < 100:
                return items
            page += 1

    def branches(self) -> list[Branch]:
        return [
            Branch(
                name=item["name"],
                sha=item["commit"]["sha"],
                protected=bool(item.get("protected", False)),
            )
            for item in self.paged("/branches")
        ]

    def pull_heads(self, *, state: str) -> list[PullRequestHead]:
        pulls = self.paged(f"/pulls?state={state}")
        result: list[PullRequestHead] = []
        for pull in pulls:
            head = pull.get("head") or {}
            head_repo = head.get("repo") or {}
            result.append(
                PullRequestHead(
                    ref=str(head.get("ref", "")),
                    sha=str(head.get("sha", "")),
                    merged=bool(pull.get("merged_at")),
                    repo_full_name=head_repo.get("full_name"),
                )
            )
        return result

    def is_ancestor(self, candidate_sha: str, default_sha: str) -> bool:
        """Return true only when GitHub proves candidate is contained in default."""

        candidate = urllib.parse.quote(candidate_sha, safe="")
        default = urllib.parse.quote(default_sha, safe="")
        payload = self._request(f"/compare/{candidate}...{default}")
        if not isinstance(payload, dict):
            return False
        merge_base = payload.get("merge_base_commit") or {}
        return (
            merge_base.get("sha") == candidate_sha
            and payload.get("behind_by") == 0
            and payload.get("status") in {"ahead", "identical"}
        )

    def delete_branch(self, branch: str) -> None:
        ref = urllib.parse.quote(f"heads/{branch}", safe="/")
        self._request(f"/git/refs/{ref}", method="DELETE")


def run(*, apply: bool, repo: str, token: str) -> int:
    api = GitHubApi(repo=repo, token=token)
    metadata = api.get_repo()
    default_branch = str(metadata["default_branch"])
    branches = api.branches()
    by_name = {branch.name: branch for branch in branches}
    if default_branch not in by_name:
        raise RuntimeError(f"default branch {default_branch!r} missing from branch list")
    default_sha = by_name[default_branch].sha

    decisions = select_branch_decisions(
        branches=branches,
        default_branch=default_branch,
        default_sha=default_sha,
        open_pr_heads=api.pull_heads(state="open"),
        closed_pr_heads=api.pull_heads(state="closed"),
        repo_full_name=repo,
    )

    unresolved_shas = {
        decision.sha
        for decision in decisions
        if decision.reason == "no_merge_proof"
    }
    ancestor_shas: set[str] = set()
    for sha in sorted(unresolved_shas):
        try:
            if api.is_ancestor(sha, default_sha):
                ancestor_shas.add(sha)
        except RuntimeError as exc:
            # A failed proof must preserve the branch, not turn into authority
            # to delete it. Surface the failure in logs for later audit.
            print(f"ANCESTRY_PROOF_UNAVAILABLE {sha}: {exc}", file=sys.stderr)

    decisions = apply_ancestry_proof(decisions, ancestor_shas=ancestor_shas)
    deletions = [item for item in decisions if item.action == "delete"]

    for decision in decisions:
        print(
            json.dumps(
                {
                    "branch": decision.branch,
                    "sha": decision.sha,
                    "action": decision.action,
                    "reason": decision.reason,
                },
                sort_keys=True,
            )
        )

    if apply:
        for decision in deletions:
            api.delete_branch(decision.branch)
            print(f"DELETED {decision.branch} {decision.reason}")

    print(
        json.dumps(
            {
                "mode": "apply" if apply else "dry-run",
                "branch_count": len(decisions),
                "delete_count": len(deletions),
            },
            sort_keys=True,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete only proven-merged or default-contained ephemeral GitHub branches."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not args.repo:
        print("repository is required via --repo or GITHUB_REPOSITORY", file=sys.stderr)
        return 2
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    return run(apply=args.apply, repo=args.repo, token=token)


if __name__ == "__main__":
    raise SystemExit(main())
