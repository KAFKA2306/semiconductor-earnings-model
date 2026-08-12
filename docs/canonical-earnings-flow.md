# Canonical earnings flow

The earnings ledger is the only canonical state for newly published earnings evidence.

## One production line

1. **Evidence discovery** — collect only first-party earnings disclosures with a verified publication timestamp.
2. **Ledger decision** — write accepted evidence to `data/earnings_ledger/events.ndjson`; write rejected candidates once to `data/earnings_ledger/rejected.ndjson` with the rejection reason.
3. **Audit** — validate the ledger deterministically and publish the latest machine-readable result to `data/earnings_ledger/audit_latest.json`.
4. **Report** — generate `data/earnings_ledger/reports/YYYY-MM-DD.md` only from audited PASS events.

`state.json` records the collection window and counts; it is operational state, not a second event ledger. Downstream datasets, Pages views, Hugging Face exports, and analysis outputs are projections and must remain reproducible from canonical evidence/ledger state rather than becoming competing fact stores.

## Failure ownership

A candidate rejected before acceptance belongs in `rejected.ndjson`. A canonical ledger invariant that fails after acceptance belongs in `audit_latest.json` and fails closed. A failure must not be represented by a separate ad-hoc status store or reimplemented by an unrelated workflow.

## Repository KPIs

Only these three repository-level operating KPIs are canonical:

1. `acquisition_success_rate` — enabled primary-source adapters completing their scheduled collection successfully.
2. `freshness_pass_rate` — accepted events satisfying the canonical publication-time freshness gate.
3. `audit_pass_rate` — deterministic ledger audits that complete with PASS.

Unknown or unavailable measurements remain unknown; they are never converted to zero.

## CI contract

CI should directly protect this line: required canonical files exist, failure ownership remains explicit, the ledger contract is documented, and known non-canonical automation does not reappear. Product-specific downstream checks may exist, but they must not create another canonical earnings state.
