# AGENTS.md — BFV Kernel

> Bound the work. Falsify necessity. Verify the Contract. Stop at the Fixed Point.

BFV means **Bounded Falsification & Verification**. This file defines the repository-level operating policy for agent changes. The Contract is both the minimum required result and the maximum allowed scope.

## 1. Contract

### Functional Contract

Changes must preserve the repository as a reproducible primary-financial-facts system.

- Treat versioned repository data and documented primary-source adapters as the canonical inputs.
- Preserve source URL, observation/publication time, fiscal period, unit/currency, value type, evidence identifiers, and hashes when those fields exist in the relevant contract.
- Do not infer or fabricate missing publication times, fiscal periods, financial values, consensus values, provenance, or source identity.
- Keep accepted, rejected, derived, estimated, scenario, and observed facts distinguishable according to the schema that owns them.

### Non-Functional Contract

Changes must remain deterministic, traceable, testable, and fail closed.

- The same versioned inputs and code revision must be sufficient to replay deterministic transforms and audits.
- Schema or calculation changes require regression evidence appropriate to the affected contract.
- A failed primary-source adapter, provenance check, schema check, or audit must not silently produce a successful canonical update.
- Do not weaken existing data-integrity, security, provenance, or publication gates merely to make CI green.

### Operational Contract

Changes must use the repository's existing verification and evidence surfaces.

- Use pull-request review for repository changes and preserve commit history needed for audit and rollback.
- Run the relevant `pytest` suites and repository audit/build commands for the files changed.
- Preserve `data/earnings_ledger/` evidence, including `events.ndjson`, `rejected.ndjson`, `state.json`, `audit_latest.json`, and dated reports when that pipeline is affected.
- Publish or commit generated canonical outputs only after their existing audit gates pass.
- Preserve CI status, audit output, structured failure reasons, and logs needed to diagnose a failed run.

## 2. Mandatory Acceptance Criteria

Every change must keep all four criteria provable:

1. **Data provenance is reproducible.** A reviewer can trace a material published fact or generated value to the versioned input/source metadata required by its owning contract.
2. **Audit results can be replayed.** The repository records enough versioned inputs, code, commands/tests, and audit artifacts to rerun the relevant deterministic checks.
3. **Rollback remains possible.** A repository change can be reversed without rewriting shared history; prefer a normal Git revert of the relevant commit/PR and regenerate derived artifacts from versioned inputs when needed.
4. **Observability is preserved.** CI results and the applicable audit/state/report artifacts continue to expose success, failure, counts, and reason codes rather than hiding them.

## 3. Source-of-Truth Precedence

When sources disagree, use this order:

1. current primary-source response or versioned raw evidence required by the owning contract;
2. canonical repository ledgers and manifests, especially `data/earnings_ledger/`;
3. current executable code, schemas, configuration, and deterministic audit logic;
4. CI results and generated evidence bound to the exact commit SHA;
5. current documentation and ADRs;
6. Issue/PR prose and historical reports;
7. inference.

Never let stale prose override current executable or versioned evidence. Do not repair a discrepancy by rewriting historical evidence to match a newer interpretation.

## 4. Claim Provenance

Every material statement made while operating the repository must be classified mentally as one of:

- **VERIFIED** — directly observed from a primary source, repository file, command result, artifact, API response, or CI run.
- **OBSERVED** — explicitly provided by the user or task contract.
- **INFERRED** — a hypothesis derived from verified/observed evidence; identify it as inference when reporting it.
- **UNVERIFIED** — not inspected yet; never present it as fact.
- **FABRICATED** — forbidden.

A command returning successfully does not prove the business outcome. Verify the owning postcondition: persisted ledger row, manifest hash, audit result, deployed endpoint, or other contract-specific evidence.

## 5. Canonical Workline Rule

Before creating work, inspect current PRs, branches, Issues, CI, and the relevant canonical artifacts.

Priority:

1. continue an existing canonical open PR/head branch for the same outcome;
2. otherwise continue the unresolved Issue that owns the gap and create exactly one bounded branch + PR if code/data changes are required;
3. never create an untracked work branch or a second branch/PR for the same outcome.

Do not create duplicate branches, PRs, manifests, ledgers, or alternative pipelines for the same outcome. If an older workline is clearly superseded, consolidate to one canonical line and close/delete the duplicate when safe.

## 6. Branch Lifecycle

Aside from the repository default branch and unavoidable platform-managed/protected branches, a persistent branch is permitted only while it is the head branch of a currently open PR.

- Creating a branch creates an obligation to open or reuse its canonical PR immediately.
- Do not use branches as backlog, continuation state, backup, archive, release-waiting state, evidence storage, or historical marker. Git commits/PRs and canonical artifacts preserve history.
- After a PR is merged or closed, delete its head branch after verifying PR/main state.
- A branch with no open PR is an orphan and must be deleted.
- Before starting and before reporting completion, compare non-default branches with currently open PR heads. Any unmatched task branch is a cleanup failure.
- Do not report the repository at fixed point while an orphan task branch remains.
- If the available GitHub surface cannot delete a branch, record that as a tooling blocker and leave cleanup explicitly incomplete. Never create, preserve, rename, or move another orphan branch as a workaround.

## 7. Claim

A **Claim** is a proposed unit of work. Before implementation, state which acceptance criterion would become unprovable without that work and identify the smallest evidence needed to prove completion.

A valid Claim should identify:

- the affected contract or artifact;
- the acceptance criterion it protects;
- the smallest code/data/documentation change required;
- the verification command, test, audit artifact, or CI result that proves it.

Claims that only improve style, convenience, abstraction, or future flexibility are out of scope unless deleting them would make an acceptance criterion unprovable for the requested outcome.

## 8. Deletion Test

**A claim becomes work only when deleting it makes one acceptance criterion unprovable.**

Apply the test before implementation and again before merge. If a proposed file, refactor, dependency, abstraction, generated artifact, or documentation section can be removed while the requested outcome and all four acceptance criteria remain provable, remove it from the change.

## 9. Investigation Before Implementation

Before editing a financial/data contract:

1. inspect the relevant Issue/PR/branch and latest base SHA;
2. inspect the owning schema, canonical ledger/manifest, producer, consumer, and audit;
3. inspect existing regression tests and GitHub Actions gates;
4. inspect primary-source documentation or current provider behavior when external semantics are involved;
5. determine whether the target is canonical evidence or a generated projection;
6. identify the exact postcondition that will prove completion.

Do not design from README prose, screenshots, file names, or memory alone when the underlying evidence is inspectable.

## 10. Data and Calculation Boundaries

- `data/earnings_ledger/` is the canonical earnings evidence boundary unless an owning contract explicitly defines another canonical source.
- Adapters must not silently recompute financial values already owned by the canonical service/ledger layer.
- A derived metric must retain its formula/basis and traceable inputs.
- Null is not zero. Missing, unavailable, incomparable, ambiguous, stale, or rejected values must remain distinguishable with explicit reason semantics.
- Actuals, guidance, consensus, estimates, scenarios, and market observations must not cross value-type boundaries implicitly.
- Period, consolidation basis, accounting standard, currency, scale, and unit comparability must be proven before comparison.

## 11. Primary-Source and External-Data Rule

For current external facts, use the repository's documented primary-source/provider surface and verify the exact response used.

- Prefer SEC/EDGAR, TDnet/JPX, issuer IR, official public-data APIs, or the explicitly authorized provider for the owning dataset.
- Do not upgrade a secondary summary into canonical primary evidence.
- If a provider projection disagrees with raw filing text, preserve the discrepancy and fail closed rather than reconstructing missing rows heuristically.
- Record source URL/identifier, relevant timestamps, hashes/fingerprints, and provider revision/as-of fields when required by the owning contract.

## 12. Verification Evidence

Prefer existing repository evidence over parallel mechanisms.

- Earnings collection/provenance: `data/earnings_ledger/README.md`, `source_registry.json`, `events.ndjson`, `rejected.ndjson`, `state.json`, `audit_latest.json`, and dated reports.
- Automated checks: relevant `pytest` tests and the existing GitHub Actions workflows under `.github/workflows/`.
- Data Platform Standard: `config/data_platform_standard.json`, `scripts/check_data_platform_standard.py`, and MCP contract checks.
- Published/research datasets: use their owning schema, manifest, source metadata, hashes, and audit fields rather than inventing a second provenance format.
- Rollback: use normal version-control reversal (`git revert`) rather than destructive history rewriting for shared changes.

The README documents a broad local validation surface. Run the smallest relevant subset first, then escalate when the affected contract requires it. A repository-wide change may require `uv run python -m pytest -q`, data-platform checks, site unit audits, and a production-equivalent site build.

## 13. Builder / Auditor Separation

Treat implementation and acceptance as separate phases even when one agent performs both sequentially.

### Builder

The Builder may modify code, schemas, tests, data projections, docs, workflows, and canonical artifacts only within the bounded Contract.

### Auditor

The Auditor independently checks:

- the requested outcome exists;
- canonical evidence was not fabricated or rewritten improperly;
- deterministic acceptance checks pass;
- evidence belongs to the current PR head/base SHA;
- generated outputs match their manifests/hashes where applicable;
- no source/value-type/unit/period boundary was weakened;
- every non-default task branch is the head of a currently open PR;
- cleanup is complete with no orphan branch remaining.

Implementation intent is never audit evidence.

## 14. Fail-Closed Rule

A missing source, stale source, ambiguous period, unsupported unit, schema failure, hash mismatch, provenance failure, provider timeout, audit crash, or deployment verification failure blocks the corresponding update.

Do not:

- fill an unknown financial value with a plausible value;
- relabel immutable historical rejections merely to satisfy a new enum;
- suppress a failed audit to keep CI green;
- publish a partial projection as complete without explicit coverage state;
- substitute a different dataset for the exact dataset required by the contract without recording that change as a new contract.

## 15. PR Merge and Product/Data Release Are Separate

Do not use one gate for repository integration and external release.

### PR merge conditions

A PR may merge when all repository-local acceptance criteria for the bounded change are provable on the exact reviewed head revision:

- relevant deterministic tests/audits/builds pass;
- provenance, value-type, period, unit/currency and schema boundaries remain correct;
- generated repository artifacts are reproducible when affected;
- no unresolved review, data-integrity, security, or correctness blocker remains.

A future filing or official observation, live external-provider success after merge, production deployment, public traffic, downstream consumer adoption, or other release-only evidence is **not** a merge condition unless the PR itself changes the release mechanism and that mechanism must be validated before merge.

### Product/data release conditions

Release is a separate post-merge decision. Treat an earnings dataset, API, site, model, research output, or other external surface as released only after:

- the merged `main` revision is read back;
- the release artifact/surface is bound to that merged revision or its versioned canonical evidence;
- every release surface in scope is directly verified, such as a live primary-source collection, deployment URL/API, published dataset/model, manifest/hash, or publication receipt;
- rollback/rebuild/recovery expectations required by the owning contract remain valid.

A merged PR does not prove release. A release/live-source/deployment blocker does not retroactively invalidate a correctly merged repository change. Do not invent custom state names; report `merged` and `released` separately with direct evidence.

## 16. Git / PR / CI Protocol

For repository changes:

1. start from the latest intended base;
2. reuse the head branch of the canonical open PR if one exists;
3. otherwise create one descriptive branch and open its PR immediately in the same workline;
4. never leave a newly created work branch without an open PR;
5. keep the diff limited by the Contract and Deletion Test;
6. add/update regression evidence with behavior or schema changes;
7. verify CI on the exact PR head SHA;
8. inspect failed jobs and root causes rather than retrying blindly;
9. merge when the PR merge conditions are provable;
10. verify the merged `main` SHA;
11. delete the merged PR head branch immediately; if the PR is closed without merge, delete its head branch after verifying the close state;
12. if release is in scope, execute and verify the separate release conditions against the merged revision without retaining the merged head branch;
13. close the owning Issue only when the Issue's actual outcome is complete; an Issue may legitimately remain open after merge when release or external acceptance remains outstanding;
14. perform a final branch-vs-open-PR audit and remove every orphan task branch before claiming cleanup/fixed point.

If a host-side safety system rejects a GitHub write, re-fetch current state and retry the exact canonical action once. Do not create a duplicate branch/PR or weaken the action as a workaround. If branch deletion is unsupported by the available tool, report cleanup blocked rather than preserving the orphan as normal state.

## 17. Publication and Irreversible Side Effects

Publishing to GitHub Pages, Hugging Face, external APIs, or other remote stores requires explicit contract authority and postcondition evidence.

- Publication/release happens after the merge contract unless the bounded change explicitly requires a pre-merge release-mechanism validation.
- A successful build is not proof of successful publication.
- A dispatch is not proof of successful publication.
- Verify the remote artifact/revision/URL when the contract requires external publication.
- Preserve publication receipts, manifest hashes, source revision binding, or equivalent evidence.
- Never publish from a moving/unverified source revision when the publisher contract expects an exact SHA.

## 18. Cleanup Is Part of Completion

Before final reporting, inspect for residue created by the work:

- temporary/staging files;
- debug output;
- obsolete generated intermediates;
- superseded PRs;
- any non-default branch that is not the head of a currently open PR;
- stale Issue state;
- duplicate manifests or alternate state stores;
- CI helper artifacts that are not part of the final contract.

Do not delete unrelated valid work. Open PR head branches are valid work; merged/closed PR heads and branches with no open PR are not. If a blocker remains, keep continuation in exactly one canonical Issue/open PR and record the blocker plus next action there, never in an orphan branch.

## 19. Fixed Point

Stop when the bounded repository-local outcome is satisfied, all four acceptance criteria relevant to merge are provable, and every remaining change survives the Deletion Test.

At the merge fixed point:

- required deterministic tests/audits have passed or a concrete merge blocker is recorded;
- provenance and observability evidence remain available;
- rollback remains possible;
- exact-head CI is verified when applicable;
- linked PR state is correct;
- every persistent non-default task branch is the head of a currently open PR; no orphan branch remains;
- task-created residue is cleaned up or an explicit connector/tooling blocker is recorded.

If release is in scope, continue only through the separate release conditions. A release blocker leaves the merged repository change valid and must be reported separately. A release wait never justifies retaining a merged PR head branch. No extra refactor, feature, dataset expansion, or policy change is included solely because it might be useful later.

## 20. Final Report Contract

Report only verified state relevant to the task:

- target Issue/PR/repository URL;
- bounded change;
- tests/audits and exact result;
- PR/commit/merge SHA;
- `merged`: yes/no with direct repository evidence;
- `released`: yes/no with direct publication/deployment/live-source evidence when release is in scope;
- branch cleanup: orphan branches removed/remaining and any branch-deletion tooling blocker;
- external publication receipt when applicable;
- cleanup performed;
- blocker and exact next action if unfinished.

Do not use completion theater or unsupported confidence. If evidence is absent, say so.
