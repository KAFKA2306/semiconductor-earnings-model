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

## 3. Claim

A **Claim** is a proposed unit of work. Before implementation, state which acceptance criterion would become unprovable without that work and identify the smallest evidence needed to prove completion.

A valid Claim should identify:

- the affected contract or artifact;
- the acceptance criterion it protects;
- the smallest code/data/documentation change required;
- the verification command, test, audit artifact, or CI result that proves it.

Claims that only improve style, convenience, abstraction, or future flexibility are out of scope unless deleting them would make an acceptance criterion unprovable for the requested outcome.

## 4. Deletion Test

**A claim becomes work only when deleting it makes one acceptance criterion unprovable.**

Apply the test before implementation and again before merge. If a proposed file, refactor, dependency, abstraction, generated artifact, or documentation section can be removed while the requested outcome and all four acceptance criteria remain provable, remove it from the change.

## 5. Verification Evidence

Prefer existing repository evidence over parallel mechanisms.

- Earnings collection/provenance: `data/earnings_ledger/README.md`, `source_registry.json`, `events.ndjson`, `rejected.ndjson`, `state.json`, `audit_latest.json`, and dated reports.
- Automated checks: relevant `pytest` tests and the existing GitHub Actions workflows under `.github/workflows/`.
- Published/research datasets: use their owning schema, manifest, source metadata, hashes, and audit fields rather than inventing a second provenance format.
- Rollback: use normal version-control reversal (`git revert`) rather than destructive history rewriting for shared changes.

## 6. Fixed Point

Stop when the requested outcome is satisfied, all four acceptance criteria are provable, and every remaining change survives the Deletion Test.

At the Fixed Point:

- required tests/audits have passed or a concrete blocker is recorded;
- provenance and observability evidence remain available;
- rollback remains possible;
- no extra refactor, feature, dataset expansion, or policy change is included solely because it might be useful later.
