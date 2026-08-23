from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.publish_investor2_yahoo_market_cache import (
    BUCKET,
    PREFIX,
    assert_converged_sync_plan,
    parse_sync_changes,
    validate_manifest,
    verify_readback,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_snapshot(root: Path) -> dict[str, object]:
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
        "ticker_count": 1,
        "files": files,
        "storage_contract": {
            "writer_repository": "KAFKA2306/semiconductor-earnings-model",
            "bucket": BUCKET,
            "prefix": PREFIX,
            "consumer_repository_authentication": False,
        },
    }


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


def test_sync_plan_parser_handles_json_spacing() -> None:
    plan = '\n'.join(
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
