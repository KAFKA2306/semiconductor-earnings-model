#!/usr/bin/env python3
"""Fail closed when the latest earnings-ledger audit artifacts are not coherent."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "earnings_ledger"
OUTPUT = LEDGER / "run_coherence_audit_latest.json"

REQUIRED = (
    "source_registry_audit_latest.json",
    "audit_latest.json",
    "rejection_reason_audit_latest.json",
    "semantic_duplicate_audit_latest.json",
    "period_normalization_latest.json",
    "accounting_basis_audit_latest.json",
    "published_at_audit_latest.json",
    "evidence_latest.json",
    "consensus_separation_audit_latest.json",
    "publication_latest.json",
)


def audit(ledger: Path = LEDGER) -> dict:
    issues: list[str] = []
    artifacts: list[dict] = []

    for name in REQUIRED:
        path = ledger / name
        if not path.is_file():
            issues.append(f"MISSING_ARTIFACT:{name}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"INVALID_JSON:{name}:{type(exc).__name__}")
            continue

        status = payload.get("status", payload.get("audit_status"))
        artifact_issues = payload.get("issues", [])
        schema_version = payload.get("schema_version")
        if status != "PASS":
            issues.append(f"NON_PASS_STATUS:{name}:{status}")
        if not isinstance(artifact_issues, list):
            issues.append(f"INVALID_ISSUES_FIELD:{name}")
        elif artifact_issues:
            issues.append(f"ARTIFACT_HAS_ISSUES:{name}:{len(artifact_issues)}")
        if not isinstance(schema_version, str) or not schema_version:
            issues.append(f"MISSING_SCHEMA_VERSION:{name}")

        artifacts.append(
            {
                "artifact": name,
                "schema_version": schema_version,
                "status": status,
                "issues_total": len(artifact_issues) if isinstance(artifact_issues, list) else None,
            }
        )

    ledger_audit_path = ledger / "audit_latest.json"
    publication_path = ledger / "publication_latest.json"
    if ledger_audit_path.is_file() and publication_path.is_file():
        try:
            ledger_audit = json.loads(ledger_audit_path.read_text(encoding="utf-8"))
            publication = json.loads(publication_path.read_text(encoding="utf-8"))
            accepted = ledger_audit.get("accepted_events_total")
            published = publication.get("events_total", publication.get("accepted_events_total"))
            if isinstance(accepted, int) and isinstance(published, int) and accepted != published:
                issues.append(f"PUBLICATION_COUNT_MISMATCH:{accepted}:{published}")

            ledger_run_at = ledger_audit.get("run_at")
            publication_run_at = publication.get("generated_from_run_at")
            if not isinstance(ledger_run_at, str) or not ledger_run_at:
                issues.append("MISSING_LEDGER_RUN_AT")
            if not isinstance(publication_run_at, str) or not publication_run_at:
                issues.append("MISSING_PUBLICATION_SOURCE_RUN_AT")
            if (
                isinstance(ledger_run_at, str)
                and ledger_run_at
                and isinstance(publication_run_at, str)
                and publication_run_at
                and ledger_run_at != publication_run_at
            ):
                issues.append(
                    f"STALE_PUBLICATION_RUN:{ledger_run_at}:{publication_run_at}"
                )
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "schema_version": "earnings-run-coherence-audit.v1",
        "required_artifacts": list(REQUIRED),
        "required_artifacts_total": len(REQUIRED),
        "checked_artifacts_total": len(artifacts),
        "artifacts": artifacts,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": (
            "A ledger run is publishable only when every required audit artifact exists, parses as JSON, "
            "declares a schema version, reports PASS, contains zero audit issues, and the publication is "
            "bound to the exact same ledger run_at so a stale PASS publication cannot be reused."
        ),
    }


def main() -> int:
    result = audit()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
