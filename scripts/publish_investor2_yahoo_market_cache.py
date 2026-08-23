#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BUCKET = "k4fka/kafka-data-lake"
PREFIX = "central/investor2/private/yahoo-market-cache/v1"
EXTENSIONS_PREFIX = "central/investor2/private/yahoo-market-cache/extensions/v1"
INVESTOR2_REPOSITORY = "https://github.com/KAFKA2306/investor2.git"
MUTATING_SYNC_ACTIONS = {"upload", "download", "delete"}
ANNUAL_RELEASE_MONTH = 1
ANNUAL_RELEASE_DAY = 7


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish immutable investor2 Japan Yahoo market cache shards through central HF OIDC.")
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--regions", default="jp")
    parser.add_argument("--start", default="2004-01-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--benchmark", default="1306.T")
    parser.add_argument("--extension-year", type=int)
    return parser.parse_args()


def latest_safe_completed_year(now: datetime | None = None) -> int:
    current = now or datetime.now(UTC)
    previous_year = current.year - 1
    if (current.month, current.day) < (ANNUAL_RELEASE_MONTH, ANNUAL_RELEASE_DAY):
        return previous_year - 1
    return previous_year


def annual_prefix(year: int) -> str:
    if year < 2000 or year > 9998:
        raise ValueError(f"unsupported calendar year: {year}")
    return f"{EXTENSIONS_PREFIX}/{year}"


def run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("market cache manifest must be a JSON object")
    return payload


def parse_sync_changes(plan: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for raw in plan.splitlines():
        if not raw.strip():
            continue
        item = json.loads(raw)
        if not isinstance(item, dict):
            raise AssertionError("hf sync plan rows must be JSON objects")
        if item.get("action") in MUTATING_SYNC_ACTIONS:
            changes.append(item)
    return changes


def assert_converged_sync_plan(plan: str) -> None:
    changes = parse_sync_changes(plan)
    if changes:
        raise AssertionError(f"remote market cache is not converged after sync: {changes[:5]}")


def validate_contract_fields(
    manifest: dict[str, Any],
    *,
    bucket: str,
    prefix: str,
    regions: str,
    start: str,
    end: str,
    benchmark: str,
) -> None:
    if manifest.get("schema_version") != "investor2.market-snapshot.v2":
        raise AssertionError("unexpected market snapshot schema")
    if manifest.get("source") != "Yahoo Finance via yfinance":
        raise AssertionError("unexpected market snapshot source")
    if manifest.get("immutable") is not True:
        raise AssertionError("market snapshot must be immutable")
    if manifest.get("regions") != [value.strip().lower() for value in regions.split(",") if value.strip()]:
        raise AssertionError("market snapshot region contract mismatch")
    if manifest.get("start") != start or manifest.get("end_exclusive") != end:
        raise AssertionError("market snapshot date contract mismatch")
    if manifest.get("benchmark") != benchmark:
        raise AssertionError("market snapshot benchmark contract mismatch")
    storage = manifest.get("storage_contract")
    if not isinstance(storage, dict):
        raise AssertionError("missing storage_contract")
    if storage.get("writer_repository") != "KAFKA2306/semiconductor-earnings-model":
        raise AssertionError("writer authority mismatch")
    if storage.get("bucket") != bucket or storage.get("prefix") != prefix:
        raise AssertionError("bucket contract mismatch")


def validate_manifest(
    manifest: dict[str, Any],
    root: Path,
    *,
    prefix: str = PREFIX,
    regions: str = "jp",
    start: str = "2004-01-01",
    end: str = "2025-01-01",
    benchmark: str = "1306.T",
) -> None:
    validate_contract_fields(
        manifest,
        bucket=BUCKET,
        prefix=prefix,
        regions=regions,
        start=start,
        end=end,
        benchmark=benchmark,
    )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise AssertionError("snapshot manifest has no files")
    for entry in files:
        if not isinstance(entry, dict):
            raise AssertionError("snapshot file entry must be an object")
        relative = str(entry.get("path", ""))
        path = (root / relative).resolve()
        if root.resolve() not in path.parents:
            raise AssertionError(f"snapshot file escapes root: {relative}")
        if not path.is_file():
            raise AssertionError(f"missing snapshot file: {relative}")
        if path.stat().st_size != int(entry.get("size_bytes", -1)):
            raise AssertionError(f"size mismatch: {relative}")
        if sha256_file(path) != str(entry.get("sha256", "")):
            raise AssertionError(f"SHA-256 mismatch: {relative}")


def validate_extension_contract(manifest: dict[str, Any], *, year: int, prefix: str) -> None:
    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"
    validate_contract_fields(
        manifest,
        bucket=BUCKET,
        prefix=prefix,
        regions="jp",
        start=start,
        end=end,
        benchmark="1306.T",
    )
    extension = manifest.get("extension_contract")
    if not isinstance(extension, dict):
        raise AssertionError("missing extension_contract")
    if extension.get("calendar_year") != year:
        raise AssertionError("extension calendar_year mismatch")
    if extension.get("base_prefix") != PREFIX:
        raise AssertionError("extension base_prefix mismatch")
    if extension.get("append_only") is not True:
        raise AssertionError("extension must be append-only")


def verify_readback(manifest: dict[str, Any], readback_root: Path) -> None:
    for entry in manifest["files"]:
        relative = str(entry["path"])
        path = readback_root / relative
        if not path.is_file():
            raise AssertionError(f"remote readback missing: {relative}")
        if path.stat().st_size != int(entry["size_bytes"]):
            raise AssertionError(f"remote size mismatch: {relative}")
        if sha256_file(path) != str(entry["sha256"]):
            raise AssertionError(f"remote SHA-256 mismatch: {relative}")


def remote_manifest(bucket: str, prefix: str, destination: Path) -> bool:
    remote = f"hf://buckets/{bucket}/{prefix}/manifest.json"
    result = subprocess.run(
        ["hf", "buckets", "cp", remote, str(destination)],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def clone_investor2(destination: Path) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "",
        }
    )
    subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", INVESTOR2_REPOSITORY, str(destination)],
        check=True,
        env=env,
    )
    subprocess.run(["git", "-C", str(destination), "fetch", "--depth=1", "origin", "main"], check=True, env=env)
    revision = run(["git", "-C", str(destination), "rev-parse", "FETCH_HEAD"], capture=True)
    if len(revision) != 40:
        raise AssertionError(f"invalid investor2 revision: {revision}")
    subprocess.run(["git", "-C", str(destination), "checkout", "--detach", revision], check=True, env=env)
    return revision


def publish_snapshot(root: Path, manifest: dict[str, Any], *, bucket: str, prefix: str) -> None:
    manifest_path = root / "manifest.json"
    staged_manifest = root.parent / "manifest.json"
    shutil.move(manifest_path, staged_manifest)
    remote_root = f"hf://buckets/{bucket}/{prefix}"
    try:
        run(["hf", "buckets", "sync", str(root), remote_root, "--delete", "--dry-run"])
        run(["hf", "buckets", "sync", str(root), remote_root, "--delete"])
        post_plan = run(
            ["hf", "buckets", "sync", str(root), remote_root, "--delete", "--ignore-times", "--dry-run"],
            capture=True,
        )
        assert_converged_sync_plan(post_plan)

        readback = root.parent / "readback"
        run(["hf", "buckets", "sync", remote_root, str(readback)])
        verify_readback(manifest, readback)

        remote_manifest_path = f"{remote_root}/manifest.json"
        run(["hf", "buckets", "cp", str(staged_manifest), remote_manifest_path])
        manifest_readback = root.parent / "manifest-readback.json"
        run(["hf", "buckets", "cp", remote_manifest_path, str(manifest_readback)])
        if sha256_file(staged_manifest) != sha256_file(manifest_readback):
            raise AssertionError("remote manifest SHA-256 mismatch")
    finally:
        if staged_manifest.exists() and not manifest_path.exists():
            shutil.move(staged_manifest, manifest_path)


def _provenance(revision: str) -> dict[str, str]:
    return {
        "repository": "KAFKA2306/investor2",
        "revision": revision,
        "publisher_repository": "KAFKA2306/semiconductor-earnings-model",
        "publisher_revision": os.environ.get("GITHUB_SHA", "local"),
        "publisher_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "publisher_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
    }


def build_snapshot(
    temp_dir: Path,
    *,
    prefix: str,
    start: str,
    end: str,
    extension_year: int | None = None,
) -> tuple[Path, dict[str, Any], str]:
    investor2 = temp_dir / "investor2"
    revision = clone_investor2(investor2)
    output = temp_dir / "snapshot"
    run(
        [
            sys.executable,
            str(investor2 / "scripts/alphazerobeta_build_market_snapshot.py"),
            "--output-dir",
            str(output),
            "--regions",
            "jp",
            "--start",
            start,
            "--end",
            end,
            "--benchmark",
            "1306.T",
            "--storage-prefix",
            prefix,
        ],
        cwd=investor2,
    )
    manifest_path = output / "manifest.json"
    manifest = load_manifest(manifest_path)
    manifest["provenance"] = _provenance(revision)
    if extension_year is not None:
        manifest["extension_contract"] = {
            "calendar_year": extension_year,
            "base_prefix": PREFIX,
            "append_only": True,
        }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validate_manifest(
        manifest,
        output,
        prefix=prefix,
        regions="jp",
        start=start,
        end=end,
        benchmark="1306.T",
    )
    if extension_year is not None:
        validate_extension_contract(manifest, year=extension_year, prefix=prefix)
    return output, manifest, revision


def publish_base(args: argparse.Namespace) -> None:
    with tempfile.TemporaryDirectory(prefix="investor2-yahoo-market-cache-base-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        existing = temp_dir / "existing-manifest.json"
        if remote_manifest(args.bucket, args.prefix, existing):
            manifest = load_manifest(existing)
            validate_contract_fields(
                manifest,
                bucket=args.bucket,
                prefix=args.prefix,
                regions=args.regions,
                start=args.start,
                end=args.end,
                benchmark=args.benchmark,
            )
            files = manifest.get("files")
            if not isinstance(files, list) or not files:
                raise AssertionError("existing remote market cache manifest has no files")
            print("YAHOO_MARKET_CACHE_RESULT=SKIP_ALREADY_PUBLISHED")
            print(f"YAHOO_MARKET_CACHE_TICKERS={manifest.get('ticker_count')}")
            print(f"YAHOO_MARKET_CACHE_FILES={len(files)}")
            print(f"YAHOO_MARKET_CACHE_PREFIX={PREFIX}")
            return

        output, manifest, revision = build_snapshot(
            temp_dir,
            prefix=args.prefix,
            start=args.start,
            end=args.end,
        )
        publish_snapshot(output, manifest, bucket=args.bucket, prefix=args.prefix)
        print("YAHOO_MARKET_CACHE_RESULT=PUBLISHED")
        print(f"YAHOO_MARKET_CACHE_SOURCE_REVISION={revision}")
        print(f"YAHOO_MARKET_CACHE_TICKERS={manifest['ticker_count']}")
        print(f"YAHOO_MARKET_CACHE_FILES={len(manifest['files'])}")
        print(f"YAHOO_MARKET_CACHE_PREFIX={PREFIX}")


def publish_extension(args: argparse.Namespace, year: int) -> None:
    prefix = annual_prefix(year)
    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"
    with tempfile.TemporaryDirectory(prefix=f"investor2-yahoo-market-cache-{year}-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        existing = temp_dir / "existing-manifest.json"
        if remote_manifest(args.bucket, prefix, existing):
            manifest = load_manifest(existing)
            validate_extension_contract(manifest, year=year, prefix=prefix)
            files = manifest.get("files")
            if not isinstance(files, list) or not files:
                raise AssertionError("existing yearly extension manifest has no files")
            print("YAHOO_MARKET_CACHE_EXTENSION_RESULT=SKIP_ALREADY_PUBLISHED")
            print(f"YAHOO_MARKET_CACHE_EXTENSION_YEAR={year}")
            print(f"YAHOO_MARKET_CACHE_EXTENSION_FILES={len(files)}")
            print(f"YAHOO_MARKET_CACHE_EXTENSION_PREFIX={prefix}")
            return

        output, manifest, revision = build_snapshot(
            temp_dir,
            prefix=prefix,
            start=start,
            end=end,
            extension_year=year,
        )
        publish_snapshot(output, manifest, bucket=args.bucket, prefix=prefix)
        print("YAHOO_MARKET_CACHE_EXTENSION_RESULT=PUBLISHED")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_YEAR={year}")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_SOURCE_REVISION={revision}")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_TICKERS={manifest['ticker_count']}")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_FILES={len(manifest['files'])}")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_PREFIX={prefix}")


def main() -> None:
    args = parse_args()
    if args.bucket != BUCKET or args.prefix != PREFIX:
        raise AssertionError("publisher is restricted to the canonical owned bucket prefix")
    if args.regions != "jp" or args.benchmark != "1306.T" or args.start != "2004-01-01" or args.end != "2025-01-01":
        raise AssertionError("publisher is restricted to the canonical Japan AlphaZeroBeta snapshot contract")

    safe_year = latest_safe_completed_year()
    extension_year = safe_year if args.extension_year is None else args.extension_year
    if extension_year > safe_year:
        raise AssertionError(
            f"refusing to freeze incomplete calendar year {extension_year}; latest safe year is {safe_year}"
        )

    publish_base(args)
    publish_extension(args, extension_year)


if __name__ == "__main__":
    main()
