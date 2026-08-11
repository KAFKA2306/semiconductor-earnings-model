from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_platform import DataPlatformService
from src.data_platform_cli import execute as cli_execute
from src.data_platform_rest import dispatch_rest

CONFIG_PATH = ROOT / "config" / "data_platform_standard.json"

EXPECTED_TOOLS = {
    "search_companies",
    "get_company_earnings",
    "get_earnings_history",
    "get_evidence",
    "get_lineage",
    "get_audit_status",
    "get_publication_snapshot",
    "get_data_quality",
}
EXPECTED_DOCS = {
    "docs/data-sources.md",
    "docs/methodology.md",
    "docs/data-quality.md",
    "docs/mcp.md",
}
ALLOWED_LAYERS = {"raw/bronze", "normalized/silver", "public/gold"}


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def assert_envelope(record: dict, required_fields: set[str], root: Path) -> None:
    missing = required_fields - set(record)
    assert not missing, f"provenance fields missing: {sorted(missing)}"
    assert record["data_layer"] in ALLOWED_LAYERS
    source_path = record["provenance"]["source_path"]
    source_file = root / source_path
    assert source_file.is_file(), source_path
    actual_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
    assert record["source_hash"] == actual_hash
    assert record["provenance"]["source_hash"] == actual_hash
    assert record["canonical_id"]


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["schema_version"] == "data-platform-standard.v1"
    assert config["protocol_version"] == "2026-07-28"
    assert config["mcp_endpoint"] == "/mcp"
    assert set(config["mcp_tools"]) == EXPECTED_TOOLS
    assert config["security"]["stateless_http"] is True
    assert config["security"]["request_body_limit_bytes"] == 65536
    assert config["security"]["read_only"] is True
    assert config["rest_api"]["read_only"] is True
    assert set(config["rest_api"]["routes"]) == EXPECTED_TOOLS
    assert config["determinism"]["llm_overwrites_primary_facts"] is False
    assert config["determinism"]["null_is_not_defaulted"] is True
    assert config["determinism"]["fail_closed"] is True

    for relative_path in EXPECTED_DOCS:
        assert (ROOT / relative_path).is_file(), relative_path

    server_source = (ROOT / "src" / "mcp_server.py").read_text(encoding="utf-8")
    assert 'streamable_http_path="/mcp"' in server_source
    assert "stateless_http=True" in server_source
    for tool in EXPECTED_TOOLS:
        assert f"def {tool}(" in server_source

    required_fields = set(config["provenance_required_fields"])
    service = DataPlatformService(ROOT)

    companies_a = service.search_companies("")
    companies_b = service.search_companies("")
    assert canonical_json(companies_a) == canonical_json(companies_b), "search must replay deterministically"
    assert companies_a["records"], "canonical events must expose at least one company"
    assert_envelope(companies_a["records"][0], required_fields, ROOT)

    company_id = companies_a["records"][0]["record"]["company_id"]
    latest = service.get_company_earnings(company_id)
    history = service.get_earnings_history(company_id)
    evidence = service.get_evidence("")
    lineage = service.get_lineage()
    audits = service.get_audit_status()
    publication = service.get_publication_snapshot()
    quality = service.get_data_quality()

    for payload in (latest, history, evidence, lineage, audits, publication, quality):
        for record in payload.get("records", []):
            assert_envelope(record, required_fields, ROOT)

    assert service.get_company_earnings("__missing__")["null_reason"] == "NOT_FOUND"
    missing_history = service.get_earnings_history("__missing__")
    assert missing_history["records"] == []
    assert missing_history["null_reason"] == "NOT_FOUND"

    publication_record = publication["records"][0]
    if not publication_record["record"].get("events"):
        assert publication_record["null_reason"] == "NO_FRESH_PUBLISHABLE_EVENTS"

    assert canonical_json(cli_execute("get_data_quality")) == canonical_json(quality)
    assert canonical_json(dispatch_rest("/api/data-platform/v1/quality")) == canonical_json(quality)
    assert canonical_json(cli_execute("search_companies", "")) == canonical_json(companies_a)
    assert canonical_json(dispatch_rest("/api/data-platform/v1/companies", "q=")) == canonical_json(companies_a)

    quality_record = quality["records"][0]["record"]
    assert quality_record["fail_closed"] is True
    assert isinstance(quality_record["lineage_artifacts"], list)

    replay_a = service.get_data_quality()
    replay_b = service.get_data_quality()
    assert canonical_json(replay_a) == canonical_json(replay_b), "quality projection must replay deterministically"

    print(
        json.dumps(
            {
                "status": "PASS",
                "schema_version": config["schema_version"],
                "companies": companies_a["count"],
                "audit_records": audits["count"],
                "mcp_tools": len(EXPECTED_TOOLS),
                "data_quality": quality["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
