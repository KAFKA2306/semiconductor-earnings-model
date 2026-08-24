from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.publish_investor2_yahoo_market_cache import (
    MarketCacheConfig,
    annual_prefix,
    assert_converged_sync_plan,
    latest_safe_completed_year,
    load_config,
    parse_sync_changes,
    validate_extension_contract,
    validate_manifest,
    verify_readback,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_config(tmp_path: Path) -> MarketCacheConfig:
    path = tmp_path / "cache-config.json"
    path.write_text(
        json.dumps(
            {
                "bucket": "example-bucket",
                "base_prefix": "market/base/v7",
                "extensions_prefix": "market/extensions/v7",
                "regions": ["us", "ca"],
                "start": "2013-04-01",
                "end_exclusive": "2024-09-01",
                "benchmark": "BENCH",
                "investor2_repository": "https://example.invalid/investor2.git",
                "investor2_ref": "research-ref",
                "writer_repository": "example/writer",
                "annual_release": {"month": 2, "day": 14},
            }
        ),
        encoding="utf-8",
    )
    return load_config(path)


def make_snapshot(
    root: Path,
    *,
    config: MarketCacheConfig,
    prefix: str,
    start: str,
    end: str,
) -> dict[str, object]:
    price = root / "prices/us/part-00000.parquet"
    price.parent.mkdir(parents=True)
    price.write_bytes(b"price-bytes")
    universe = root / "universe.parquet"
    universe.write_bytes(b"universe-bytes")
    benchmark = root / "benchmark.parquet"
    benchmark.write_bytes(b"benchmark-bytes")
    files = [
        {"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in (benchmark, price, universe)
    ]
    return {
        "schema_version": "investor2.market-snapshot.v2",
        "source": "Yahoo Finance via yfinance",
        "immutable": True,
        "regions": list(config.regions),
        "start": start,
        "end_exclusive": end,
        "benchmark": config.benchmark,
        "ticker_count": 1,
        "files": files,
        "storage_contract": {
            "writer_repository": config.writer_repository,
            "bucket": config.bucket,
            "prefix": prefix,
            "consumer_repository_authentication": False,
        },
    }


def test_load_config_accepts_non_japan_contract(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    assert config.regions == ("us", "ca")
    assert config.benchmark == "BENCH"
    assert config.start == "2013-04-01"
    assert config.end_exclusive == "2024-09-01"
    assert config.investor2_ref == "research-ref"


def test_validate_manifest_and_readback_use_runtime_contract(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
    )

    validate_manifest(
        manifest,
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
    )

    readback = tmp_path / "readback"
    for entry in manifest["files"]:  # type: ignore[index]
        source = root / entry["path"]  # type: ignore[index]
        target = readback / entry["path"]  # type: ignore[index]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    verify_readback(manifest, readback)


def test_validate_manifest_rejects_mutated_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
    )
    (root / "universe.parquet").write_bytes(b"mutated")

    with pytest.raises(AssertionError, match="size mismatch|SHA-256 mismatch"):
        validate_manifest(
            manifest,
            root,
            config=config,
            prefix=config.base_prefix,
            start=config.start,
            end=config.end_exclusive,
        )


def test_validate_manifest_rejects_contract_mismatch(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
    )
    manifest["regions"] = ["jp"]

    with pytest.raises(AssertionError, match="region contract mismatch"):
        validate_manifest(
            manifest,
            root,
            config=config,
            prefix=config.base_prefix,
            start=config.start,
            end=config.end_exclusive,
        )


def test_sync_plan_parser_handles_json_spacing() -> None:
    plan = "\n".join(
        [
            json.dumps({"action": "skip", "path": "a"}),
            json.dumps({"action": "upload", "path": "b"}),
        ]
    )

    changes = parse_sync_changes(plan)

    assert changes == [{"action": "upload", "path": "b"}]
    with pytest.raises(AssertionError, match="not converged"):
        assert_converged_sync_plan(plan)


def test_converged_sync_plan_accepts_no_mutations() -> None:
    assert_converged_sync_plan(json.dumps({"action": "skip", "path": "a"}))


def test_latest_safe_completed_year_uses_runtime_release_rule() -> None:
    assert latest_safe_completed_year(
        release_month=2,
        release_day=14,
        now=datetime(2027, 2, 13, tzinfo=UTC),
    ) == 2025
    assert latest_safe_completed_year(
        release_month=2,
        release_day=14,
        now=datetime(2027, 2, 14, tzinfo=UTC),
    ) == 2026


def test_annual_prefix_uses_runtime_namespace() -> None:
    assert annual_prefix("custom/extensions/v4", 2025) == "custom/extensions/v4/2025"
    with pytest.raises(ValueError, match="unsupported calendar year"):
        annual_prefix("custom/extensions/v4", 0)


def test_validate_extension_contract_accepts_runtime_market_contract(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    prefix = annual_prefix(config.extensions_prefix, 2025)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=prefix,
        start="2025-01-01",
        end="2026-01-01",
    )
    manifest["extension_contract"] = {
        "calendar_year": 2025,
        "base_prefix": config.base_prefix,
        "append_only": True,
    }

    validate_extension_contract(manifest, config=config, year=2025, prefix=prefix)


def test_validate_extension_contract_rejects_partial_year(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    prefix = annual_prefix(config.extensions_prefix, 2025)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=prefix,
        start="2025-01-01",
        end="2025-08-24",
    )
    manifest["extension_contract"] = {
        "calendar_year": 2025,
        "base_prefix": config.base_prefix,
        "append_only": True,
    }

    with pytest.raises(AssertionError, match="date contract mismatch"):
        validate_extension_contract(manifest, config=config, year=2025, prefix=prefix)
