from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_earnings_source_registry import audit_registry  # noqa: E402


def load_registry() -> dict:
    return json.loads((ROOT / "data/earnings_ledger/source_registry.json").read_text(encoding="utf-8"))


def issue_codes(result: dict) -> set[str]:
    return {issue["code"] for issue in result["issues"]}


def test_current_registry_passes_fail_closed_contract() -> None:
    result = audit_registry(load_registry())
    assert result["status"] == "PASS"
    assert result["issues"] == []
    assert result["summary"]["enabled_source_count"] >= 1
    assert result["contract"]["primary_domains_allow_listed"] is True
    assert result["contract"]["sec_registry_cik_bound_to_official_url"] is True


def test_rejects_policy_relaxation() -> None:
    registry = load_registry()
    registry["policy"]["freshness_window_hours"] = 48
    result = audit_registry(registry)
    assert result["status"] == "FAIL"
    assert "UNSAFE_POLICY" in issue_codes(result)


def test_rejects_non_primary_sec_domain() -> None:
    registry = load_registry()
    sec_source = next(source for source in registry["sources"] if source["adapter"] == "sec_edgar")
    sec_source["official_source"] = "https://example.com/company"
    result = audit_registry(registry)
    assert "NON_PRIMARY_OFFICIAL_SOURCE" in issue_codes(result)


def test_rejects_missing_sec_url_cik() -> None:
    registry = load_registry()
    sec_source = next(source for source in registry["sources"] if source["adapter"] == "sec_edgar")
    sec_source["official_source"] = "https://www.sec.gov/edgar/browse/"
    result = audit_registry(registry)
    assert "MISSING_SEC_URL_CIK" in issue_codes(result)


def test_rejects_mismatched_sec_url_cik() -> None:
    registry = load_registry()
    sec_source = next(source for source in registry["sources"] if source["adapter"] == "sec_edgar")
    sec_source["official_source"] = "https://www.sec.gov/edgar/browse/?CIK=1"
    result = audit_registry(registry)
    assert "SEC_URL_CIK_MISMATCH" in issue_codes(result)


def test_rejects_ambiguous_sec_url_cik() -> None:
    registry = load_registry()
    sec_source = next(source for source in registry["sources"] if source["adapter"] == "sec_edgar")
    cik = sec_source["cik"]
    sec_source["official_source"] = f"https://www.sec.gov/edgar/browse/?CIK={cik}&CIK={cik}"
    result = audit_registry(registry)
    assert "MISSING_SEC_URL_CIK" in issue_codes(result)


def test_rejects_duplicate_sec_identity() -> None:
    registry = load_registry()
    first = next(source for source in registry["sources"] if source["adapter"] == "sec_edgar")
    duplicate = copy.deepcopy(first)
    duplicate["id"] = "duplicate-company"
    duplicate["ticker"] = "DUP"
    registry["sources"].append(duplicate)
    result = audit_registry(registry)
    assert "DUPLICATE_SEC_CIK" in issue_codes(result)


def test_rejects_tdnet_code_company_drift() -> None:
    registry = load_registry()
    tdnet = next(source for source in registry["sources"] if source["adapter"] == "tdnet_public")
    tdnet["companies"].pop(tdnet["codes"][0])
    result = audit_registry(registry)
    assert "TDNET_CODE_COMPANY_MISMATCH" in issue_codes(result)


def test_disabled_source_requires_reason() -> None:
    registry = load_registry()
    disabled = next(source for source in registry["sources"] if source["enabled"] is False)
    disabled.pop("disabled_reason", None)
    result = audit_registry(registry)
    assert "MISSING_DISABLED_REASON" in issue_codes(result)


def test_opendart_cannot_be_enabled_before_authenticated_timestamp_contract() -> None:
    registry = load_registry()
    opendart = next(source for source in registry["sources"] if source["adapter"] == "opendart")
    opendart["enabled"] = True
    result = audit_registry(registry)
    assert "OPENDART_ENABLED_WITHOUT_AUTH_CONTRACT" in issue_codes(result)
