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

## dbt responsibility

dbt is a first-class repository responsibility for reproducible analytical transformation, not a second source of truth.

- Source acquisition, source verification, raw snapshots, and canonical identity remain upstream responsibilities.
- dbt owns reproducible Silver-to-Gold transformation where analytical normalization or joining is required.
- dbt owns model-level data-quality tests, lineage metadata, generated docs/catalog artifacts, and CI checks for those transformations.
- New analytical marts must preserve evidence lineage and must not overwrite or silently reinterpret observed facts.
- UI, API, Google Sheets, and BI consumers must not independently reimplement business transformations already owned by a tested Gold model.
- A dbt failure must fail the affected analytical/publication path closed. Do not weaken provenance, period, unit, or verification requirements to obtain a green build.
- Prefer additive models and explicit context joins over causal labels unless causality is separately evidenced.

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

## Outcome-first task interpretation (Altitude / Depth / Range / Speed)

- **Altitude:** Interpret a task as a verifiable user outcome, not only the named intermediate step. Infer the smallest justified acceptance criteria from the request and current repository state; do not silently expand scope or override explicit instructions.
- **Depth:** Use primary/current evidence and real domain tools and methods. Verify the actual postcondition independently of agent self-report, preferably on the exact changed revision or target runtime.
- **Range:** Combine code, data, tests, runtime/UI, and domain expertise when that materially improves the outcome, while respecting canonical owners and avoiding duplicate systems.
- **Speed:** Complete authorized read-only and reversible work through implementation, focused checks, and read-back without unnecessary approval loops. Bound retries and stop at the proven outcome.
- These principles never bypass repository-specific security, privacy, permission, publication, spending, destructive-action, or release boundaries. State verified results and any remaining `UNVERIFIED` layers.

## Revenue-first decisions and hypothesis independence

- The ultimate product/business objective is **maximize realized net revenue/profit**, subject to law, security, data licensing, privacy, user constraints, and the repository's evidence and data-integrity contracts. Features, code volume, model novelty, traffic, and visual polish are means, not ends.
- Prioritize hypotheses that can be tested through payment intent or actual purchases. Record pricing, conversions, refunds, external costs, maintenance effort, and observation windows; never label projected revenue as realized revenue.
- Keep the user-defined outcome and constraints separate from the user's proposed cause, edit location, technology, or solution. Treat those suggestions as hypotheses, not verified facts or implicit acceptance criteria.
- Before implementing a proposed fix, inspect the relevant code, logs, primary evidence, and tests. If the suggestion is wrong, explain the evidence briefly and implement the smallest authorized alternative that delivers the stated outcome.
- Avoid blindly agreeing with or reflexively rejecting the user's suggestion. Evaluate with independently falsifiable evidence. Include at least one misleading-suggestion case in evaluation when materially changing agent instructions.
- Do not dilute fail-closed provenance, unit, license, or security checks to accelerate monetization. Follow the revenue-validation work tracked in #231.

## UX purpose: elicit valuable user hypotheses

- UI/UX exists to help users formulate **high-quality, testable work/analysis hypotheses** that can lead to economic value, not merely to increase engagement or visual polish.
- Show a guided path from **observation → question → hypothesis → required evidence → falsification → next action → measurable outcome**. Preserve the user's agency: hypotheses remain user-authored or explicitly labeled AI suggestions.
- Use real source-linked data, comparisons, missing-data notices, and counterexamples to help the user discover non-obvious opportunities. Never present inferred causes or investment outcomes as established facts.
- Lower effort to inspect alternative explanations and revise or discard a hypothesis; avoid leading questions that simply confirm the user's first guess.
- Evaluate UX by usable hypotheses, completed independent checks, decisions taken, and ultimately **realized profit**, rather than screen count, clicks, or time spent. Avoid collecting unnecessary personal information.
- Before building a new widget, state the user hypothesis it enables, how it will be checked, and what economic decision it could improve. Prefer a minimal interaction experiment over a large speculative redesign.
