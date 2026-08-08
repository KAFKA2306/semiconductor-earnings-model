from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_earnings_accounting_basis.py"
SPEC = importlib.util.spec_from_file_location("audit_earnings_accounting_basis", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def event(document_type: str, adapter: str = "sec_edgar", event_id: str = "e1") -> dict:
    return {
        "event_id": event_id,
        "company_id": "example",
        "document_type": document_type,
        "source_adapter": adapter,
    }


def test_10k_does_not_auto_label_metrics_gaap():
    item = module.classify_event(event("10-K"))
    assert item["event_accounting_context"] == "US_GAAP_PRIMARY_FINANCIAL_STATEMENTS_PRESENT"
    assert item["automatic_gaap_metric_use"] is False
    assert item["metric_level_basis_required"] is True


def test_8k_is_mixed_or_unverified():
    item = module.classify_event(event("8-K"))
    assert item["event_accounting_context"] == "MIXED_OR_UNVERIFIED_EARNINGS_MATERIAL"
    assert item["automatic_gaap_metric_use"] is False


def test_20f_basis_is_not_inferred_from_form():
    item = module.classify_event(event("20-F"))
    assert item["event_accounting_context"] == "ACCOUNTING_BASIS_UNVERIFIED_FROM_FORM"


def test_non_sec_source_remains_unverified():
    item = module.classify_event(event("earnings_release", adapter="tdnet"))
    assert item["event_accounting_context"] == "UNVERIFIED_PRIMARY_SOURCE_BASIS"
    assert item["automatic_gaap_metric_use"] is False


def test_unknown_sec_form_fails_closed():
    result = module.audit([event("S-1")])
    assert result["status"] == "FAIL"
    assert result["issues"][0]["code"] == "UNCLASSIFIED_ACCOUNTING_BASIS"
