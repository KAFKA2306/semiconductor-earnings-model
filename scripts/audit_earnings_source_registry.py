#!/usr/bin/env python3
"""Fail-closed structural audit for the primary-source earnings registry."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "data/earnings_ledger/source_registry.json"
DEFAULT_OUTPUT = ROOT / "data/earnings_ledger/source_registry_audit_latest.json"

EXPECTED_POLICY = {
    "primary_only": True,
    "freshness_window_hours": 24,
    "fail_closed": True,
    "no_search_snippet_dates": True,
    "dedupe_key": "event_id",
    "require_explicit_sec_cik": True,
}

ADAPTER_URL_RULES = {
    "sec_edgar": ("www.sec.gov", "/edgar/browse/"),
    "tdnet_public": ("www.release.tdnet.info", "/inbs/"),
    "opendart": ("englishdart.fss.or.kr", "/"),
}


def _issue(issues: list[dict[str, str]], code: str, source_id: str, detail: str) -> None:
    issues.append({"code": code, "source_id": source_id, "detail": detail})


def _valid_official_url(adapter: str, value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    rule = ADAPTER_URL_RULES.get(adapter)
    if rule is None:
        return False
    host, path_prefix = rule
    return parsed.scheme == "https" and parsed.hostname == host and parsed.path.startswith(path_prefix)


def audit_registry(registry: dict) -> dict:
    issues: list[dict[str, str]] = []

    if registry.get("schema_version") != "earnings-source-registry.v1":
        _issue(issues, "INVALID_SCHEMA_VERSION", "<registry>", "schema_version must be earnings-source-registry.v1")

    policy = registry.get("policy")
    if not isinstance(policy, dict):
        _issue(issues, "MISSING_POLICY", "<registry>", "policy must be an object")
        policy = {}
    for key, expected in EXPECTED_POLICY.items():
        if policy.get(key) != expected:
            _issue(issues, "UNSAFE_POLICY", "<registry>", f"policy.{key} must equal {expected!r}")

    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        _issue(issues, "MISSING_SOURCES", "<registry>", "sources must be a non-empty array")
        sources = []

    seen_ids: set[str] = set()
    seen_sec_ciks: set[int] = set()
    seen_company_ids: set[str] = set()
    adapter_counts: dict[str, int] = {}
    enabled_count = 0
    disabled_count = 0

    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            _issue(issues, "INVALID_SOURCE", f"<index:{index}>", "source must be an object")
            continue

        source_id = source.get("id")
        sid = source_id if isinstance(source_id, str) and source_id else f"<index:{index}>"
        if not isinstance(source_id, str) or not source_id:
            _issue(issues, "MISSING_SOURCE_ID", sid, "id must be a non-empty string")
        elif source_id in seen_ids:
            _issue(issues, "DUPLICATE_SOURCE_ID", sid, "source id must be unique")
        else:
            seen_ids.add(source_id)

        adapter = source.get("adapter")
        if adapter not in ADAPTER_URL_RULES:
            _issue(issues, "UNSUPPORTED_ADAPTER", sid, f"unsupported adapter: {adapter!r}")
            adapter_name = str(adapter)
        else:
            adapter_name = adapter
        adapter_counts[adapter_name] = adapter_counts.get(adapter_name, 0) + 1

        enabled = source.get("enabled")
        if not isinstance(enabled, bool):
            _issue(issues, "INVALID_ENABLED_FLAG", sid, "enabled must be boolean")
            enabled = False
        if enabled:
            enabled_count += 1
        else:
            disabled_count += 1
            reason = source.get("disabled_reason")
            if not isinstance(reason, str) or not reason.strip():
                _issue(issues, "MISSING_DISABLED_REASON", sid, "disabled sources require disabled_reason")

        if not _valid_official_url(adapter_name, source.get("official_source")):
            _issue(
                issues,
                "NON_PRIMARY_OFFICIAL_SOURCE",
                sid,
                "official_source must use the adapter's allow-listed HTTPS primary domain/path",
            )

        for field in ("name",):
            if not isinstance(source.get(field), str) or not source[field].strip():
                _issue(issues, "MISSING_REQUIRED_FIELD", sid, f"{field} must be a non-empty string")

        if adapter == "sec_edgar":
            cik = source.get("cik")
            if not isinstance(cik, int) or isinstance(cik, bool) or cik <= 0 or cik > 9_999_999_999:
                _issue(issues, "INVALID_SEC_CIK", sid, "SEC source requires a positive integer CIK of at most 10 digits")
            elif cik in seen_sec_ciks:
                _issue(issues, "DUPLICATE_SEC_CIK", sid, f"CIK {cik} is registered more than once")
            else:
                seen_sec_ciks.add(cik)

            ticker = source.get("ticker")
            if not isinstance(ticker, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker):
                _issue(issues, "INVALID_SEC_TICKER", sid, "SEC source requires a normalized uppercase ticker")

            if isinstance(source_id, str) and source_id:
                if source_id in seen_company_ids:
                    _issue(issues, "DUPLICATE_COMPANY_ID", sid, "company id must be globally unique")
                else:
                    seen_company_ids.add(source_id)

        elif adapter == "tdnet_public":
            codes = source.get("codes")
            companies = source.get("companies")
            if not isinstance(codes, list) or not codes:
                _issue(issues, "INVALID_TDNET_CODES", sid, "TDnet source requires a non-empty codes array")
                codes = []
            normalized_codes = [code for code in codes if isinstance(code, str) and re.fullmatch(r"\d{4}", code)]
            if len(normalized_codes) != len(codes) or len(set(normalized_codes)) != len(normalized_codes):
                _issue(issues, "INVALID_TDNET_CODES", sid, "TDnet codes must be unique four-digit strings")
            if not isinstance(companies, dict):
                _issue(issues, "INVALID_TDNET_COMPANIES", sid, "TDnet source requires companies mapping")
                companies = {}
            if set(companies) != set(normalized_codes):
                _issue(issues, "TDNET_CODE_COMPANY_MISMATCH", sid, "companies keys must exactly match codes")

            for code in normalized_codes:
                company = companies.get(code)
                if not isinstance(company, dict):
                    continue
                company_id = company.get("id")
                if not isinstance(company_id, str) or not company_id:
                    _issue(issues, "MISSING_TDNET_COMPANY_ID", sid, f"company {code} requires id")
                elif company_id in seen_company_ids:
                    _issue(issues, "DUPLICATE_COMPANY_ID", sid, f"company id {company_id} is registered more than once")
                else:
                    seen_company_ids.add(company_id)
                if company.get("ticker") != code:
                    _issue(issues, "TDNET_TICKER_CODE_MISMATCH", sid, f"company {code} ticker must equal code")
                if not isinstance(company.get("name"), str) or not company["name"].strip():
                    _issue(issues, "MISSING_REQUIRED_FIELD", sid, f"company {code} name must be non-empty")

        elif adapter == "opendart":
            if enabled:
                _issue(
                    issues,
                    "OPENDART_ENABLED_WITHOUT_AUTH_CONTRACT",
                    sid,
                    "OpenDART sources remain fail-closed until the authenticated exact-timestamp adapter contract exists",
                )

    return {
        "schema_version": "earnings-source-registry-audit.v1",
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "summary": {
            "source_count": len(sources),
            "enabled_source_count": enabled_count,
            "disabled_source_count": disabled_count,
            "company_id_count": len(seen_company_ids),
            "adapter_counts": dict(sorted(adapter_counts.items())),
        },
        "contract": {
            "primary_domains_allow_listed": True,
            "unsafe_policy_mutation_rejected": True,
            "duplicate_source_and_company_identity_rejected": True,
            "disabled_sources_require_reason": True,
            "opendart_remains_fail_closed_without_authenticated_timestamp_contract": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    result = audit_registry(registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
