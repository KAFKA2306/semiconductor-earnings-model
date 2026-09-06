# Semiconductor Earnings Agent Contract

`AGENTS.md` is the only repository-wide agent instruction source. Tool-specific instruction files must not duplicate it.

## Data contract

This repository is a reproducible primary-financial-facts system.

- Preserve source identity, URL, publication/observation time, fiscal period, unit/currency, value type, evidence identifiers, and hashes when the owning schema requires them.
- Keep observed actuals, guidance, consensus, estimates, scenarios, derived values, and rejected records distinct.
- Null is not zero. Missing, stale, ambiguous, incomparable, or rejected data must remain explicit.
- Do not infer missing financial values, periods, consensus, provenance, source identity, accounting basis, currency, or scale.
- `data/earnings_ledger/` is the canonical earnings evidence boundary unless current code/schema defines another owner.
- Prefer SEC/EDGAR, TDnet/JPX, issuer IR, official APIs, or the repository's authorized provider for current primary facts.

## Execution

- Prefer current user instruction, current primary evidence, current code/schema/config/tests, then current docs/history.
- Proceed with read-only and reversible work without unnecessary confirmation.
- Use one canonical workline and one implementation for each outcome.
- Prefer deletion and consolidation over parallel ledgers, manifests, pipelines, wrappers, or provenance formats.
- Fail closed on missing sources, schema errors, hash/provenance failures, ambiguous periods/units, or failed audits.
- Do not weaken data-integrity gates merely to make CI pass.

## Verification

Run the smallest tests and audits that prove the changed data contract. Broaden only when new failures, changes, or unresolved concerns justify it.

A successful command is not the business postcondition. Verify the resulting ledger row, manifest/hash, audit result, generated artifact, API, or deployed surface that owns the claim.

CI green proves only the checks executed for that revision. Repository merge and product/data release are separate. Release requires the merged revision and the actual published/live artifact or surface to be directly verified.

## Completion

Reuse the current Issue/branch/PR where one exists. Re-read state before writes, read back after writes, and merge only the reviewed revision.

Stop when the requested data/repository/release state is directly verified. Unchecked layers remain `UNVERIFIED`.
