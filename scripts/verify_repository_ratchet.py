from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = (
    "data/earnings_ledger/README.md",
    "data/earnings_ledger/events.ndjson",
    "data/earnings_ledger/rejected.ndjson",
    "data/earnings_ledger/state.json",
    "data/earnings_ledger/audit_latest.json",
    "scripts/earnings_ledger.py",
    "docs/canonical-earnings-flow.md",
)
FORBIDDEN = (".github/workflows/weekly-repo-research.yml",)
KPIS = ("acquisition_success_rate", "freshness_pass_rate", "audit_pass_rate")


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    forbidden = [path for path in FORBIDDEN if (ROOT / path).exists()]

    contract = (ROOT / "docs/canonical-earnings-flow.md").read_text(encoding="utf-8")
    ledger_readme = (ROOT / "data/earnings_ledger/README.md").read_text(encoding="utf-8")

    errors: list[str] = []
    if missing:
        errors.append(f"missing canonical files: {missing}")
    if forbidden:
        errors.append(f"non-canonical automation reintroduced: {forbidden}")

    for token in ("events.ndjson", "rejected.ndjson", "audit_latest.json", "reports/YYYY-MM-DD.md"):
        if token not in contract or token not in ledger_readme:
            errors.append(f"canonical flow token is not documented in both contracts: {token}")

    present_kpis = [kpi for kpi in KPIS if kpi in contract]
    if len(present_kpis) != 3:
        errors.append(f"expected exactly 3 canonical KPIs, found {present_kpis}")

    if errors:
        raise SystemExit("repository ratchet failed:\n- " + "\n- ".join(errors))

    print("repository ratchet passed: canonical earnings flow and 3-KPI contract are intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
