from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "push_earnings_commit_with_retry.sh"


def run_with_fake_git(tmp_path: Path, behavior: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "git.log"
    state = tmp_path / "state"
    fake_git = bin_dir / "git"
    fake_git.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$FAKE_GIT_LOG"
case "${FAKE_GIT_BEHAVIOR}:$1" in
  retry:push)
    if [ ! -f "$FAKE_GIT_STATE" ]; then
      touch "$FAKE_GIT_STATE"
      exit 1
    fi
    exit 0
    ;;
  retry:fetch|retry:rebase)
    exit 0
    ;;
  conflict:push)
    exit 1
    ;;
  conflict:fetch)
    exit 0
    ;;
  conflict:rebase)
    if [ "${2:-}" = "--abort" ]; then exit 0; fi
    exit 1
    ;;
  success:push)
    exit 0
    ;;
  *)
    echo "unexpected fake git invocation: $*" >&2
    exit 97
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "FAKE_GIT_LOG": str(log),
            "FAKE_GIT_STATE": str(state),
            "FAKE_GIT_BEHAVIOR": behavior,
            "PUSH_MAX_ATTEMPTS": "3",
            "PUSH_RETRY_SLEEP_SECONDS": "0",
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    result.git_log = log.read_text(encoding="utf-8").splitlines() if log.exists() else []  # type: ignore[attr-defined]
    return result


def test_first_push_success_does_not_fetch_or_rebase(tmp_path: Path):
    result = run_with_fake_git(tmp_path, "success")
    assert result.returncode == 0
    assert result.git_log == ["push origin HEAD:main"]  # type: ignore[attr-defined]


def test_non_fast_forward_like_failure_fetches_rebases_and_retries(tmp_path: Path):
    result = run_with_fake_git(tmp_path, "retry")
    assert result.returncode == 0
    assert result.git_log == [  # type: ignore[attr-defined]
        "push origin HEAD:main",
        "fetch origin main",
        "rebase origin/main",
        "push origin HEAD:main",
    ]


def test_rebase_conflict_aborts_and_fails_closed(tmp_path: Path):
    result = run_with_fake_git(tmp_path, "conflict")
    assert result.returncode != 0
    assert result.git_log == [  # type: ignore[attr-defined]
        "push origin HEAD:main",
        "fetch origin main",
        "rebase origin/main",
        "rebase --abort",
    ]
    assert "instead of auto-resolving audited ledger data" in result.stderr


def test_invalid_retry_configuration_fails_before_git(tmp_path: Path):
    env = os.environ.copy()
    env["PUSH_MAX_ATTEMPTS"] = "0"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "positive integer" in result.stderr
