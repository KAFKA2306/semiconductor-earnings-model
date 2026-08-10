from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

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

    assert result["schema_version"] == "data-lake-manifest.v2"
    assert result["file_count"] == 1
    assert result["files"][0]["remote_path"] == (
        "central/edinetdb/projections/KAFKA2306__factory/factory-toyota-financials.json"
    )
    assert len(result["files"][0]["sha256"]) == 64
    assert result["files"][0]["source_repository"] == "KAFKA2306/semiconductor-earnings-model"
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
    assert result["roots"][0]["file_count"] == 0
    assert (tmp_path / "out" / "payload" / "central" / "edinetdb" / "projections").is_dir()


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

    with pytest.raises(ValueError, match="unexpected EDINETDB projection top-level fields"):
        bundle.build_bundle(
            config_path,
            tmp_path / "out",
            source_repo="KAFKA2306/semiconductor-earnings-model",
            source_revision="abc123",
        )


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

    with pytest.raises(ValueError, match="unexpected EDINETDB record fields") as exc_info:
        bundle.build_bundle(
            config_path,
            tmp_path / "out",
            source_repo="KAFKA2306/semiconductor-earnings-model",
            source_revision="abc123",
        )
    assert "raw_provider_payload" in str(exc_info.value)


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

    with pytest.raises(ValueError, match="endpoint is not allow-listed"):
        bundle.build_bundle(
            config_path,
            tmp_path / "out",
            source_repo="KAFKA2306/semiconductor-earnings-model",
            source_revision="abc123",
        )


def test_policy_cannot_enable_consumer_authentication() -> None:
    bad = config()
    bad["policy"]["consumer_repository_authentication"] = True
    with pytest.raises(ValueError, match="consumer_repository_authentication"):
        bundle.validate_config(bad)


def test_remote_public_source_records_repository_revision_and_filters(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bundle, "ROOT", tmp_path / "central")
    bundle.ROOT.mkdir()
    remote = tmp_path / "remote-factory"
    data = remote / "data"
    data.mkdir(parents=True)
    (data / "companies-01.jsonl").write_text('{"id":"c1"}\n', encoding="utf-8")
    (data / "ignored.txt").write_text("ignored\n", encoding="utf-8")

    cfg = config()
    cfg["publish_roots"].append(
        {
            "repository": "KAFKA2306/factory",
            "ref": "main",
            "source": "data",
            "destination": "factory",
            "required": True,
            "extensions": [".jsonl"],
        }
    )
    config_path = bundle.ROOT / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")

    def fake_checkout(repository: str, ref: str, checkout_root: Path):
        assert repository == "KAFKA2306/factory"
        assert ref == "main"
        return remote, "c" * 40

    monkeypatch.setattr(bundle, "checkout_public_repository", fake_checkout)
    result = bundle.build_bundle(
        config_path,
        bundle.ROOT / "out",
        source_repo="KAFKA2306/semiconductor-earnings-model",
        source_revision="d" * 40,
        generated_at="2026-08-10T00:00:00Z",
    )

    remote_file = next(
        item
        for item in result["files"]
        if item["remote_path"] == "central/factory/companies-01.jsonl"
    )
    assert remote_file["source_repository"] == "KAFKA2306/factory"
    assert remote_file["source_revision"] == "c" * 40
    assert not any(item["remote_path"].endswith("ignored.txt") for item in result["files"])
    factory_root = next(
        item for item in result["roots"] if item["destination"] == "central/factory"
    )
    assert factory_root["file_count"] == 1


def test_include_patterns_are_root_scoped_and_explicit(tmp_path: Path) -> None:
    source = tmp_path / "data"
    (source / "kindle").mkdir(parents=True)
    (source / "nested").mkdir()
    (source / "catalog.json").write_text("{}\n", encoding="utf-8")
    (source / "nested" / "catalog.json").write_text("{}\n", encoding="utf-8")
    (source / "kindle" / "manifest.json").write_text("{}\n", encoding="utf-8")
    (source / "kindle" / "records-01.ndjson").write_text("{}\n", encoding="utf-8")
    (source / "kindle" / "debug.json").write_text("{}\n", encoding="utf-8")

    selected = bundle.selected_files(
        source,
        {
            "extensions": [".json", ".ndjson"],
            "include": ["catalog.json", "kindle/manifest.json", "kindle/records-*.ndjson"],
        },
    )
    assert [path.relative_to(source).as_posix() for path in selected] == [
        "catalog.json",
        "kindle/manifest.json",
        "kindle/records-01.ndjson",
    ]


def test_remote_repository_boundary_rejects_other_owners() -> None:
    bad = config()
    bad["publish_roots"].append(
        {
            "repository": "someone-else/factory",
            "ref": "main",
            "source": "data",
            "destination": "factory",
            "required": True,
            "extensions": [".jsonl"],
        }
    )
    with pytest.raises(ValueError, match="not allow-listed"):
        bundle.validate_config(bad)


def test_checkout_creates_work_root_before_anonymous_clone(monkeypatch, tmp_path: Path) -> None:
    checkout_root = tmp_path / "sources"
    calls: list[tuple[list[str], Path | None, bool]] = []

    def fake_run_git(
        command: list[str], *, cwd: Path | None = None, capture: bool = False
    ) -> str:
        calls.append((command, cwd, capture))
        if command[0] == "clone":
            assert checkout_root.is_dir()
            Path(command[-1]).mkdir(parents=True)
            return ""
        assert command == ["rev-parse", "HEAD"]
        return "e" * 40

    monkeypatch.setattr(bundle, "run_git", fake_run_git)
    checkout, revision = bundle.checkout_public_repository(
        "KAFKA2306/books", "main", checkout_root
    )
    assert checkout == checkout_root / "KAFKA2306__books"
    assert revision == "e" * 40
    assert calls[0][0][0] == "clone"
