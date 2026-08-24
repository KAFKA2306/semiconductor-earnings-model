#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.publish_investor2_yahoo_market_cache import (
    clone_investor2,
    load_manifest,
    publish_snapshot,
    remote_manifest,
    run,
    sha256_file,
    verify_readback,
)

CONFIG_SCHEMA = "investor2.session-state-cache.v1"


@dataclass(frozen=True)
class CollectionConfig:
    batch_size: int
    request_pause_seconds: float
    download_timeout_seconds: float

    def manifest_contract(self) -> dict[str, object]:
        return {
            "batch_size": self.batch_size,
            "request_pause_seconds": self.request_pause_seconds,
            "download_timeout_seconds": self.download_timeout_seconds,
            "interval": "1d",
            "auto_adjust": False,
            "actions": True,
            "repair": True,
        }


@dataclass(frozen=True)
class EvaluationConfig:
    start: str
    end: str
    train_start: str
    test_start: str
    adjustment: str
    half_life: int
    min_periods: int
    trading_days: int
    costs_bps_per_side: tuple[float, ...]
    primary_cost_bps_per_side: float


@dataclass(frozen=True)
class SessionStateCacheConfig:
    bucket: str
    cache_prefix: str
    result_prefix: str
    region: str
    tickers: tuple[str, ...]
    start: str
    end_exclusive: str
    benchmark: str
    investor2_repository: str
    investor2_ref: str
    writer_repository: str
    collection: CollectionConfig
    evaluation: EvaluationConfig
    evidence_issue: int | None

    @property
    def tickers_csv(self) -> str:
        return ",".join(self.tickers)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish an explicit investor2 market snapshot to HF, read it back, and evaluate SessionTilt."
    )
    parser.add_argument("--config", type=Path, required=True)
    return parser.parse_args()


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"config field {key!r} must be a non-empty string")
    return value.strip()


def _int(payload: dict[str, Any], key: str, *, minimum: int = 1) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"config field {key!r} must be an integer >= {minimum}")
    return value


def _number(payload: dict[str, Any], key: str, *, minimum: float = 0.0, strict: bool = False) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"config field {key!r} must be numeric")
    number = float(value)
    if (number <= minimum) if strict else (number < minimum):
        comparator = ">" if strict else ">="
        raise ValueError(f"config field {key!r} must be {comparator} {minimum}")
    return number


def load_config(path: Path) -> SessionStateCacheConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != CONFIG_SCHEMA:
        raise ValueError(f"config must declare schema_version={CONFIG_SCHEMA!r}")

    tickers_raw = payload.get("tickers")
    if not isinstance(tickers_raw, list) or not tickers_raw:
        raise ValueError("tickers must be a non-empty array")
    tickers = tuple(str(value).strip().upper() for value in tickers_raw if str(value).strip())
    if len(tickers) != len(tickers_raw) or len(tickers) != len(set(tickers)):
        raise ValueError("tickers must contain unique non-empty symbols")

    collection_raw = payload.get("collection")
    if not isinstance(collection_raw, dict):
        raise ValueError("collection must be an object")
    collection = CollectionConfig(
        batch_size=_int(collection_raw, "batch_size"),
        request_pause_seconds=_number(collection_raw, "request_pause_seconds"),
        download_timeout_seconds=_number(collection_raw, "download_timeout_seconds", strict=True),
    )

    evaluation_raw = payload.get("evaluation")
    if not isinstance(evaluation_raw, dict):
        raise ValueError("evaluation must be an object")
    costs_raw = evaluation_raw.get("costs_bps_per_side")
    if not isinstance(costs_raw, list) or not costs_raw:
        raise ValueError("evaluation.costs_bps_per_side must be a non-empty array")
    costs = tuple(float(value) for value in costs_raw)
    if any(value < 0 for value in costs) or len(costs) != len(set(costs)):
        raise ValueError("evaluation costs must be unique and non-negative")
    primary_cost = _number(evaluation_raw, "primary_cost_bps_per_side")
    if primary_cost not in costs:
        raise ValueError("primary evaluation cost must be present in costs_bps_per_side")
    evaluation = EvaluationConfig(
        start=_string(evaluation_raw, "start"),
        end=_string(evaluation_raw, "end"),
        train_start=_string(evaluation_raw, "train_start"),
        test_start=_string(evaluation_raw, "test_start"),
        adjustment=_string(evaluation_raw, "adjustment"),
        half_life=_int(evaluation_raw, "half_life"),
        min_periods=_int(evaluation_raw, "min_periods", minimum=2),
        trading_days=_int(evaluation_raw, "trading_days"),
        costs_bps_per_side=costs,
        primary_cost_bps_per_side=primary_cost,
    )
    if evaluation.adjustment not in {"adjusted", "raw"}:
        raise ValueError("evaluation.adjustment must be adjusted or raw")

    evidence_issue_raw = payload.get("evidence_issue")
    if evidence_issue_raw is not None and (
        not isinstance(evidence_issue_raw, int) or isinstance(evidence_issue_raw, bool) or evidence_issue_raw < 1
    ):
        raise ValueError("evidence_issue must be null or a positive integer")

    config = SessionStateCacheConfig(
        bucket=_string(payload, "bucket"),
        cache_prefix=_string(payload, "cache_prefix").strip("/"),
        result_prefix=_string(payload, "result_prefix").strip("/"),
        region=_string(payload, "region").lower(),
        tickers=tickers,
        start=_string(payload, "start"),
        end_exclusive=_string(payload, "end_exclusive"),
        benchmark=_string(payload, "benchmark").upper(),
        investor2_repository=_string(payload, "investor2_repository"),
        investor2_ref=_string(payload, "investor2_ref"),
        writer_repository=_string(payload, "writer_repository"),
        collection=collection,
        evaluation=evaluation,
        evidence_issue=evidence_issue_raw,
    )
    if config.benchmark not in config.tickers:
        raise ValueError("benchmark must be included in the explicit ticker universe")
    if not (config.start <= evaluation.start <= evaluation.train_start < evaluation.test_start <= evaluation.end):
        raise ValueError("evaluation date ordering is invalid")
    if evaluation.end >= config.end_exclusive:
        raise ValueError("evaluation end must be covered by the cache end_exclusive")
    return config


def validate_cache_manifest(manifest: dict[str, Any], *, config: SessionStateCacheConfig) -> None:
    if manifest.get("schema_version") != "investor2.market-snapshot.v2":
        raise AssertionError("unexpected market snapshot schema")
    if manifest.get("source") != "Yahoo Finance via yfinance":
        raise AssertionError("unexpected market snapshot source")
    if manifest.get("immutable") is not True:
        raise AssertionError("market snapshot must be immutable")
    if manifest.get("regions") != [config.region]:
        raise AssertionError("market snapshot region mismatch")
    if manifest.get("start") != config.start or manifest.get("end_exclusive") != config.end_exclusive:
        raise AssertionError("market snapshot date mismatch")
    if manifest.get("benchmark") != config.benchmark:
        raise AssertionError("market snapshot benchmark mismatch")
    if manifest.get("ticker_count") != len(config.tickers):
        raise AssertionError("market snapshot ticker count mismatch")

    universe = manifest.get("universe_contract")
    if not isinstance(universe, dict) or universe.get("mode") != "explicit_tickers":
        raise AssertionError("market snapshot must declare explicit ticker universe")
    if universe.get("tickers") != list(config.tickers):
        raise AssertionError("market snapshot ticker universe mismatch")
    if manifest.get("collection_contract") != config.collection.manifest_contract():
        raise AssertionError("market snapshot collection contract mismatch")

    storage = manifest.get("storage_contract")
    if not isinstance(storage, dict):
        raise AssertionError("market snapshot storage contract missing")
    if storage.get("writer_repository") != config.writer_repository:
        raise AssertionError("market snapshot writer mismatch")
    if storage.get("bucket") != config.bucket or storage.get("prefix") != config.cache_prefix:
        raise AssertionError("market snapshot HF path mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise AssertionError("market snapshot file manifest is empty")


def _provenance(revision: str, config: SessionStateCacheConfig) -> dict[str, str]:
    return {
        "repository": config.investor2_repository,
        "ref": config.investor2_ref,
        "revision": revision,
        "publisher_repository": config.writer_repository,
        "publisher_revision": os.environ.get("GITHUB_SHA", "local"),
        "publisher_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "publisher_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
    }


def _build_cache(temp_dir: Path, *, config: SessionStateCacheConfig) -> tuple[dict[str, Any], str]:
    investor2 = temp_dir / "investor2-build"
    revision = clone_investor2(
        investor2,
        repository=config.investor2_repository,
        ref=config.investor2_ref,
    )
    output = temp_dir / "built-cache"
    run(
        [
            sys.executable,
            str(investor2 / "scripts/build_explicit_market_snapshot.py"),
            "--start",
            config.start,
            "--end",
            config.end_exclusive,
            "--region",
            config.region,
            "--tickers",
            config.tickers_csv,
            "--benchmark",
            config.benchmark,
            "--storage-prefix",
            config.cache_prefix,
            "--storage-bucket",
            config.bucket,
            "--writer-repository",
            config.writer_repository,
            "--batch-size",
            str(config.collection.batch_size),
            "--request-pause",
            str(config.collection.request_pause_seconds),
            "--download-timeout",
            str(config.collection.download_timeout_seconds),
            "--output-dir",
            str(output),
        ],
        cwd=investor2,
    )
    manifest_path = output / "manifest.json"
    manifest = load_manifest(manifest_path)
    manifest["provenance"] = _provenance(revision, config)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validate_cache_manifest(manifest, config=config)
    for entry in manifest["files"]:
        path = output / str(entry["path"])
        if path.stat().st_size != int(entry["size_bytes"]) or sha256_file(path) != str(entry["sha256"]):
            raise AssertionError(f"local cache object mismatch: {entry['path']}")
    publish_snapshot(output, manifest, bucket=config.bucket, prefix=config.cache_prefix)
    return manifest, revision


def ensure_cache(temp_dir: Path, *, config: SessionStateCacheConfig) -> tuple[str, dict[str, Any]]:
    existing_manifest_path = temp_dir / "existing-manifest.json"
    if remote_manifest(config.bucket, config.cache_prefix, existing_manifest_path):
        manifest = load_manifest(existing_manifest_path)
        validate_cache_manifest(manifest, config=config)
        return "SKIP_ALREADY_PUBLISHED", manifest
    manifest, _ = _build_cache(temp_dir, config=config)
    return "PUBLISHED", manifest


def readback_cache(temp_dir: Path, *, config: SessionStateCacheConfig) -> tuple[Path, dict[str, Any], str]:
    root = temp_dir / "hf-readback"
    run(["hf", "buckets", "sync", f"hf://buckets/{config.bucket}/{config.cache_prefix}", str(root)])
    manifest = load_manifest(root / "manifest.json")
    validate_cache_manifest(manifest, config=config)
    verify_readback(manifest, root)
    manifest_sha = sha256_file(root / "manifest.json")
    return root, manifest, manifest_sha


def result_remote_path(config: SessionStateCacheConfig, *, manifest_sha: str, analysis_revision: str) -> str:
    return f"{config.result_prefix}/{manifest_sha}/{analysis_revision}/result.json"


def _publish_result(path: Path, *, config: SessionStateCacheConfig, remote_path: str) -> tuple[str, str]:
    expected_sha = sha256_file(path)
    remote = f"hf://buckets/{config.bucket}/{remote_path}"
    existing = path.parent / "existing-result.json"
    probe = subprocess.run(
        ["hf", "buckets", "cp", remote, str(existing)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode == 0:
        if sha256_file(existing) != expected_sha:
            raise AssertionError("immutable result path collision")
        return "SKIP_ALREADY_PUBLISHED", expected_sha
    run(["hf", "buckets", "cp", str(path), remote])
    readback = path.parent / "result-readback.json"
    run(["hf", "buckets", "cp", remote, str(readback)])
    if sha256_file(readback) != expected_sha:
        raise AssertionError("HF result readback SHA-256 mismatch")
    return "PUBLISHED", expected_sha


def evaluate_from_hf(
    temp_dir: Path,
    *,
    config: SessionStateCacheConfig,
    cache_root: Path,
    cache_manifest_sha: str,
) -> tuple[dict[str, Any], str, str, str]:
    investor2 = temp_dir / "investor2-analysis"
    revision = clone_investor2(
        investor2,
        repository=config.investor2_repository,
        ref=config.investor2_ref,
    )
    result_path = temp_dir / "session-state-oos.json"
    evaluation = config.evaluation
    run(
        [
            sys.executable,
            str(investor2 / "scripts/session_state_oos.py"),
            "--market-snapshot-dir",
            str(cache_root),
            "--market-regions",
            config.region,
            "--tickers",
            config.tickers_csv,
            "--start",
            evaluation.start,
            "--end",
            evaluation.end,
            "--train-start",
            evaluation.train_start,
            "--test-start",
            evaluation.test_start,
            "--adjustment",
            evaluation.adjustment,
            "--half-life",
            str(evaluation.half_life),
            "--min-periods",
            str(evaluation.min_periods),
            "--trading-days",
            str(evaluation.trading_days),
            "--costs-bps-per-side",
            ",".join(str(value) for value in evaluation.costs_bps_per_side),
            "--primary-cost-bps-per-side",
            str(evaluation.primary_cost_bps_per_side),
            "--output",
            str(result_path),
        ],
        cwd=investor2,
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["hf_cache_evidence"] = {
        "bucket": config.bucket,
        "prefix": config.cache_prefix,
        "manifest_sha256": cache_manifest_sha,
        "analysis_revision": revision,
        "publisher_repository": config.writer_repository,
        "publisher_revision": os.environ.get("GITHUB_SHA", "local"),
        "publisher_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
    }
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    remote_path = result_remote_path(config, manifest_sha=cache_manifest_sha, analysis_revision=revision)
    publish_result, result_sha = _publish_result(result_path, config=config, remote_path=remote_path)
    return payload, revision, publish_result, result_sha


def _strategy(payload: dict[str, Any], cost: float) -> dict[str, Any]:
    for row in payload["strategies"]:
        if float(row["cost_bps_per_side"]) == cost:
            return row["session_tilt"]
    raise AssertionError(f"missing strategy cost row: {cost}")


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    with tempfile.TemporaryDirectory(prefix="investor2-session-state-hf-") as temp_raw:
        temp_dir = Path(temp_raw)
        cache_result, _ = ensure_cache(temp_dir, config=config)
        cache_root, _, cache_manifest_sha = readback_cache(temp_dir, config=config)
        payload, analysis_revision, result_publish, result_sha = evaluate_from_hf(
            temp_dir,
            config=config,
            cache_root=cache_root,
            cache_manifest_sha=cache_manifest_sha,
        )
        remote_path = result_remote_path(
            config,
            manifest_sha=cache_manifest_sha,
            analysis_revision=analysis_revision,
        )
        predictive = payload["predictive"]
        primary = _strategy(payload, config.evaluation.primary_cost_bps_per_side)
        five = _strategy(payload, 5.0) if 5.0 in config.evaluation.costs_bps_per_side else None
        print(f"SESSION_STATE_CACHE_RESULT={cache_result}")
        print(f"SESSION_STATE_CACHE_PREFIX={config.cache_prefix}")
        print(f"SESSION_STATE_CACHE_MANIFEST_SHA256={cache_manifest_sha}")
        print(f"SESSION_STATE_OOS_RESULT={result_publish}")
        print(f"SESSION_STATE_OOS_RESULT_REMOTE={remote_path}")
        print(f"SESSION_STATE_OOS_RESULT_SHA256={result_sha}")
        print(f"SESSION_STATE_OOS_ANALYSIS_REVISION={analysis_revision}")
        print(f"SESSION_STATE_OOS_DECISION={payload['decision']}")
        print(f"SESSION_STATE_OOS_IC={predictive['information_coefficient']}")
        print(f"SESSION_STATE_OOS_MSE_IMPROVEMENT_VS_INTERCEPT={predictive['mse_improvement_vs_intercept']}")
        print(f"SESSION_STATE_OOS_MSE_IMPROVEMENT_VS_LAG={predictive['mse_improvement_vs_lag_session_spread']}")
        print(f"SESSION_STATE_OOS_POSITIVE_IC_TICKERS={predictive['positive_ic_tickers']}")
        print(f"SESSION_STATE_OOS_PRIMARY_TOTAL_RETURN={primary['total_return']}")
        print(f"SESSION_STATE_OOS_PRIMARY_ANN_RETURN={primary['annualized_arithmetic_return']}")
        print(f"SESSION_STATE_OOS_PRIMARY_SHARPE={primary['sharpe']}")
        print(f"SESSION_STATE_OOS_PRIMARY_MAX_DD={primary['max_drawdown']}")
        print(f"SESSION_STATE_OOS_PRIMARY_BETA={primary['beta_to_spy_close_to_close']}")
        print(f"SESSION_STATE_OOS_PRIMARY_CORR={primary['correlation_to_spy_close_to_close']}")
        if five is not None:
            print(f"SESSION_STATE_OOS_5BPS_ANN_RETURN={five['annualized_arithmetic_return']}")
            print(f"SESSION_STATE_OOS_5BPS_SHARPE={five['sharpe']}")


if __name__ == "__main__":
    main()
