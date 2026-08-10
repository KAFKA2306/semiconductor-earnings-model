from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_data_lake_bundle.py"
SPEC = importlib.util.spec_from_file_location("build_data_lake_bundle", MODULE_PATH)
assert SPEC and SPEC.loader
bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundle
SPEC.loader.exec_module(bundle)


def projection(**overrides):
    payload = {
        "schema_version": "edinetdb.consumer-projection.v1",
        "consumer": "KAFKA2306/factory",
        "projection_id": "factory-toyota-financials",
        "provider": "EDINET DB",
        "attribution": "Powered by EDINET DB",
        "provider_terms": "https://edinetdb.jp/legal/terms",
        "source_endpoint": "/v1/companies/E02144/financials",
        "request_fingerprint": "a" * 64,
        "fetched_at": "2026-08-10T00:00:00Z",
        "response_sha256": "b" * 64,
        "record_count": 1,
        "records": [{"fiscal_year": 2026}],
    }
    payload.update(overrides)
    return payload


def config():
    return {
        "schema_version": "data-lake-publish.v1",
        "bucket": "k4fka/kafka-data-lake",
        "destination_prefix": "central",
        "publish_roots": [
            {
                "source": "data/edinetdb_projections",
                "destination": "edinetdb/projections",
                "required": False,
                "extensions": [".json"],
            }
        ],
        "policy": {
            "allow_list_only": True,
            "raw_provider_responses": False,
            "manifest_required": True,
            "sha256_readback_required": True,
            "consumer_repository_authentication": False,
        },
    }


def quota_plan():
    return {
        "company_master": {
            "projection_fields": ["edinet_code", "name"],
            "code_consumers": {
                "E02144": ["KAFKA2306/factory"],
            },
        },
        "requests": [
            {
                "id": "factory-toyota-financials",
                "consumer": "KAFKA2306/factory",
                "path": "/v1/companies/E02144/financials",
                "projection_fields": ["fiscal_year", "revenue", "source_doc_id"],
            }
        ],
    }


def write_quota_plan(tmp_path: Path) -> None:
    path = tmp_path / "config" / "edinetdb_quota_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(quota_plan()), encoding="utf-8")


def test_bundle_contains_only_allow_listed_projection(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bundle, "ROOT", tmp_path)
    write_quota_plan(tmp_path)
    source = tmp_path / "data" / "edinetdb_projections" / "KAFKA2306__factory"
    source.mkdir(parents=True)
    projection_path = source / "factory-toyota-financials.json"
    projection_path.write_text(json.dumps(projection()), encoding="utf-8")
    (source / "ignored.txt").write_text("not published", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config()), encoding="utf-8")

    result = bundle.build_bundle(
        config_path,
        tmp_path / "out",
        source_repo="KAFKA2306/semiconductor-earnings-model",
        source_revision="abc123",
        generated_at="2026-08-10T00:00:00Z",
    )

    assert result["file_count"] == 1
    assert result["files"][0]["remote_path"] == (
        "central/edinetdb/projections/KAFKA2306__factory/factory-toyota-financials.json"
    )
    assert len(result["files"][0]["sha256"]) == 64
    assert not (
        tmp_path
        / "out"
        / "payload"
        / "central"
        / "edinetdb"
        / "projections"
        / "KAFKA2306__factory"
        / "ignored.txt"
    ).exists()


def test_optional_missing_projection_root_produces_empty_manifest(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bundle, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config()), encoding="utf-8")
    result = bundle.build_bundle(
        config_path,
        tmp_path / "out",
        source_repo="KAFKA2306/semiconductor-earnings-model",
        source_revision="abc123",
        generated_at="2026-08-10T00:00:00Z",
    )
    assert result["file_count"] == 0
    assert result["total_bytes"] == 0


def test_raw_or_unknown_top_level_field_is_fail_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bundle, "ROOT", tmp_path)
    write_quota_plan(tmp_path)
    source = tmp_path / "data" / "edinetdb_projections"
    source.mkdir(parents=True)
    bad = projection(raw_response={"forbidden": True})
    path = source / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config()), encoding="utf-8")

    try:
        bundle.build_bundle(
            config_path,
            tmp_path / "out",
            source_repo="KAFKA2306/semiconductor-earnings-model",
            source_revision="abc123",
        )
    except ValueError as exc:
        assert "unexpected EDINETDB projection top-level fields" in str(exc)
    else:
        raise AssertionError("unknown/raw fields must fail closed")


def test_raw_or_unknown_nested_record_field_is_fail_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bundle, "ROOT", tmp_path)
    write_quota_plan(tmp_path)
    source = tmp_path / "data" / "edinetdb_projections"
    source.mkdir(parents=True)
    bad = projection(records=[{"fiscal_year": 2026, "raw_provider_payload": {"secret": True}}])
    path = source / "bad-record.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config()), encoding="utf-8")

    try:
        bundle.build_bundle(
            config_path,
            tmp_path / "out",
            source_repo="KAFKA2306/semiconductor-earnings-model",
            source_revision="abc123",
        )
    except ValueError as exc:
        assert "unexpected EDINETDB record fields" in str(exc)
        assert "raw_provider_payload" in str(exc)
    else:
        raise AssertionError("nested unknown/raw fields must fail closed")


def test_projection_id_and_endpoint_must_match_quota_plan(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bundle, "ROOT", tmp_path)
    write_quota_plan(tmp_path)
    source = tmp_path / "data" / "edinetdb_projections"
    source.mkdir(parents=True)
    bad = projection(source_endpoint="/v1/companies/E99999/financials")
    path = source / "wrong-endpoint.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config()), encoding="utf-8")

    try:
        bundle.build_bundle(
            config_path,
            tmp_path / "out",
            source_repo="KAFKA2306/semiconductor-earnings-model",
            source_revision="abc123",
        )
    except ValueError as exc:
        assert "endpoint is not allow-listed" in str(exc)
    else:
        raise AssertionError("endpoint drift must fail closed")


def test_policy_cannot_enable_consumer_authentication() -> None:
    bad = config()
    bad["policy"]["consumer_repository_authentication"] = True
    try:
        bundle.validate_config(bad)
    except ValueError as exc:
        assert "consumer_repository_authentication" in str(exc)
    else:
        raise AssertionError("consumer repo authentication must remain disabled")
