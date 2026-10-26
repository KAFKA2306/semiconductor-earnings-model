#!/usr/bin/env bash
set -euo pipefail

remote="${PUSH_REMOTE:-origin}"
branch="${PUSH_BRANCH:-main}"
max_attempts="${PUSH_MAX_ATTEMPTS:-3}"
sleep_seconds="${PUSH_RETRY_SLEEP_SECONDS:-5}"

if ! [[ "$max_attempts" =~ ^[1-9][0-9]*$ ]]; then
  echo "PUSH_MAX_ATTEMPTS must be a positive integer" >&2
  exit 2
fi
if ! [[ "$sleep_seconds" =~ ^[0-9]+$ ]]; then
  echo "PUSH_RETRY_SLEEP_SECONDS must be a non-negative integer" >&2
  exit 2
fi

for ((attempt=1; attempt<=max_attempts; attempt++)); do
  echo "ledger push attempt ${attempt}/${max_attempts}"
  if git push "$remote" "HEAD:${branch}"; then
    exit 0
  fi

  if (( attempt == max_attempts )); then
    echo "ledger push failed after ${max_attempts} attempts" >&2
    exit 1
  fi

  echo "push rejected; fetching ${remote}/${branch} before a fail-closed rebase" >&2
  git fetch "$remote" "$branch"

  # A successful rebase does not make an artifact built from stale inputs valid.
  # Reject upstream input changes rather than publishing a mismatched snapshot.
  if [[ -n "${PUSH_GUARD_PATHS:-}" ]]; then
    read -r -a guard_paths <<< "$PUSH_GUARD_PATHS"
    if ! git diff --quiet HEAD^ "${remote}/${branch}" -- "${guard_paths[@]}"; then
      echo "upstream guarded inputs changed; refusing to rebase stale derived data" >&2
      exit 1
    fi
  fi

  if ! git rebase "${remote}/${branch}"; then
    echo "rebase conflicted; aborting instead of auto-resolving audited ledger data" >&2
    git rebase --abort >/dev/null 2>&1 || true
    exit 1
  fi

  if (( sleep_seconds > 0 )); then
    sleep "$sleep_seconds"
  fi
done
