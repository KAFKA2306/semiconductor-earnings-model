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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MUTATING_SYNC_ACTIONS = {"upload", "download", "delete"}
CONFIG_SCHEMA = "investor2.yahoo-market-cache-publish.v1"


@dataclass(frozen=True)
class MarketCollectionConfig:
    page_size: int
    batch_size: int
    request_pause_seconds: float
    max_request_attempts: int
    retry_base_seconds: float
    download_timeout_seconds: float

    def manifest_contract(self) -> dict[str, object]:
        return {
            "page_size": self.page_size,
            "batch_size": self.batch_size,
            "request_pause_seconds": self.request_pause_seconds,
            "max_request_attempts": self.max_request_attempts,
            "retry_base_seconds": self.retry_base_seconds,
            "download_timeout_seconds": self.download_timeout_seconds,
            "interval": "1d",
            "auto_adjust": False,
            "actions": True,
            "repair": True,
        }


@dataclass(frozen=True)
class MarketCacheConfig:
    bucket: str
    base_prefix: str
    extensions_prefix: str
    regions: tuple[str, ...]
    start: str
    end_exclusive: str
    benchmark: str
    investor2_repository: str
    investor2_ref: str
    writer_repository: str
    collection: MarketCollectionConfig
    release_month: int
    release_day: int
    evidence_issue: int | None

    @property
    def regions_csv(self) -> str:
        return ",".join(self.regions)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish immutable investor2 Yahoo market-cache shards from an explicit JSON contract."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--extension-year", type=int)
    return parser.parse_args()


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"config field {key!r} must be a non-empty string")
    return value.strip()


def _required_int(payload: dict[str, Any], key: str, *, minimum: int) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"config field {key!r} must be an integer >= {minimum}")
    return value


def _required_number(payload: dict[str, Any], key: str, *, minimum: float, strict: bool = False) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"config field {key!r} must be numeric")
    number = float(value)
    valid = number > minimum if strict else number >= minimum
    if not valid:
        comparator = ">" if strict else ">="
        raise ValueError(f"config field {key!r} must be {comparator} {minimum}")
    return number


def load_config(path: Path) -> MarketCacheConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("market cache config must be a JSON object")
    if payload.get("schema_version") != CONFIG_SCHEMA:
        raise ValueError(f"market cache config must declare schema_version={CONFIG_SCHEMA!r}")

    regions_raw = payload.get("regions")
    if not isinstance(regions_raw, list) or not regions_raw:
        raise ValueError("config field 'regions' must be a non-empty array")
    regions = tuple(str(value).strip().lower() for value in regions_raw if str(value).strip())
    if len(regions) != len(regions_raw):
        raise ValueError("config field 'regions' must contain only non-empty strings")
    if "all" in regions:
        raise ValueError("region aliases are not allowed; enumerate region codes explicitly")
    if len(regions) != len(set(regions)):
        raise ValueError("config field 'regions' must not contain duplicates")

    collection_raw = payload.get("collection")
    if not isinstance(collection_raw, dict):
        raise ValueError("config field 'collection' must be an object")
    collection = MarketCollectionConfig(
        page_size=_required_int(collection_raw, "page_size", minimum=1),
        batch_size=_required_int(collection_raw, "batch_size", minimum=1),
        request_pause_seconds=_required_number(collection_raw, "request_pause_seconds", minimum=0.0),
        max_request_attempts=_required_int(collection_raw, "max_request_attempts", minimum=1),
        retry_base_seconds=_required_number(collection_raw, "retry_base_seconds", minimum=0.0),
        download_timeout_seconds=_required_number(
            collection_raw,
            "download_timeout_seconds",
            minimum=0.0,
            strict=True,
        ),
    )

    release = payload.get("annual_release")
    if not isinstance(release, dict):
        raise ValueError("config field 'annual_release' must be an object")
    month = _required_int(release, "month", minimum=1)
    day = _required_int(release, "day", minimum=1)
    if month > 12:
        raise ValueError("annual_release.month must be <= 12")
    if day > 31:
        raise ValueError("annual_release.day must be <= 31")

    evidence_issue_raw = payload.get("evidence_issue")
    if evidence_issue_raw is not None and (
        not isinstance(evidence_issue_raw, int) or isinstance(evidence_issue_raw, bool) or evidence_issue_raw < 1
    ):
        raise ValueError("evidence_issue must be null or a positive integer")

    config = MarketCacheConfig(
        bucket=_required_string(payload, "bucket"),
        base_prefix=_required_string(payload, "base_prefix").strip("/"),
        extensions_prefix=_required_string(payload, "extensions_prefix").strip("/"),
        regions=regions,
        start=_required_string(payload, "start"),
        end_exclusive=_required_string(payload, "end_exclusive"),
        benchmark=_required_string(payload, "benchmark"),
        investor2_repository=_required_string(payload, "investor2_repository"),
        investor2_ref=_required_string(payload, "investor2_ref"),
        writer_repository=_required_string(payload, "writer_repository"),
        collection=collection,
        release_month=month,
        release_day=day,
        evidence_issue=evidence_issue_raw,
    )
    if datetime.fromisoformat(config.start) >= datetime.fromisoformat(config.end_exclusive):
        raise ValueError("config start must be earlier than end_exclusive")
    return config


def latest_safe_completed_year(
    *,
    release_month: int,
    release_day: int,
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(UTC)
    previous_year = current.year - 1
    if (current.month, current.day) < (release_month, release_day):
        return previous_year - 1
    return previous_year


def annual_prefix(extensions_prefix: str, year: int) -> str:
    if year < 1 or year > 9998:
        raise ValueError(f"unsupported calendar year: {year}")
    return f"{extensions_prefix.rstrip('/')}/{year}"


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


def validate_collection_contract(
    manifest: dict[str, Any],
    *,
    config: MarketCacheConfig,
    required: bool,
) -> None:
    observed = manifest.get("collection_contract")
    if observed is None and not required:
        return
    if not isinstance(observed, dict):
        raise AssertionError("missing collection_contract")
    expected = config.collection.manifest_contract()
    if observed != expected:
        raise AssertionError(f"market snapshot collection contract mismatch: expected={expected} observed={observed}")


def validate_contract_fields(
    manifest: dict[str, Any],
    *,
    config: MarketCacheConfig,
    prefix: str,
    start: str,
    end: str,
    require_collection_contract: bool = False,
) -> None:
    if manifest.get("schema_version") != "investor2.market-snapshot.v2":
        raise AssertionError("unexpected market snapshot schema")
    if manifest.get("source") != "Yahoo Finance via yfinance":
        raise AssertionError("unexpected market snapshot source")
    if manifest.get("immutable") is not True:
        raise AssertionError("market snapshot must be immutable")
    if manifest.get("regions") != list(config.regions):
        raise AssertionError("market snapshot region contract mismatch")
    if manifest.get("start") != start or manifest.get("end_exclusive") != end:
        raise AssertionError("market snapshot date contract mismatch")
    if manifest.get("benchmark") != config.benchmark:
        raise AssertionError("market snapshot benchmark contract mismatch")

    storage = manifest.get("storage_contract")
    if not isinstance(storage, dict):
        raise AssertionError("missing storage_contract")
    if storage.get("writer_repository") != config.writer_repository:
        raise AssertionError("writer authority mismatch")
    if storage.get("bucket") != config.bucket or storage.get("prefix") != prefix:
        raise AssertionError("bucket contract mismatch")
    validate_collection_contract(manifest, config=config, required=require_collection_contract)


def validate_manifest(
    manifest: dict[str, Any],
    root: Path,
    *,
    config: MarketCacheConfig,
    prefix: str,
    start: str,
    end: str,
    require_collection_contract: bool = True,
) -> None:
    validate_contract_fields(
        manifest,
        config=config,
        prefix=prefix,
        start=start,
        end=end,
        require_collection_contract=require_collection_contract,
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


def validate_extension_contract(
    manifest: dict[str, Any],
    *,
    config: MarketCacheConfig,
    year: int,
    prefix: str,
    require_collection_contract: bool = False,
) -> None:
    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"
    validate_contract_fields(
        manifest,
        config=config,
        prefix=prefix,
        start=start,
        end=end,
        require_collection_contract=require_collection_contract,
    )
    extension = manifest.get("extension_contract")
    if not isinstance(extension, dict):
        raise AssertionError("missing extension_contract")
    if extension.get("calendar_year") != year:
        raise AssertionError("extension calendar_year mismatch")
    if extension.get("base_prefix") != config.base_prefix:
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


def clone_investor2(destination: Path, *, repository: str, ref: str) -> str:
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
        ["git", "clone", "--filter=blob:none", "--no-checkout", repository, str(destination)],
        check=True,
        env=env,
    )
    subprocess.run(["git", "-C", str(destination), "fetch", "--depth=1", "origin", ref], check=True, env=env)
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


def _provenance(revision: str, config: MarketCacheConfig) -> dict[str, str]:
    return {
        "repository": config.investor2_repository,
        "ref": config.investor2_ref,
        "revision": revision,
        "publisher_repository": config.writer_repository,
        "publisher_revision": os.environ.get("GITHUB_SHA", "local"),
        "publisher_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "publisher_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
    }


def build_snapshot(
    temp_dir: Path,
    *,
    config: MarketCacheConfig,
    prefix: str,
    start: str,
    end: str,
    extension_year: int | None = None,
) -> tuple[Path, dict[str, Any], str]:
    investor2 = temp_dir / "investor2"
    revision = clone_investor2(
        investor2,
        repository=config.investor2_repository,
        ref=config.investor2_ref,
    )
    output = temp_dir / "snapshot"
    collection = config.collection
    run(
        [
            sys.executable,
            str(investor2 / "scripts/alphazerobeta_build_market_snapshot.py"),
            "--output-dir",
            str(output),
            "--regions",
            config.regions_csv,
            "--start",
            start,
            "--end",
            end,
            "--benchmark",
            config.benchmark,
            "--storage-prefix",
            prefix,
            "--storage-bucket",
            config.bucket,
            "--writer-repository",
            config.writer_repository,
            "--page-size",
            str(collection.page_size),
            "--batch-size",
            str(collection.batch_size),
            "--request-pause",
            str(collection.request_pause_seconds),
            "--max-request-attempts",
            str(collection.max_request_attempts),
            "--retry-base-seconds",
            str(collection.retry_base_seconds),
            "--download-timeout",
            str(collection.download_timeout_seconds),
        ],
        cwd=investor2,
    )
    manifest_path = output / "manifest.json"
    manifest = load_manifest(manifest_path)
    manifest["provenance"] = _provenance(revision, config)
    if extension_year is not None:
        manifest["extension_contract"] = {
            "calendar_year": extension_year,
            "base_prefix": config.base_prefix,
            "append_only": True,
        }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validate_manifest(
        manifest,
        output,
        config=config,
        prefix=prefix,
        start=start,
        end=end,
        require_collection_contract=True,
    )
    if extension_year is not None:
        validate_extension_contract(
            manifest,
            config=config,
            year=extension_year,
            prefix=prefix,
            require_collection_contract=True,
        )
    return output, manifest, revision


def publish_base(config: MarketCacheConfig) -> None:
    with tempfile.TemporaryDirectory(prefix="investor2-yahoo-market-cache-base-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        existing = temp_dir / "existing-manifest.json"
        if remote_manifest(config.bucket, config.base_prefix, existing):
            manifest = load_manifest(existing)
            validate_contract_fields(
                manifest,
                config=config,
                prefix=config.base_prefix,
                start=config.start,
                end=config.end_exclusive,
                require_collection_contract=False,
            )
            files = manifest.get("files")
            if not isinstance(files, list) or not files:
                raise AssertionError("existing remote market cache manifest has no files")
            print("YAHOO_MARKET_CACHE_RESULT=SKIP_ALREADY_PUBLISHED")
            print(f"YAHOO_MARKET_CACHE_TICKERS={manifest.get('ticker_count')}")
            print(f"YAHOO_MARKET_CACHE_FILES={len(files)}")
            print(f"YAHOO_MARKET_CACHE_PREFIX={config.base_prefix}")
            return

        output, manifest, revision = build_snapshot(
            temp_dir,
            config=config,
            prefix=config.base_prefix,
            start=config.start,
            end=config.end_exclusive,
        )
        publish_snapshot(output, manifest, bucket=config.bucket, prefix=config.base_prefix)
        print("YAHOO_MARKET_CACHE_RESULT=PUBLISHED")
        print(f"YAHOO_MARKET_CACHE_SOURCE_REVISION={revision}")
        print(f"YAHOO_MARKET_CACHE_TICKERS={manifest['ticker_count']}")
        print(f"YAHOO_MARKET_CACHE_FILES={len(manifest['files'])}")
        print(f"YAHOO_MARKET_CACHE_PREFIX={config.base_prefix}")


def publish_extension(config: MarketCacheConfig, year: int) -> None:
    prefix = annual_prefix(config.extensions_prefix, year)
    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"
    with tempfile.TemporaryDirectory(prefix=f"investor2-yahoo-market-cache-{year}-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        existing = temp_dir / "existing-manifest.json"
        if remote_manifest(config.bucket, prefix, existing):
            manifest = load_manifest(existing)
            validate_extension_contract(
                manifest,
                config=config,
                year=year,
                prefix=prefix,
                require_collection_contract=False,
            )
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
            config=config,
            prefix=prefix,
            start=start,
            end=end,
            extension_year=year,
        )
        publish_snapshot(output, manifest, bucket=config.bucket, prefix=prefix)
        print("YAHOO_MARKET_CACHE_EXTENSION_RESULT=PUBLISHED")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_YEAR={year}")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_SOURCE_REVISION={revision}")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_TICKERS={manifest['ticker_count']}")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_FILES={len(manifest['files'])}")
        print(f"YAHOO_MARKET_CACHE_EXTENSION_PREFIX={prefix}")


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    safe_year = latest_safe_completed_year(
        release_month=config.release_month,
        release_day=config.release_day,
    )
    extension_year = safe_year if args.extension_year is None else args.extension_year
    if extension_year > safe_year:
        raise AssertionError(
            f"refusing to freeze incomplete calendar year {extension_year}; latest safe year is {safe_year}"
        )

    publish_base(config)
    publish_extension(config, extension_year)


if __name__ == "__main__":
    main()
