from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.publish_investor2_yahoo_market_cache import (
    BUCKET,
    PREFIX,
    annual_prefix,
    assert_converged_sync_plan,
    latest_safe_completed_year,
    parse_args,
    parse_sync_changes,
    validate_extension_contract,
    validate_manifest,
    verify_readback,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_snapshot(
    root: Path,
    *,
    prefix: str = PREFIX,
    start: str = "2004-01-01",
    end: str = "2025-01-01",
) -> dict[str, object]:
    price = root / "prices/jp/part-00000.parquet"
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
        "regions": ["jp"],
        "start": start,
        "end_exclusive": end,
        "benchmark": "1306.T",
        "ticker_count": 1,
        "files": files,
        "storage_contract": {
            "writer_repository": "KAFKA2306/semiconductor-earnings-model",
            "bucket": BUCKET,
            "prefix": prefix,
            "consumer_repository_authentication": False,
        },
    }


def test_publisher_defaults_are_japan_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["publish_investor2_yahoo_market_cache.py"])

    args = parse_args()

    assert PREFIX.endswith("/yahoo-market-cache/v1")
    assert args.prefix == PREFIX
    assert args.regions == "jp"
    assert args.start == "2004-01-01"
    assert args.end == "2025-01-01"
    assert args.benchmark == "1306.T"


def test_validate_manifest_and_readback(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    manifest = make_snapshot(root)

    validate_manifest(manifest, root)

    readback = tmp_path / "readback"
    for entry in manifest["files"]:  # type: ignore[index]
        source = root / entry["path"]  # type: ignore[index]
        target = readback / entry["path"]  # type: ignore[index]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    verify_readback(manifest, readback)


def test_validate_manifest_rejects_mutated_file(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    manifest = make_snapshot(root)
    (root / "universe.parquet").write_bytes(b"mutated")

    with pytest.raises(AssertionError, match="size mismatch|SHA-256 mismatch"):
        validate_manifest(manifest, root)


def test_validate_manifest_rejects_non_japan_contract(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    manifest = make_snapshot(root)
    manifest["regions"] = ["us"]

    with pytest.raises(AssertionError, match="region contract mismatch"):
        validate_manifest(manifest, root)


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


def test_latest_safe_completed_year_waits_until_january_seventh() -> None:
    assert latest_safe_completed_year(datetime(2027, 1, 6, tzinfo=UTC)) == 2025
    assert latest_safe_completed_year(datetime(2027, 1, 7, tzinfo=UTC)) == 2026
    assert latest_safe_completed_year(datetime(2026, 8, 23, tzinfo=UTC)) == 2025


def test_annual_prefix_is_append_only_year_namespace() -> None:
    assert annual_prefix(2025) == "central/investor2/private/yahoo-market-cache/extensions/v1/2025"
    with pytest.raises(ValueError, match="unsupported calendar year"):
        annual_prefix(1999)


def test_validate_extension_contract_accepts_exact_japan_calendar_year(tmp_path: Path) -> None:
    prefix = annual_prefix(2025)
    manifest = make_snapshot(tmp_path / "snapshot", prefix=prefix, start="2025-01-01", end="2026-01-01")
    manifest["extension_contract"] = {
        "calendar_year": 2025,
        "base_prefix": PREFIX,
        "append_only": True,
    }

    validate_extension_contract(manifest, year=2025, prefix=prefix)


def test_validate_extension_contract_rejects_partial_year(tmp_path: Path) -> None:
    prefix = annual_prefix(2025)
    manifest = make_snapshot(tmp_path / "snapshot", prefix=prefix, start="2025-01-01", end="2025-08-24")
    manifest["extension_contract"] = {
        "calendar_year": 2025,
        "base_prefix": PREFIX,
        "append_only": True,
    }

    with pytest.raises(AssertionError, match="date contract mismatch"):
        validate_extension_contract(manifest, year=2025, prefix=prefix)


def test_validate_extension_contract_rejects_non_japan_shard(tmp_path: Path) -> None:
    prefix = annual_prefix(2025)
    manifest = make_snapshot(tmp_path / "snapshot", prefix=prefix, start="2025-01-01", end="2026-01-01")
    manifest["regions"] = ["us"]
    manifest["extension_contract"] = {
        "calendar_year": 2025,
        "base_prefix": PREFIX,
        "append_only": True,
    }

    with pytest.raises(AssertionError, match="region contract mismatch"):
        validate_extension_contract(manifest, year=2025, prefix=prefix)
