#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA_VERSION = "investor2.yahoo-market-cache-stats.v1"
EXPECTED_MARKET_SCHEMA = "investor2.market-snapshot.v2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(root: Path, relative: str) -> Path:
    root_resolved = root.resolve()
    path = (root / relative).resolve()
    if path == root_resolved or root_resolved not in path.parents:
        raise AssertionError(f"manifest path escapes cache root: {relative}")
    return path


def load_and_verify_manifest(
    root: Path,
    manifest_path: Path,
    *,
    expected_manifest_sha256: str | None = None,
) -> tuple[dict[str, Any], str, int]:
    raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(raw).hexdigest()
    if expected_manifest_sha256 and manifest_sha != expected_manifest_sha256:
        raise AssertionError(
            f"canonical manifest SHA-256 mismatch: expected {expected_manifest_sha256}, got {manifest_sha}"
        )
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise AssertionError("market cache manifest must be a JSON object")
    if manifest.get("schema_version") != EXPECTED_MARKET_SCHEMA:
        raise AssertionError(f"unexpected market cache schema: {manifest.get('schema_version')}")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise AssertionError("market cache manifest has no files")
    for entry in files:
        if not isinstance(entry, dict):
            raise AssertionError("manifest file entry must be an object")
        relative = str(entry.get("path", ""))
        path = _safe_file(root, relative)
        if not path.is_file():
            raise AssertionError(f"readback missing manifest file: {relative}")
        actual_size = path.stat().st_size
        expected_size = int(entry.get("size_bytes", -1))
        if actual_size != expected_size:
            raise AssertionError(f"readback size mismatch for {relative}: {actual_size} != {expected_size}")
        actual_sha = sha256_file(path)
        expected_sha = str(entry.get("sha256", ""))
        if actual_sha != expected_sha:
            raise AssertionError(f"readback SHA-256 mismatch for {relative}: {actual_sha} != {expected_sha}")
    return manifest, manifest_sha, len(raw)


def _ticker_set(frame: pd.DataFrame, *, context: str) -> set[str]:
    if "Ticker" not in frame.columns:
        raise AssertionError(f"{context} has no Ticker column")
    return {value for value in frame["Ticker"].dropna().astype(str) if value}


def compute_stats(
    root: Path,
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest, manifest_sha, manifest_bytes = load_and_verify_manifest(
        root,
        manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    files: list[dict[str, Any]] = manifest["files"]

    universe_path = root / "universe.parquet"
    benchmark_path = root / "benchmark.parquet"
    if not universe_path.is_file() or not benchmark_path.is_file():
        raise AssertionError("canonical universe.parquet or benchmark.parquet is missing")

    universe = pd.read_parquet(universe_path)
    requested = _ticker_set(universe, context="universe.parquet")
    declared_ticker_count = int(manifest.get("ticker_count", -1))
    if len(requested) != declared_ticker_count:
        raise AssertionError(
            f"universe ticker count disagrees with manifest: {len(requested)} != {declared_ticker_count}"
        )

    price_entries = sorted(
        (entry for entry in files if str(entry.get("path", "")).startswith("prices/") and str(entry.get("path", "")).endswith(".parquet")),
        key=lambda entry: str(entry["path"]),
    )
    if not price_entries:
        raise AssertionError("manifest has no price parquet shards")

    valid_symbols: set[str] = set()
    price_rows_total = 0
    close_observations_total = 0
    price_min_date: str | None = None
    price_max_date: str | None = None
    per_file: list[dict[str, Any]] = []

    for entry in price_entries:
        relative = str(entry["path"])
        path = _safe_file(root, relative)
        frame = pd.read_parquet(path)
        symbols = _ticker_set(frame, context=relative)
        valid_symbols.update(symbols)
        rows = len(frame)
        price_rows_total += rows
        close_observations = int(frame["Close"].notna().sum()) if "Close" in frame.columns else 0
        close_observations_total += close_observations
        shard_min: str | None = None
        shard_max: str | None = None
        if "Date" in frame.columns and not frame.empty:
            dates = pd.to_datetime(frame["Date"], errors="coerce").dropna()
            if not dates.empty:
                shard_min = dates.min().date().isoformat()
                shard_max = dates.max().date().isoformat()
                price_min_date = shard_min if price_min_date is None else min(price_min_date, shard_min)
                price_max_date = shard_max if price_max_date is None else max(price_max_date, shard_max)
        per_file.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "rows": rows,
                "symbols": len(symbols),
                "close_observations": close_observations,
                "min_date": shard_min,
                "max_date": shard_max,
            }
        )

    unexpected_symbols = sorted(valid_symbols - requested)
    if unexpected_symbols:
        raise AssertionError(f"price shards contain symbols outside universe: {unexpected_symbols[:10]}")
    missing_symbols = sorted(requested - valid_symbols)

    benchmark = pd.read_parquet(benchmark_path)
    benchmark_symbols = sorted(_ticker_set(benchmark, context="benchmark.parquet"))
    benchmark_close_observations = int(benchmark["Close"].notna().sum()) if "Close" in benchmark.columns else 0

    actual_data_bytes_total = sum(_safe_file(root, str(entry["path"])).stat().st_size for entry in files)
    declared_data_bytes_total = sum(int(entry["size_bytes"]) for entry in files)
    if actual_data_bytes_total != declared_data_bytes_total:
        raise AssertionError("actual cache bytes disagree with manifest-declared bytes")

    return {
        "schema_version": SCHEMA_VERSION,
        "canonical_manifest_sha256": manifest_sha,
        "canonical_manifest_bytes": manifest_bytes,
        "cache_contract": {
            "source": manifest.get("source"),
            "regions": manifest.get("regions"),
            "start": manifest.get("start"),
            "end_exclusive": manifest.get("end_exclusive"),
            "benchmark": manifest.get("benchmark"),
            "storage_contract": manifest.get("storage_contract"),
        },
        "requested_symbols": len(requested),
        "valid_price_symbols": len(valid_symbols),
        "missing_symbols_count": len(missing_symbols),
        "missing_symbols": missing_symbols,
        "valid_symbol_fraction": len(valid_symbols) / len(requested) if requested else 0.0,
        "price_files_count": len(price_entries),
        "data_files_count": len(files),
        "price_rows_total": price_rows_total,
        "close_observations_total": close_observations_total,
        "price_min_date": price_min_date,
        "price_max_date": price_max_date,
        "benchmark_rows": len(benchmark),
        "benchmark_symbols": benchmark_symbols,
        "benchmark_close_observations": benchmark_close_observations,
        "data_bytes_total": actual_data_bytes_total,
        "cache_bytes_including_manifest": actual_data_bytes_total + manifest_bytes,
        "price_files": per_file,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the immutable investor2 Yahoo market cache readback.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = compute_stats(args.root, expected_manifest_sha256=args.expected_manifest_sha256)
    text = json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
