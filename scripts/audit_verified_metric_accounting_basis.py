from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
OUTPUT_PATH = LEDGER_DIR / "metric_accounting_basis_audit_latest.json"

RAW_ARTIFACTS = {
    "verified_revenue_latest.json": "revenue",
    "verified_capex_latest.json": "capital_expenditures",
    "verified_inventory_latest.json": "inventory_net",
}
DERIVED_ARTIFACTS = {"verified_fcf_latest.json": "free_cash_flow"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_issue(path: str, code: str, detail: str | None = None, event_id: Any = None) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "artifact": path}
    if event_id is not None:
        issue["event_id"] = event_id
    if detail is not None:
        issue["detail"] = detail
    return issue


def audit_artifacts(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    expected = {**RAW_ARTIFACTS, **DERIVED_ARTIFACTS}
    for artifact, expected_metric in expected.items():
        payload = payloads.get(artifact)
        if payload is None:
            issues.append(_artifact_issue(artifact, "MISSING_VERIFIED_METRIC_ARTIFACT"))
            continue
        if payload.get("status") != "PASS" or payload.get("issues") not in ([], None):
            issues.append(_artifact_issue(artifact, "UPSTREAM_METRIC_ARTIFACT_NOT_PASS"))
            continue

        metrics = payload.get("metrics")
        if not isinstance(metrics, list):
            issues.append(_artifact_issue(artifact, "INVALID_METRICS_COLLECTION"))
            continue
        if payload.get("verified_metrics_total") != len(metrics):
            issues.append(_artifact_issue(artifact, "VERIFIED_METRIC_COUNT_MISMATCH"))

        for metric in metrics:
            if not isinstance(metric, dict):
                issues.append(_artifact_issue(artifact, "INVALID_METRIC_ROW"))
                continue
            event_id = str(metric.get("event_id") or "")
            metric_name = str(metric.get("metric") or "")
            if not event_id or metric_name != expected_metric:
                issues.append(
                    _artifact_issue(
                        artifact,
                        "INVALID_METRIC_IDENTITY",
                        detail=f"expected metric={expected_metric!r}, got {metric_name!r}",
                        event_id=event_id or None,
                    )
                )
                continue
            key = (event_id, metric_name)
            if key in seen:
                issues.append(_artifact_issue(artifact, "DUPLICATE_VERIFIED_METRIC", event_id=event_id))
                continue
            seen.add(key)

            if artifact in RAW_ARTIFACTS:
                taxonomy = metric.get("taxonomy")
                concept = metric.get("concept")
                if taxonomy != "us-gaap" or not isinstance(concept, str) or not concept.strip():
                    issues.append(
                        _artifact_issue(
                            artifact,
                            "RAW_METRIC_NOT_BOUND_TO_US_GAAP_XBRL",
                            event_id=event_id,
                        )
                    )
                    continue
                declared_basis = metric.get("accounting_basis")
                if declared_basis not in (None, "us-gaap-xbrl-fact"):
                    issues.append(
                        _artifact_issue(
                            artifact,
                            "RAW_METRIC_ACCOUNTING_BASIS_CONFLICT",
                            detail=f"unexpected accounting_basis={declared_basis!r}",
                            event_id=event_id,
                        )
                    )
                    continue
                items.append(
                    {
                        "artifact": artifact,
                        "event_id": event_id,
                        "metric": metric_name,
                        "accounting_basis": "us-gaap-xbrl-fact",
                        "taxonomy": taxonomy,
                        "concept": concept,
                    }
                )
                continue

            if metric.get("accounting_basis") != "derived-non-gaap":
                issues.append(_artifact_issue(artifact, "DERIVED_METRIC_MISSING_NON_GAAP_LABEL", event_id=event_id))
                continue
            inputs = metric.get("inputs")
            if not isinstance(inputs, dict) or set(inputs) != {"operating_cash_flow", "capital_expenditures"}:
                issues.append(_artifact_issue(artifact, "DERIVED_METRIC_INPUT_PROVENANCE_INCOMPLETE", event_id=event_id))
                continue
            invalid_input = False
            for input_metric in inputs.values():
                if not isinstance(input_metric, dict):
                    invalid_input = True
                    break
                if input_metric.get("taxonomy") != "us-gaap" or not str(input_metric.get("concept") or "").strip():
                    invalid_input = True
                    break
            if invalid_input:
                issues.append(_artifact_issue(artifact, "DERIVED_METRIC_INPUT_PROVENANCE_INCOMPLETE", event_id=event_id))
                continue
            if not str(metric.get("derivation") or "").strip():
                issues.append(_artifact_issue(artifact, "DERIVED_METRIC_DERIVATION_MISSING", event_id=event_id))
                continue
            items.append(
                {
                    "artifact": artifact,
                    "event_id": event_id,
                    "metric": metric_name,
                    "accounting_basis": "derived-non-gaap",
                    "inputs": sorted(inputs),
                }
            )

    items.sort(key=lambda item: (item["artifact"], item["event_id"], item["metric"]))
    return {
        "schema_version": "verified-metric-accounting-basis-audit.v1",
        "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifacts_expected_total": len(expected),
        "metrics_audited_total": len(items),
        "items": items,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": "Persisted raw metrics may be classified as GAAP only when bound to a standard us-gaap XBRL concept; derived FCF must remain explicitly derived-non-gaap with both us-gaap input provenances and an explicit derivation.",
    }


def main() -> int:
    payloads: dict[str, dict[str, Any]] = {}
    for artifact in {**RAW_ARTIFACTS, **DERIVED_ARTIFACTS}:
        path = LEDGER_DIR / artifact
        if path.exists():
            payloads[artifact] = load_json(path)
    result = audit_artifacts(payloads)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
