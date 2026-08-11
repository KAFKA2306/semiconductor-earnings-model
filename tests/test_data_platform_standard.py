from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.data_platform import DataPlatformService, STANDARD_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


def stable(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_company_projection_has_complete_provenance_and_valid_source_hash() -> None:
    service = DataPlatformService(ROOT)
    payload = service.search_companies("")
    assert payload["schema_version"] == STANDARD_SCHEMA_VERSION
    assert payload["records"]
    record = payload["records"][0]

    required = {
        "canonical_id",
        "schema_version",
        "data_layer",
        "data_as_of",
        "generated_at",
        "source_type",
        "source_id",
        "source_doc_id",
        "source_url",
        "source_observed_at",
        "source_hash",
        "freshness",
        "stale",
        "null_reason",
        "derivation_method",
        "basis",
        "provenance",
    }
    assert required <= set(record)
    source = ROOT / record["provenance"]["source_path"]
    assert record["source_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_read_only_service_replays_deterministically() -> None:
    service = DataPlatformService(ROOT)
    first = service.search_companies("")
    second = service.search_companies("")
    assert stable(first) == stable(second)

    company_id = first["records"][0]["record"]["company_id"]
    assert stable(service.get_earnings_history(company_id)) == stable(service.get_earnings_history(company_id))
    assert stable(service.get_data_quality()) == stable(service.get_data_quality())


def test_missing_data_remains_explicit_null_state() -> None:
    service = DataPlatformService(ROOT)
    latest = service.get_company_earnings("__does_not_exist__")
    history = service.get_earnings_history("__does_not_exist__")
    assert latest["records"] == []
    assert latest["null_reason"] == "NOT_FOUND"
    assert history["records"] == []
    assert history["null_reason"] == "NOT_FOUND"

    publication = service.get_publication_snapshot()["records"][0]
    if not publication["record"].get("events"):
        assert publication["null_reason"] == "NO_FRESH_PUBLISHABLE_EVENTS"


def test_data_quality_surfaces_lineage_revision_without_silent_rewrite() -> None:
    service = DataPlatformService(ROOT)
    quality = service.get_data_quality()
    record = quality["records"][0]["record"]
    assert record["fail_closed"] is True
    assert isinstance(record["lineage_artifacts"], list)
    assert record["lineage_status"] in {"PASS", "FAIL", "BLOCKED", None}
    assert all(item["state"] in {"MATCH", "REVISION_CHANGED", "MISSING"} for item in record["lineage_artifacts"])
