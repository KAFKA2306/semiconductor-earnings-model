#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
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

CONFIG_SCHEMA = "investor2.session-state-us-publish.v1"
SNAPSHOT_SCHEMA = "investor2.market-snapshot.v2"
EVIDENCE_SCHEMA = "investor2.session-state-us-evidence.v1"


@dataclass(frozen=True)
class SessionSpec:
    id: str
    adjustment: str
    half_life: int
    min_periods: int
    primary: bool


@dataclass(frozen=True)
class SessionStateConfig:
    bucket: str
    snapshot_prefix: str
    evidence_prefix: str
    investor2_repository: str
    investor2_ref: str
    writer_repository: str
    issue_repository: str
    issue_number: int
    region: str
    tickers: tuple[str, ...]
    benchmark: str
    snapshot_start: str
    snapshot_end_exclusive: str
    train_start: str
    test_start: str
    test_end: str
    trading_days: int
    costs_bps_per_side: tuple[float, ...]
    primary_cost_bps_per_side: float
    batch_size: int
    request_pause_seconds: float
    download_timeout_seconds: float
    specifications: tuple[SessionSpec, ...]
    post_23_5_status: str

    @property
    def tickers_csv(self) -> str:
        return ",".join(self.tickers)

    @property
    def primary_spec(self) -> SessionSpec:
        matches = [spec for spec in self.specifications if spec.primary]
        if len(matches) != 1:
            raise AssertionError("exactly one primary specification is required")
        return matches[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize and evaluate the preregistered investor2 U.S. session-state evidence block."
    )
    parser.add_argument("--config", required=True, type=Path)
    return parser.parse_args()


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"config field {key!r} must be a non-empty string")
    return value.strip()


def _required_int(payload: dict[str, Any], key: str, *, minimum: int = 1) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"config field {key!r} must be an integer >= {minimum}")
    return value


def _required_number(payload: dict[str, Any], key: str, *, minimum: float = 0.0) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"config field {key!r} must be numeric")
    result = float(value)
    if result < minimum:
        raise ValueError(f"config field {key!r} must be >= {minimum}")
    return result


def load_config(path: Path) -> SessionStateConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != CONFIG_SCHEMA:
        raise ValueError(f"config must declare schema_version={CONFIG_SCHEMA!r}")

    tickers_raw = payload.get("tickers")
    if not isinstance(tickers_raw, list) or not tickers_raw:
        raise ValueError("tickers must be a non-empty array")
    tickers = tuple(str(value).strip().upper() for value in tickers_raw if str(value).strip())
    if len(tickers) != len(tickers_raw) or len(tickers) != len(set(tickers)):
        raise ValueError("tickers must contain unique non-empty symbols")

    costs_raw = payload.get("costs_bps_per_side")
    if not isinstance(costs_raw, list) or not costs_raw:
        raise ValueError("costs_bps_per_side must be a non-empty array")
    costs = tuple(float(value) for value in costs_raw)
    if any(value < 0 for value in costs) or len(costs) != len(set(costs)):
        raise ValueError("costs_bps_per_side must contain unique non-negative values")

    collection = payload.get("collection")
    if not isinstance(collection, dict):
        raise ValueError("collection must be an object")

    specs_raw = payload.get("specifications")
    if not isinstance(specs_raw, list) or not specs_raw:
        raise ValueError("specifications must be a non-empty array")
    specs: list[SessionSpec] = []
    for raw in specs_raw:
        if not isinstance(raw, dict):
            raise ValueError("each specification must be an object")
        adjustment = _required_string(raw, "adjustment")
        if adjustment not in {"adjusted", "raw"}:
            raise ValueError("specification adjustment must be adjusted or raw")
        primary = raw.get("primary")
        if not isinstance(primary, bool):
            raise ValueError("specification primary must be boolean")
        specs.append(
            SessionSpec(
                id=_required_string(raw, "id"),
                adjustment=adjustment,
                half_life=_required_int(raw, "half_life"),
                min_periods=_required_int(raw, "min_periods"),
                primary=primary,
            )
        )
    if len({spec.id for spec in specs}) != len(specs):
        raise ValueError("specification ids must be unique")
    if sum(spec.primary for spec in specs) != 1:
        raise ValueError("exactly one specification must be primary")

    config = SessionStateConfig(
        bucket=_required_string(payload, "bucket"),
        snapshot_prefix=_required_string(payload, "snapshot_prefix").strip("/"),
        evidence_prefix=_required_string(payload, "evidence_prefix").strip("/"),
        investor2_repository=_required_string(payload, "investor2_repository"),
        investor2_ref=_required_string(payload, "investor2_ref"),
        writer_repository=_required_string(payload, "writer_repository"),
        issue_repository=_required_string(payload, "issue_repository"),
        issue_number=_required_int(payload, "issue_number"),
        region=_required_string(payload, "region").lower(),
        tickers=tickers,
        benchmark=_required_string(payload, "benchmark").upper(),
        snapshot_start=_required_string(payload, "snapshot_start"),
        snapshot_end_exclusive=_required_string(payload, "snapshot_end_exclusive"),
        train_start=_required_string(payload, "train_start"),
        test_start=_required_string(payload, "test_start"),
        test_end=_required_string(payload, "test_end"),
        trading_days=_required_int(payload, "trading_days"),
        costs_bps_per_side=costs,
        primary_cost_bps_per_side=_required_number(payload, "primary_cost_bps_per_side"),
        batch_size=_required_int(collection, "batch_size"),
        request_pause_seconds=_required_number(collection, "request_pause_seconds"),
        download_timeout_seconds=_required_number(collection, "download_timeout_seconds"),
        specifications=tuple(specs),
        post_23_5_status=_required_string(payload, "post_23_5_status"),
    )
    if config.benchmark not in config.tickers:
        raise ValueError("benchmark must be included in tickers")
    if config.primary_cost_bps_per_side not in config.costs_bps_per_side:
        raise ValueError("primary_cost_bps_per_side must appear in costs_bps_per_side")
    if not (
        config.snapshot_start < config.train_start < config.test_start <= config.test_end < config.snapshot_end_exclusive
    ):
        raise ValueError("date contract must satisfy snapshot_start < train_start < test_start <= test_end < end_exclusive")
    return config


def config_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_prefix(config: SessionStateConfig, *, snapshot_sha: str, source_revision: str, config_sha: str) -> str:
    for value, name, length in (
        (snapshot_sha, "snapshot_sha", 64),
        (source_revision, "source_revision", 40),
        (config_sha, "config_sha", 64),
    ):
        if len(value) != length or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError(f"invalid {name}: {value}")
    return f"{config.evidence_prefix}/{snapshot_sha}/{source_revision}/{config_sha}"


def validate_snapshot_contract(manifest: dict[str, Any], config: SessionStateConfig) -> None:
    if manifest.get("schema_version") != SNAPSHOT_SCHEMA:
        raise AssertionError("unexpected snapshot schema")
    if manifest.get("source") != "Yahoo Finance via yfinance" or manifest.get("immutable") is not True:
        raise AssertionError("unexpected snapshot source or mutability")
    if manifest.get("regions") != [config.region]:
        raise AssertionError("snapshot region mismatch")
    if manifest.get("start") != config.snapshot_start or manifest.get("end_exclusive") != config.snapshot_end_exclusive:
        raise AssertionError("snapshot date range mismatch")
    if manifest.get("benchmark") != config.benchmark:
        raise AssertionError("snapshot benchmark mismatch")
    universe = manifest.get("universe_contract")
    if not isinstance(universe, dict) or universe.get("mode") != "explicit_tickers":
        raise AssertionError("snapshot must use explicit_tickers universe")
    if universe.get("tickers") != list(config.tickers):
        raise AssertionError("snapshot ticker universe mismatch")
    collection = manifest.get("collection_contract")
    expected_collection = {
        "batch_size": config.batch_size,
        "request_pause_seconds": config.request_pause_seconds,
        "download_timeout_seconds": config.download_timeout_seconds,
        "interval": "1d",
        "auto_adjust": False,
        "actions": True,
        "repair": True,
    }
    if collection != expected_collection:
        raise AssertionError("snapshot collection contract mismatch")
    storage = manifest.get("storage_contract")
    if not isinstance(storage, dict):
        raise AssertionError("snapshot storage contract missing")
    if storage.get("writer_repository") != config.writer_repository:
        raise AssertionError("snapshot writer mismatch")
    if storage.get("bucket") != config.bucket or storage.get("prefix") != config.snapshot_prefix:
        raise AssertionError("snapshot storage location mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise AssertionError("snapshot files manifest is empty")


def _provenance(config: SessionStateConfig, source_revision: str) -> dict[str, str]:
    return {
        "repository": config.investor2_repository,
        "ref": config.investor2_ref,
        "revision": source_revision,
        "publisher_repository": config.writer_repository,
        "publisher_revision": os.environ.get("GITHUB_SHA", "local"),
        "publisher_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "publisher_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
    }


def _sync_snapshot_from_remote(root: Path, config: SessionStateConfig) -> dict[str, Any]:
    remote_root = f"hf://buckets/{config.bucket}/{config.snapshot_prefix}"
    run(["hf", "buckets", "sync", remote_root, str(root)])
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise AssertionError("remote snapshot readback has no manifest")
    manifest = load_manifest(manifest_path)
    validate_snapshot_contract(manifest, config)
    verify_readback(manifest, root)
    return manifest


def materialize_snapshot(
    temp_dir: Path,
    *,
    config: SessionStateConfig,
    investor2: Path,
    source_revision: str,
) -> tuple[Path, dict[str, Any], str]:
    snapshot_root = temp_dir / "snapshot"
    existing = temp_dir / "remote-manifest.json"
    if remote_manifest(config.bucket, config.snapshot_prefix, existing):
        existing_manifest = load_manifest(existing)
        validate_snapshot_contract(existing_manifest, config)
        manifest = _sync_snapshot_from_remote(snapshot_root, config)
        if sha256_file(existing) != sha256_file(snapshot_root / "manifest.json"):
            raise AssertionError("remote snapshot manifest changed during readback")
        return snapshot_root, manifest, "SKIP_ALREADY_PUBLISHED"

    run(
        [
            sys.executable,
            str(investor2 / "scripts/build_explicit_market_snapshot.py"),
            "--start",
            config.snapshot_start,
            "--end",
            config.snapshot_end_exclusive,
            "--region",
            config.region,
            "--tickers",
            config.tickers_csv,
            "--benchmark",
            config.benchmark,
            "--storage-prefix",
            config.snapshot_prefix,
            "--storage-bucket",
            config.bucket,
            "--writer-repository",
            config.writer_repository,
            "--batch-size",
            str(config.batch_size),
            "--request-pause",
            str(config.request_pause_seconds),
            "--download-timeout",
            str(config.download_timeout_seconds),
            "--output-dir",
            str(snapshot_root),
        ],
        cwd=investor2,
    )
    manifest_path = snapshot_root / "manifest.json"
    manifest = load_manifest(manifest_path)
    manifest["provenance"] = _provenance(config, source_revision)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validate_snapshot_contract(manifest, config)
    verify_readback(manifest, snapshot_root)
    publish_snapshot(snapshot_root, manifest, bucket=config.bucket, prefix=config.snapshot_prefix)
    readback_manifest = _sync_snapshot_from_remote(temp_dir / "snapshot-readback", config)
    if sha256_file(manifest_path) != sha256_file(temp_dir / "snapshot-readback" / "manifest.json"):
        raise AssertionError("published snapshot manifest readback mismatch")
    if readback_manifest != manifest:
        raise AssertionError("published snapshot manifest semantic readback mismatch")
    return snapshot_root, manifest, "PUBLISHED"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return payload


def run_analysis(
    root: Path,
    *,
    config: SessionStateConfig,
    investor2: Path,
    source_revision: str,
) -> tuple[Path, dict[str, dict[str, Any]]]:
    evidence_root = root / "evidence"
    evidence_root.mkdir(parents=True)
    results: dict[str, dict[str, Any]] = {}
    costs_csv = ",".join(str(value) for value in config.costs_bps_per_side)

    for spec in config.specifications:
        oos_path = evidence_root / f"oos-{spec.id}.json"
        run(
            [
                sys.executable,
                str(investor2 / "scripts/session_state_oos.py"),
                "--market-snapshot-dir",
                str(root / "snapshot"),
                "--market-regions",
                config.region,
                "--tickers",
                config.tickers_csv,
                "--start",
                config.snapshot_start,
                "--end",
                config.test_end,
                "--train-start",
                config.train_start,
                "--test-start",
                config.test_start,
                "--adjustment",
                spec.adjustment,
                "--half-life",
                str(spec.half_life),
                "--min-periods",
                str(spec.min_periods),
                "--trading-days",
                str(config.trading_days),
                "--costs-bps-per-side",
                costs_csv,
                "--primary-cost-bps-per-side",
                str(config.primary_cost_bps_per_side),
                "--output",
                str(oos_path),
            ],
            cwd=investor2,
        )
        payload = _load_json(oos_path)
        payload["analysis_provenance"] = _provenance(config, source_revision)
        payload["specification_id"] = spec.id
        payload["is_primary_specification"] = spec.primary
        oos_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        results[spec.id] = payload

        if spec.primary:
            baseline_path = evidence_root / "baseline-primary.json"
            run(
                [
                    sys.executable,
                    str(investor2 / "scripts/session_state_baseline.py"),
                    "--market-snapshot-dir",
                    str(root / "snapshot"),
                    "--market-regions",
                    config.region,
                    "--tickers",
                    config.tickers_csv,
                    "--start",
                    config.snapshot_start,
                    "--end",
                    config.test_end,
                    "--adjustment",
                    spec.adjustment,
                    "--half-life",
                    str(spec.half_life),
                    "--min-periods",
                    str(spec.min_periods),
                    "--trading-days",
                    str(config.trading_days),
                    "--output",
                    str(baseline_path),
                ],
                cwd=investor2,
            )
            baseline = _load_json(baseline_path)
            baseline["analysis_provenance"] = _provenance(config, source_revision)
            baseline_path.write_text(
                json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return evidence_root, results


def build_evidence_manifest(
    evidence_root: Path,
    *,
    config: SessionStateConfig,
    config_path: Path,
    snapshot_manifest_path: Path,
    source_revision: str,
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    snapshot_sha = sha256_file(snapshot_manifest_path)
    config_sha = config_sha256(config_path)
    primary = results[config.primary_spec.id]
    files = []
    for path in sorted(evidence_root.glob("*.json")):
        files.append(
            {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "snapshot_manifest_sha256": snapshot_sha,
        "config_sha256": config_sha,
        "investor2_revision": source_revision,
        "publisher_revision": os.environ.get("GITHUB_SHA", "local"),
        "post_23_5_status": config.post_23_5_status,
        "primary_specification_id": config.primary_spec.id,
        "primary_decision": primary["decision"],
        "primary_predictive": primary["predictive"],
        "primary_decision_tests": primary["decision_tests"],
        "files": files,
    }


def publish_evidence(
    evidence_root: Path,
    manifest: dict[str, Any],
    *,
    config: SessionStateConfig,
    source_revision: str,
    config_path: Path,
) -> tuple[str, str]:
    manifest_path = evidence_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    snapshot_sha = str(manifest["snapshot_manifest_sha256"])
    config_sha = str(manifest["config_sha256"])
    prefix = evidence_prefix(config, snapshot_sha=snapshot_sha, source_revision=source_revision, config_sha=config_sha)
    remote_root = f"hf://buckets/{config.bucket}/{prefix}"
    remote_manifest_path = f"{remote_root}/manifest.json"

    with tempfile.TemporaryDirectory(prefix="investor2-session-evidence-") as temp_raw:
        temp = Path(temp_raw)
        existing = temp / "manifest.json"
        if remote_manifest(config.bucket, prefix, existing):
            if sha256_file(existing) != sha256_file(manifest_path):
                raise AssertionError("immutable evidence prefix already exists with a different manifest")
            readback = temp / "readback"
            run(["hf", "buckets", "sync", remote_root, str(readback)])
            for entry in manifest["files"]:
                path = readback / str(entry["path"])
                if not path.is_file() or path.stat().st_size != int(entry["size_bytes"]):
                    raise AssertionError(f"evidence readback size mismatch: {entry['path']}")
                if sha256_file(path) != str(entry["sha256"]):
                    raise AssertionError(f"evidence readback SHA mismatch: {entry['path']}")
            return prefix, "SKIP_ALREADY_PUBLISHED"

        staged_manifest = temp / "staged-manifest.json"
        shutil.copy2(manifest_path, staged_manifest)
        manifest_path.unlink()
        try:
            for path in sorted(evidence_root.glob("*.json")):
                run(["hf", "buckets", "cp", str(path), f"{remote_root}/{path.name}"])
            readback = temp / "readback"
            run(["hf", "buckets", "sync", remote_root, str(readback)])
            for entry in manifest["files"]:
                path = readback / str(entry["path"])
                if not path.is_file() or path.stat().st_size != int(entry["size_bytes"]):
                    raise AssertionError(f"evidence readback size mismatch: {entry['path']}")
                if sha256_file(path) != str(entry["sha256"]):
                    raise AssertionError(f"evidence readback SHA mismatch: {entry['path']}")
            run(["hf", "buckets", "cp", str(staged_manifest), remote_manifest_path])
            final_readback = temp / "manifest-readback.json"
            run(["hf", "buckets", "cp", remote_manifest_path, str(final_readback)])
            if sha256_file(staged_manifest) != sha256_file(final_readback):
                raise AssertionError("evidence manifest readback SHA mismatch")
        finally:
            if not manifest_path.exists():
                shutil.copy2(staged_manifest, manifest_path)
    return prefix, "PUBLISHED"


def _primary_cost_row(primary: dict[str, Any], cost: float) -> dict[str, Any]:
    rows = primary.get("strategies")
    if not isinstance(rows, list):
        raise AssertionError("primary OOS result has no strategies")
    for row in rows:
        if isinstance(row, dict) and float(row.get("cost_bps_per_side", -1)) == cost:
            return row
    raise AssertionError(f"primary OOS result has no cost row for {cost}")


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    with tempfile.TemporaryDirectory(prefix="investor2-session-state-us-") as temp_raw:
        temp = Path(temp_raw)
        investor2 = temp / "investor2"
        source_revision = clone_investor2(
            investor2,
            repository=config.investor2_repository,
            ref=config.investor2_ref,
        )
        snapshot_root, snapshot_manifest, snapshot_result = materialize_snapshot(
            temp,
            config=config,
            investor2=investor2,
            source_revision=source_revision,
        )
        canonical_snapshot = temp / "snapshot"
        if snapshot_root != canonical_snapshot:
            raise AssertionError("unexpected snapshot root")
        evidence_root, results = run_analysis(
            temp,
            config=config,
            investor2=investor2,
            source_revision=source_revision,
        )
        evidence_manifest = build_evidence_manifest(
            evidence_root,
            config=config,
            config_path=args.config,
            snapshot_manifest_path=canonical_snapshot / "manifest.json",
            source_revision=source_revision,
            results=results,
        )
        evidence_remote, evidence_result = publish_evidence(
            evidence_root,
            evidence_manifest,
            config=config,
            source_revision=source_revision,
            config_path=args.config,
        )
        primary = results[config.primary_spec.id]
        primary_cost = _primary_cost_row(primary, config.primary_cost_bps_per_side)["session_tilt"]
        five_cost = _primary_cost_row(primary, 5.0)["session_tilt"] if 5.0 in config.costs_bps_per_side else None
        print(f"SESSION_STATE_US_SNAPSHOT_RESULT={snapshot_result}")
        print(f"SESSION_STATE_US_SNAPSHOT_PREFIX={config.snapshot_prefix}")
        print(f"SESSION_STATE_US_SNAPSHOT_MANIFEST_SHA256={sha256_file(canonical_snapshot / 'manifest.json')}")
        print(f"SESSION_STATE_US_SOURCE_REVISION={source_revision}")
        print(f"SESSION_STATE_US_EVIDENCE_RESULT={evidence_result}")
        print(f"SESSION_STATE_US_EVIDENCE_PREFIX={evidence_remote}")
        print(f"SESSION_STATE_US_EVIDENCE_MANIFEST_SHA256={sha256_file(evidence_root / 'manifest.json')}")
        print(f"SESSION_STATE_US_PRIMARY_DECISION={primary['decision']}")
        print(f"SESSION_STATE_US_PRIMARY_IC={primary['predictive']['information_coefficient']}")
        print(f"SESSION_STATE_US_PRIMARY_MSE_VS_INTERCEPT={primary['predictive']['mse_improvement_vs_intercept']}")
        print(f"SESSION_STATE_US_PRIMARY_MSE_VS_LAG={primary['predictive']['mse_improvement_vs_lag_session_spread']}")
        print(f"SESSION_STATE_US_PRIMARY_POSITIVE_IC_TICKERS={primary['predictive']['positive_ic_tickers']}")
        print(f"SESSION_STATE_US_PRIMARY_1BP_RETURN={primary_cost['annualized_arithmetic_return']}")
        print(f"SESSION_STATE_US_PRIMARY_1BP_SHARPE={primary_cost['sharpe']}")
        print(f"SESSION_STATE_US_PRIMARY_1BP_MAX_DD={primary_cost['max_drawdown']}")
        print(f"SESSION_STATE_US_PRIMARY_1BP_BETA={primary_cost['beta_to_spy_close_to_close']}")
        print(f"SESSION_STATE_US_PRIMARY_1BP_CORR={primary_cost['correlation_to_spy_close_to_close']}")
        if five_cost is not None:
            print(f"SESSION_STATE_US_PRIMARY_5BP_RETURN={five_cost['annualized_arithmetic_return']}")
            print(f"SESSION_STATE_US_PRIMARY_5BP_SHARPE={five_cost['sharpe']}")
        for spec in config.specifications:
            print(f"SESSION_STATE_US_SENSITIVITY_{spec.id.upper().replace('-', '_')}={results[spec.id]['decision']}")
        print(f"SESSION_STATE_US_POST_23_5_STATUS={config.post_23_5_status}")
        print(f"SESSION_STATE_US_ISSUE={config.issue_repository}#{config.issue_number}")
        if snapshot_manifest.get("ticker_count") != len(config.tickers):
            raise AssertionError("snapshot ticker count changed after analysis")


if __name__ == "__main__":
    main()
