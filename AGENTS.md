# Semiconductor Earnings Agent Contract

`AGENTS.md` is the repository-wide agent instruction source. Tool-specific instruction files must not duplicate it.

## Data contract

This repository is a reproducible primary-financial-facts system.

- Preserve source identity, URL, publication/observation time, fiscal period, unit/currency, value type, evidence identifiers, and hashes when the owning schema requires them.
- Keep observed actuals, guidance, consensus, estimates, scenarios, derived values, and rejected records distinct.
- Null is not zero. Missing, stale, ambiguous, incomparable, or rejected data must remain explicit.
- Do not infer missing financial values, periods, consensus, provenance, source identity, accounting basis, currency, or scale.
- `data/earnings_ledger/` is the canonical earnings evidence boundary unless current code/schema defines another owner.
- Prefer SEC/EDGAR, TDnet/JPX, issuer IR, official APIs, or the repository's authorized provider for current primary facts.
- Fail closed on missing sources, schema errors, hash/provenance failures, ambiguous periods/units, or failed audits. Do not weaken data-integrity gates to make CI pass.

## Evidence boundary

A successful command is not the business postcondition. Verify the ledger row, manifest/hash, audit result, generated artifact, API, or deployed surface that owns the claim.

Repository merge and product/data release are separate. Release requires direct verification of the merged revision and actual published/live artifact or surface.


## 1. Fixed Point

A claim becomes work only when deleting it makes one acceptance criterion unprovable.

### Functional Contract

- Data provenance is reproducible.
- Canonical source identity and schema ownership remain explicit.
- Derived values never overwrite observed facts.

### Non-Functional Contract

- Audit results can be replayed.
- Observability is preserved.
- NULL remains distinct from zero and undisclosed remains explicit.

### Operational Contract

- Rollback remains possible.
- Verify data contracts with `pytest` and repository checks before merge.
- Preserve `data/earnings_ledger/` as the canonical earnings evidence boundary.
- Preserve generated `audit_latest.json` evidence where the owning workflow requires it.
- CI evidence lives under `.github/workflows/`.
- Reversible changes must remain recoverable with normal Git history, including `git revert`.
