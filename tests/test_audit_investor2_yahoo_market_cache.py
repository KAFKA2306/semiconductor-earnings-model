from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from scripts.audit_investor2_yahoo_market_cache import compute_stats


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_cache(root: Path) -> str:
    (root / "prices/jp").mkdir(parents=True)
    pd.DataFrame({"Ticker": ["1001.T", "1002.T", "1003.T"], "Region": ["jp"] * 3}).to_parquet(
        root / "universe.parquet", index=False
    )
    pd.DataFrame(
        {
            "Ticker": ["1306.T", "1306.T"],
            "Date": pd.to_datetime(["2024-01-04", "2024-01-05"]),
            "Close": [10.0, 11.0],
        }
    ).to_parquet(root / "benchmark.parquet", index=False)
    pd.DataFrame(
        {
            "Ticker": ["1001.T", "1001.T", "1002.T"],
            "Date": pd.to_datetime(["2024-01-04", "2024-01-05", "2024-01-05"]),
            "Close": [100.0, 101.0, 200.0],
        }
    ).to_parquet(root / "prices/jp/part-00000.parquet", index=False)

    paths = [root / "benchmark.parquet", root / "prices/jp/part-00000.parquet", root / "universe.parquet"]
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in paths
    ]
    manifest = {
        "schema_version": "investor2.market-snapshot.v2",
        "source": "Yahoo Finance via yfinance",
        "immutable": True,
        "regions": ["jp"],
        "start": "2004-01-01",
        "end_exclusive": "2025-01-01",
        "benchmark": "1306.T",
        "ticker_count": 3,
        "files": files,
        "storage_contract": {
            "writer_repository": "KAFKA2306/semiconductor-earnings-model",
            "bucket": "k4fka/kafka-data-lake",
            "prefix": "central/investor2/private/yahoo-market-cache/v1",
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    return sha256(manifest_path)


def test_compute_stats_counts_real_rows_symbols_missing_and_bytes(tmp_path: Path) -> None:
    manifest_sha = build_cache(tmp_path)

    stats = compute_stats(tmp_path, expected_manifest_sha256=manifest_sha)

    assert stats["requested_symbols"] == 3
    assert stats["valid_price_symbols"] == 2
    assert stats["missing_symbols_count"] == 1
    assert stats["missing_symbols"] == ["1003.T"]
    assert stats["price_rows_total"] == 3
    assert stats["close_observations_total"] == 3
    assert stats["price_files_count"] == 1
    assert stats["data_files_count"] == 3
    assert stats["benchmark_rows"] == 2
    assert stats["price_min_date"] == "2024-01-04"
    assert stats["price_max_date"] == "2024-01-05"
    assert stats["data_bytes_total"] == sum(path.stat().st_size for path in tmp_path.rglob("*.parquet"))
    assert stats["cache_bytes_including_manifest"] == stats["data_bytes_total"] + (tmp_path / "manifest.json").stat().st_size


def test_compute_stats_fails_closed_on_manifest_sha_mismatch(tmp_path: Path) -> None:
    build_cache(tmp_path)

    with pytest.raises(AssertionError, match="canonical manifest SHA-256 mismatch"):
        compute_stats(tmp_path, expected_manifest_sha256="0" * 64)


def test_compute_stats_fails_closed_on_mutated_readback(tmp_path: Path) -> None:
    manifest_sha = build_cache(tmp_path)
    path = tmp_path / "prices/jp/part-00000.parquet"
    path.write_bytes(path.read_bytes() + b"corrupt")

    with pytest.raises(AssertionError, match="readback size mismatch|readback SHA-256 mismatch"):
        compute_stats(tmp_path, expected_manifest_sha256=manifest_sha)
