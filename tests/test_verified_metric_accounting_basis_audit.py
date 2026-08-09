from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "audit_verified_metric_accounting_basis.py"
spec = importlib.util.spec_from_file_location("audit_verified_metric_accounting_basis", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def raw_payload(metric_name: str, concept: str) -> dict:
    return {
        "status": "PASS",
        "issues": [],
        "verified_metrics_total": 1,
        "metrics": [
            {
                "event_id": f"evt-{metric_name}",
                "metric": metric_name,
                "taxonomy": "us-gaap",
                "concept": concept,
            }
        ],
    }


def fcf_payload() -> dict:
    return {
        "status": "PASS",
        "issues": [],
        "verified_metrics_total": 1,
        "metrics": [
            {
                "event_id": "evt-fcf",
                "metric": "free_cash_flow",
                "accounting_basis": "derived-non-gaap",
                "derivation": "NetCashProvidedByUsedInOperatingActivities - PaymentsToAcquirePropertyPlantAndEquipment",
                "inputs": {
                    "operating_cash_flow": {
                        "taxonomy": "us-gaap",
                        "concept": "NetCashProvidedByUsedInOperatingActivities",
                    },
                    "capital_expenditures": {
                        "taxonomy": "us-gaap",
                        "concept": "PaymentsToAcquirePropertyPlantAndEquipment",
                    },
                },
            }
        ],
    }


def valid_payloads() -> dict[str, dict]:
    return {
        "verified_revenue_latest.json": raw_payload("revenue", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        "verified_capex_latest.json": raw_payload("capital_expenditures", "PaymentsToAcquirePropertyPlantAndEquipment"),
        "verified_inventory_latest.json": raw_payload("inventory", "InventoryNet"),
        "verified_fcf_latest.json": fcf_payload(),
    }


def test_valid_raw_gaap_and_derived_non_gaap_metrics_pass() -> None:
    result = module.audit_artifacts(valid_payloads())
    assert result["status"] == "PASS"
    assert result["issues"] == []
    assert result["metrics_audited_total"] == 4


def test_missing_artifact_fails_closed() -> None:
    payloads = valid_payloads()
    del payloads["verified_inventory_latest.json"]
    result = module.audit_artifacts(payloads)
    assert result["status"] == "FAIL"
    assert any(issue["code"] == "MISSING_VERIFIED_METRIC_ARTIFACT" for issue in result["issues"])


def test_raw_metric_requires_us_gaap_taxonomy_and_concept() -> None:
    payloads = valid_payloads()
    payloads["verified_revenue_latest.json"]["metrics"][0]["taxonomy"] = "custom"
    result = module.audit_artifacts(payloads)
    assert result["status"] == "FAIL"
    assert any(issue["code"] == "RAW_METRIC_NOT_BOUND_TO_US_GAAP_XBRL" for issue in result["issues"])


def test_raw_metric_rejects_conflicting_non_gaap_label() -> None:
    payloads = valid_payloads()
    payloads["verified_inventory_latest.json"]["metrics"][0]["accounting_basis"] = "derived-non-gaap"
    result = module.audit_artifacts(payloads)
    assert result["status"] == "FAIL"
    assert any(issue["code"] == "RAW_METRIC_ACCOUNTING_BASIS_CONFLICT" for issue in result["issues"])


def test_fcf_requires_explicit_derived_non_gaap_label() -> None:
    payloads = valid_payloads()
    del payloads["verified_fcf_latest.json"]["metrics"][0]["accounting_basis"]
    result = module.audit_artifacts(payloads)
    assert result["status"] == "FAIL"
    assert any(issue["code"] == "DERIVED_METRIC_MISSING_NON_GAAP_LABEL" for issue in result["issues"])


def test_fcf_requires_both_us_gaap_input_provenances() -> None:
    payloads = valid_payloads()
    payloads["verified_fcf_latest.json"]["metrics"][0]["inputs"]["capital_expenditures"]["taxonomy"] = "custom"
    result = module.audit_artifacts(payloads)
    assert result["status"] == "FAIL"
    assert any(issue["code"] == "DERIVED_METRIC_INPUT_PROVENANCE_INCOMPLETE" for issue in result["issues"])


def test_metric_count_mismatch_fails_closed() -> None:
    payloads = valid_payloads()
    payloads["verified_capex_latest.json"]["verified_metrics_total"] = 0
    result = module.audit_artifacts(payloads)
    assert result["status"] == "FAIL"
    assert any(issue["code"] == "VERIFIED_METRIC_COUNT_MISMATCH" for issue in result["issues"])


def test_duplicate_event_metric_pair_fails_closed_across_artifacts() -> None:
    payloads = valid_payloads()
    payloads["verified_inventory_latest.json"]["metrics"][0]["event_id"] = "evt-revenue"
    payloads["verified_inventory_latest.json"]["metrics"][0]["metric"] = "revenue"
    result = module.audit_artifacts(payloads)
    assert result["status"] == "FAIL"
    assert any(issue["code"] == "INVALID_METRIC_IDENTITY" for issue in result["issues"])
