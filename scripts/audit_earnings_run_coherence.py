#!/usr/bin/env python3
"""Fail closed when the latest earnings-ledger audit artifacts are not coherent."""

from __future__ import annotations

import json
from datetime import datetime, timezone
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

RUN_BOUND = (
    "rejection_reason_audit_latest.json",
    "semantic_duplicate_audit_latest.json",
    "period_normalization_latest.json",
    "accounting_basis_audit_latest.json",
    "published_at_audit_latest.json",
    "evidence_latest.json",
    "consensus_separation_audit_latest.json",
)
MAX_RUN_SKEW_SECONDS = 300


def parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing timestamp: {field}")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError(f"timezone missing: {field}")
    return parsed.astimezone(timezone.utc)


def audit(ledger: Path = LEDGER) -> dict:
    issues: list[str] = []
    artifacts: list[dict] = []
    payloads: dict[str, dict] = {}

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
        payloads[name] = payload

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

    ledger_audit = payloads.get("audit_latest.json")
    if ledger_audit is not None:
        try:
            ledger_run_at = parse_timestamp(ledger_audit.get("run_at"), field="audit_latest.json.run_at")
        except (TypeError, ValueError) as exc:
            issues.append(f"INVALID_LEDGER_RUN_AT:{exc}")
            ledger_run_at = None

        if ledger_run_at is not None:
            for name in RUN_BOUND:
                payload = payloads.get(name)
                if payload is None:
                    continue
                try:
                    artifact_run_at = parse_timestamp(payload.get("run_at"), field=f"{name}.run_at")
                except (TypeError, ValueError) as exc:
                    issues.append(f"INVALID_ARTIFACT_RUN_AT:{name}:{exc}")
                    continue
                skew_seconds = abs((artifact_run_at - ledger_run_at).total_seconds())
                if skew_seconds > MAX_RUN_SKEW_SECONDS:
                    issues.append(
                        f"STALE_DERIVED_AUDIT_RUN:{name}:{int(skew_seconds)}s"
                    )

    publication = payloads.get("publication_latest.json")
    if ledger_audit is not None and publication is not None:
        accepted = ledger_audit.get("accepted_events_total")
        publication_ledger_total = publication.get(
            "ledger_accepted_events_total",
            publication.get("events_total", publication.get("accepted_events_total")),
        )
        if (
            isinstance(accepted, int)
            and isinstance(publication_ledger_total, int)
            and accepted != publication_ledger_total
        ):
            issues.append(
                f"PUBLICATION_LEDGER_COUNT_MISMATCH:{accepted}:{publication_ledger_total}"
            )

        published = publication.get("accepted_events_total")
        expired = publication.get("expired_events_total", 0)
        if (
            isinstance(accepted, int)
            and isinstance(published, int)
            and isinstance(expired, int)
            and accepted != published + expired
        ):
            issues.append(
                f"PUBLICATION_FRESHNESS_COUNT_MISMATCH:{accepted}:{published}:{expired}"
            )

        ledger_run_at_raw = ledger_audit.get("run_at")
        publication_run_at = publication.get("generated_from_run_at")
        if not isinstance(ledger_run_at_raw, str) or not ledger_run_at_raw:
            issues.append("MISSING_LEDGER_RUN_AT")
        if not isinstance(publication_run_at, str) or not publication_run_at:
            issues.append("MISSING_PUBLICATION_SOURCE_RUN_AT")
        if (
            isinstance(ledger_run_at_raw, str)
            and ledger_run_at_raw
            and isinstance(publication_run_at, str)
            and publication_run_at
            and ledger_run_at_raw != publication_run_at
        ):
            issues.append(
                f"STALE_PUBLICATION_RUN:{ledger_run_at_raw}:{publication_run_at}"
            )

    return {
        "schema_version": "earnings-run-coherence-audit.v2",
        "required_artifacts": list(REQUIRED),
        "required_artifacts_total": len(REQUIRED),
        "checked_artifacts_total": len(artifacts),
        "run_bound_artifacts": list(RUN_BOUND),
        "max_run_skew_seconds": MAX_RUN_SKEW_SECONDS,
        "artifacts": artifacts,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": (
            "A ledger run is publishable only when every required audit artifact exists, parses as JSON, "
            "declares a schema version, reports PASS, contains zero audit issues, every run-bound derived "
            "audit was generated within 300 seconds of the audited ledger run, and the publication is bound "
            "to the exact same ledger run_at. The publication may omit events older than 24 hours, but its "
            "fresh plus expired counts must reconcile exactly to the audited ledger count."
        ),
    }


def main() -> int:
    result = audit()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
