#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
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

CONFIG_SCHEMA = "investor2.session-state-phase-a-publish.v1"
EVIDENCE_SCHEMA = "investor2.session-state-phase-a-evidence.v1"
OOS_SCHEMA = "investor2.session-state-oos.v2"
UNRESOLVED_CLAIM_STATUSES = {
    "NOT_REPRODUCIBLE_FROM_PUBLISHED_SPEC",
    "NOT_REPRODUCED",
    "REPRODUCED",
}


@dataclass(frozen=True)
class CollectionConfig:
    batch_size: int
    request_pause_seconds: float
    download_timeout_seconds: float


@dataclass(frozen=True)
class AnalysisConfig:
    start: str
    end: str
    train_start: str
    test_start: str
    adjustment: str
    primary_half_life: int
    sensitivity_half_lives: tuple[int, ...]
    min_periods: int
    trading_days: int
    costs_bps_per_side: tuple[float, ...]
    primary_cost_bps_per_side: float
    stress_cost_bps_per_side: float
    one_way_turnover_per_asset_day: float
    minimum_ic: float
    minimum_mse_improvement: float
    minimum_positive_ic_tickers: int
    minimum_primary_ann_return: float
    minimum_primary_sharpe: float
    minimum_stress_ann_return: float
    minimum_stress_sharpe: float
    raw_robustness: bool
    recent_descriptive_start: str

    @property
    def all_half_lives(self) -> tuple[int, ...]:
        return (self.primary_half_life, *self.sensitivity_half_lives)


@dataclass(frozen=True)
class ClaimAnalog:
    claim: str
    ticker: str


@dataclass(frozen=True)
class ClaimAuditConfig:
    unresolved_claims: tuple[str, ...]
    descriptive_analogs: tuple[ClaimAnalog, ...]
    unresolved_status: str


@dataclass(frozen=True)
class EvidenceTarget:
    repository: str
    issue: int


@dataclass(frozen=True)
class ResearchConfig:
    bucket: str
    snapshot_prefix: str
    evidence_prefix: str
    region: str
    tickers: tuple[str, ...]
    benchmark: str
    start: str
    end_exclusive: str
    investor2_repository: str
    investor2_ref: str
    writer_repository: str
    future_phase_status: str
    evidence_target: EvidenceTarget
    collection: CollectionConfig
    analysis: AnalysisConfig
    claim_audit: ClaimAuditConfig

    @property
    def tickers_csv(self) -> str:
        return ",".join(self.tickers)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish one immutable explicit-universe session-state research package."
    )
    parser.add_argument("--config", required=True, type=Path)
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


def _number(payload: dict[str, Any], key: str, *, minimum: float | None = None, strict: bool = False) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"config field {key!r} must be numeric")
    result = float(value)
    if minimum is not None:
        invalid = result <= minimum if strict else result < minimum
        if invalid:
            operator = ">" if strict else ">="
            raise ValueError(f"config field {key!r} must be {operator} {minimum}")
    return result


def _iso_date(value: str, label: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc
    return value


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"config field {key!r} must be an object")
    return value


def _string_tuple(raw: object, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{label} must be a non-empty array")
    values = tuple(str(value).strip() for value in raw)
    if any(not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must contain unique non-empty strings")
    return values


def load_config(path: Path) -> ResearchConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != CONFIG_SCHEMA:
        raise ValueError(f"config must declare schema_version={CONFIG_SCHEMA!r}")

    tickers = tuple(value.upper() for value in _string_tuple(payload.get("tickers"), "tickers"))
    if len(tickers) != len(set(tickers)):
        raise ValueError("tickers must be unique after normalization")

    collection_raw = _object(payload, "collection")
    analysis_raw = _object(payload, "analysis")
    target_raw = _object(payload, "evidence_target")
    claim_raw = _object(payload, "claim_audit")

    sensitivity_raw = analysis_raw.get("sensitivity_half_lives")
    if not isinstance(sensitivity_raw, list):
        raise ValueError("sensitivity_half_lives must be an array")
    sensitivity = tuple(int(value) for value in sensitivity_raw)
    if any(value <= 0 for value in sensitivity) or len(sensitivity) != len(set(sensitivity)):
        raise ValueError("sensitivity_half_lives must contain unique positive integers")

    costs_raw = analysis_raw.get("costs_bps_per_side")
    if not isinstance(costs_raw, list) or not costs_raw:
        raise ValueError("costs_bps_per_side must be a non-empty array")
    costs = tuple(float(value) for value in costs_raw)
    if any(value < 0 for value in costs) or len(costs) != len(set(costs)):
        raise ValueError("costs_bps_per_side must contain unique non-negative values")

    adjustment = _string(analysis_raw, "adjustment")
    if adjustment not in {"adjusted", "raw"}:
        raise ValueError("analysis.adjustment must be adjusted or raw")
    raw_robustness = analysis_raw.get("raw_robustness")
    if not isinstance(raw_robustness, bool):
        raise ValueError("analysis.raw_robustness must be boolean")

    analogs_raw = claim_raw.get("descriptive_analogs")
    if not isinstance(analogs_raw, list):
        raise ValueError("claim_audit.descriptive_analogs must be an array")
    analogs: list[ClaimAnalog] = []
    for item in analogs_raw:
        if not isinstance(item, dict):
            raise ValueError("claim_audit.descriptive_analogs entries must be objects")
        analogs.append(ClaimAnalog(claim=_string(item, "claim"), ticker=_string(item, "ticker").upper()))
    if len({item.claim for item in analogs}) != len(analogs):
        raise ValueError("claim_audit descriptive claim names must be unique")

    unresolved_claims_raw = claim_raw.get("unresolved_claims")
    unresolved_claims = (
        tuple()
        if unresolved_claims_raw == []
        else _string_tuple(unresolved_claims_raw, "claim_audit.unresolved_claims")
    )
    unresolved_status = _string(claim_raw, "unresolved_status")
    if unresolved_status not in UNRESOLVED_CLAIM_STATUSES:
        raise ValueError("unsupported claim_audit.unresolved_status")

    future_status = _string(payload, "future_phase_status")
    if future_status not in {"PENDING_FUTURE_DATA", "READY_FOR_POST_LAUNCH", "COMPLETE"}:
        raise ValueError("unsupported future_phase_status")

    analysis = AnalysisConfig(
        start=_iso_date(_string(analysis_raw, "start"), "analysis.start"),
        end=_iso_date(_string(analysis_raw, "end"), "analysis.end"),
        train_start=_iso_date(_string(analysis_raw, "train_start"), "analysis.train_start"),
        test_start=_iso_date(_string(analysis_raw, "test_start"), "analysis.test_start"),
        adjustment=adjustment,
        primary_half_life=_int(analysis_raw, "primary_half_life"),
        sensitivity_half_lives=sensitivity,
        min_periods=_int(analysis_raw, "min_periods", minimum=2),
        trading_days=_int(analysis_raw, "trading_days"),
        costs_bps_per_side=costs,
        primary_cost_bps_per_side=_number(analysis_raw, "primary_cost_bps_per_side", minimum=0.0),
        stress_cost_bps_per_side=_number(analysis_raw, "stress_cost_bps_per_side", minimum=0.0),
        one_way_turnover_per_asset_day=_number(
            analysis_raw, "one_way_turnover_per_asset_day", minimum=0.0
        ),
        minimum_ic=_number(analysis_raw, "minimum_ic"),
        minimum_mse_improvement=_number(analysis_raw, "minimum_mse_improvement"),
        minimum_positive_ic_tickers=_int(analysis_raw, "minimum_positive_ic_tickers", minimum=0),
        minimum_primary_ann_return=_number(analysis_raw, "minimum_primary_ann_return"),
        minimum_primary_sharpe=_number(analysis_raw, "minimum_primary_sharpe"),
        minimum_stress_ann_return=_number(analysis_raw, "minimum_stress_ann_return"),
        minimum_stress_sharpe=_number(analysis_raw, "minimum_stress_sharpe"),
        raw_robustness=raw_robustness,
        recent_descriptive_start=_iso_date(
            _string(analysis_raw, "recent_descriptive_start"), "analysis.recent_descriptive_start"
        ),
    )

    config = ResearchConfig(
        bucket=_string(payload, "bucket"),
        snapshot_prefix=_string(payload, "snapshot_prefix").strip("/"),
        evidence_prefix=_string(payload, "evidence_prefix").strip("/"),
        region=_string(payload, "region").lower(),
        tickers=tickers,
        benchmark=_string(payload, "benchmark").upper(),
        start=_iso_date(_string(payload, "start"), "start"),
        end_exclusive=_iso_date(_string(payload, "end_exclusive"), "end_exclusive"),
        investor2_repository=_string(payload, "investor2_repository"),
        investor2_ref=_string(payload, "investor2_ref"),
        writer_repository=_string(payload, "writer_repository"),
        future_phase_status=future_status,
        evidence_target=EvidenceTarget(
            repository=_string(target_raw, "repository"),
            issue=_int(target_raw, "issue"),
        ),
        collection=CollectionConfig(
            batch_size=_int(collection_raw, "batch_size"),
            request_pause_seconds=_number(collection_raw, "request_pause_seconds", minimum=0.0),
            download_timeout_seconds=_number(
                collection_raw, "download_timeout_seconds", minimum=0.0, strict=True
            ),
        ),
        analysis=analysis,
        claim_audit=ClaimAuditConfig(
            unresolved_claims=unresolved_claims,
            descriptive_analogs=tuple(analogs),
            unresolved_status=unresolved_status,
        ),
    )

    snapshot_start = date.fromisoformat(config.start)
    snapshot_end = date.fromisoformat(config.end_exclusive)
    analysis_start = date.fromisoformat(analysis.start)
    train_start = date.fromisoformat(analysis.train_start)
    test_start = date.fromisoformat(analysis.test_start)
    analysis_end = date.fromisoformat(analysis.end)
    recent_start = date.fromisoformat(analysis.recent_descriptive_start)
    if snapshot_start >= snapshot_end:
        raise ValueError("snapshot start must be earlier than end_exclusive")
    if not (snapshot_start <= analysis_start <= train_start < test_start <= analysis_end < snapshot_end):
        raise ValueError("analysis dates violate snapshot/train/test ordering")
    if not (analysis_start <= recent_start <= analysis_end):
        raise ValueError("recent_descriptive_start must lie inside the analysis range")
    if analysis.primary_half_life in analysis.sensitivity_half_lives:
        raise ValueError("primary_half_life must not be duplicated in sensitivity_half_lives")
    if analysis.primary_cost_bps_per_side not in analysis.costs_bps_per_side:
        raise ValueError("primary cost must be included in costs_bps_per_side")
    if analysis.stress_cost_bps_per_side not in analysis.costs_bps_per_side:
        raise ValueError("stress cost must be included in costs_bps_per_side")
    if analysis.minimum_positive_ic_tickers > len(config.tickers):
        raise ValueError("minimum_positive_ic_tickers exceeds ticker universe size")
    if config.benchmark not in config.tickers:
        raise ValueError("benchmark must be included in the explicit ticker universe")
    for analog in config.claim_audit.descriptive_analogs:
        if analog.ticker not in config.tickers:
            raise ValueError(f"claim analog ticker is outside the explicit universe: {analog.ticker}")
    return config


def config_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_file_manifest(root: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return entries


def verify_local_files(root: Path, manifest: dict[str, Any]) -> None:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise AssertionError("manifest must declare at least one file")
    resolved_root = root.resolve()
    for entry in files:
        if not isinstance(entry, dict):
            raise AssertionError("manifest file entries must be objects")
        relative = str(entry.get("path", ""))
        path = (root / relative).resolve()
        if resolved_root not in path.parents or not path.is_file():
            raise AssertionError(f"invalid or missing manifest file: {relative}")
        if path.stat().st_size != int(entry.get("size_bytes", -1)):
            raise AssertionError(f"size mismatch: {relative}")
        if sha256_file(path) != str(entry.get("sha256", "")):
            raise AssertionError(f"SHA-256 mismatch: {relative}")


def validate_snapshot_manifest(manifest: dict[str, Any], config: ResearchConfig) -> None:
    expected_collection = {
        "batch_size": config.collection.batch_size,
        "request_pause_seconds": config.collection.request_pause_seconds,
        "download_timeout_seconds": config.collection.download_timeout_seconds,
        "interval": "1d",
        "auto_adjust": False,
        "actions": True,
        "repair": True,
    }
    if manifest.get("schema_version") != "investor2.market-snapshot.v2":
        raise AssertionError("unexpected snapshot schema")
    if manifest.get("source") != "Yahoo Finance via yfinance" or manifest.get("immutable") is not True:
        raise AssertionError("unexpected snapshot source or mutability")
    if manifest.get("start") != config.start or manifest.get("end_exclusive") != config.end_exclusive:
        raise AssertionError("snapshot date contract mismatch")
    if manifest.get("regions") != [config.region] or manifest.get("benchmark") != config.benchmark:
        raise AssertionError("snapshot market contract mismatch")
    if manifest.get("ticker_count") != len(config.tickers):
        raise AssertionError("snapshot ticker count mismatch")
    if manifest.get("universe_contract") != {"mode": "explicit_tickers", "tickers": list(config.tickers)}:
        raise AssertionError("explicit universe contract mismatch")
    if manifest.get("collection_contract") != expected_collection:
        raise AssertionError("snapshot collection contract mismatch")
    storage = manifest.get("storage_contract")
    if not isinstance(storage, dict):
        raise AssertionError("missing snapshot storage contract")
    if storage.get("writer_repository") != config.writer_repository:
        raise AssertionError("snapshot writer mismatch")
    if storage.get("bucket") != config.bucket or storage.get("prefix") != config.snapshot_prefix:
        raise AssertionError("snapshot storage location mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise AssertionError("snapshot manifest has no files")


def expected_oos_spec(config: ResearchConfig, *, half_life: int, adjustment: str) -> dict[str, Any]:
    analysis = config.analysis
    return {
        "tickers": list(config.tickers),
        "benchmark_ticker": config.benchmark,
        "start": analysis.start,
        "end": analysis.end,
        "train_start": analysis.train_start,
        "test_start": analysis.test_start,
        "test_end": analysis.end,
        "adjustment": adjustment,
        "half_life": half_life,
        "min_periods": analysis.min_periods,
        "trading_days": analysis.trading_days,
        "costs_bps_per_side": list(analysis.costs_bps_per_side),
        "primary_cost_bps_per_side": analysis.primary_cost_bps_per_side,
        "stress_cost_bps_per_side": analysis.stress_cost_bps_per_side,
        "one_way_turnover_per_asset_day": analysis.one_way_turnover_per_asset_day,
        "minimum_ic": analysis.minimum_ic,
        "minimum_mse_improvement": analysis.minimum_mse_improvement,
        "minimum_positive_ic_tickers": analysis.minimum_positive_ic_tickers,
        "minimum_primary_ann_return": analysis.minimum_primary_ann_return,
        "minimum_primary_sharpe": analysis.minimum_primary_sharpe,
        "minimum_stress_ann_return": analysis.minimum_stress_ann_return,
        "minimum_stress_sharpe": analysis.minimum_stress_sharpe,
    }


def validate_oos_payload(
    payload: dict[str, Any], config: ResearchConfig, *, half_life: int, adjustment: str
) -> None:
    if payload.get("schema_version") != OOS_SCHEMA:
        raise AssertionError("unexpected OOS schema")
    if payload.get("decision") not in {"USE", "CONDITION", "REJECT"}:
        raise AssertionError("unexpected OOS decision")
    spec = payload.get("specification")
    if not isinstance(spec, dict):
        raise AssertionError("missing OOS specification")
    for key, value in expected_oos_spec(config, half_life=half_life, adjustment=adjustment).items():
        if spec.get(key) != value:
            raise AssertionError(
                f"OOS specification mismatch for {key}: expected={value!r} observed={spec.get(key)!r}"
            )
    predictive = payload.get("predictive")
    strategies = payload.get("strategies")
    tests = payload.get("decision_tests")
    if not isinstance(predictive, dict) or not isinstance(strategies, list) or not strategies:
        raise AssertionError("OOS payload missing predictive or strategy evidence")
    if not isinstance(tests, dict):
        raise AssertionError("OOS payload missing decision tests")
    if predictive.get("ticker_count") != len(config.tickers):
        raise AssertionError("OOS ticker count mismatch")


def verified_remote_root(config: ResearchConfig, prefix: str, destination: Path) -> tuple[Path, dict[str, Any]]:
    remote = f"hf://buckets/{config.bucket}/{prefix}"
    run(["hf", "buckets", "sync", remote, str(destination)])
    manifest_path = destination / "manifest.json"
    manifest = load_manifest(manifest_path)
    verify_readback(manifest, destination)
    return destination, manifest


def ensure_snapshot(
    config: ResearchConfig,
    *,
    investor2: Path,
    revision: str,
    temp_dir: Path,
) -> tuple[Path, dict[str, Any], str]:
    existing = temp_dir / "snapshot-existing-manifest.json"
    if remote_manifest(config.bucket, config.snapshot_prefix, existing):
        manifest = load_manifest(existing)
        validate_snapshot_manifest(manifest, config)
        root, verified = verified_remote_root(config, config.snapshot_prefix, temp_dir / "snapshot-readback")
        validate_snapshot_manifest(verified, config)
        print("SESSION_STATE_SNAPSHOT_RESULT=SKIP_ALREADY_PUBLISHED")
        return root, verified, "SKIP_ALREADY_PUBLISHED"

    output = temp_dir / "snapshot-build"
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
            config.snapshot_prefix,
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
    manifest["provenance"] = {
        "repository": config.investor2_repository,
        "ref": config.investor2_ref,
        "revision": revision,
        "publisher_repository": config.writer_repository,
        "publisher_revision": os.environ.get("GITHUB_SHA", "local"),
        "publisher_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "publisher_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validate_snapshot_manifest(manifest, config)
    verify_local_files(output, manifest)
    publish_snapshot(output, manifest, bucket=config.bucket, prefix=config.snapshot_prefix)
    root, verified = verified_remote_root(config, config.snapshot_prefix, temp_dir / "snapshot-readback")
    validate_snapshot_manifest(verified, config)
    print("SESSION_STATE_SNAPSHOT_RESULT=PUBLISHED")
    return root, verified, "PUBLISHED"


def run_baseline(
    investor2: Path,
    snapshot_root: Path,
    config: ResearchConfig,
    *,
    start: str,
    adjustment: str,
    output: Path,
) -> dict[str, Any]:
    run(
        [
            sys.executable,
            str(investor2 / "scripts/session_state_baseline.py"),
            "--market-snapshot-dir",
            str(snapshot_root),
            "--market-regions",
            config.region,
            "--tickers",
            config.tickers_csv,
            "--start",
            start,
            "--end",
            config.analysis.end,
            "--half-life",
            str(config.analysis.primary_half_life),
            "--min-periods",
            str(config.analysis.min_periods),
            "--trading-days",
            str(config.analysis.trading_days),
            "--adjustment",
            adjustment,
            "--output",
            str(output),
        ],
        cwd=investor2,
    )
    return load_manifest(output)


def run_oos(
    investor2: Path,
    snapshot_root: Path,
    config: ResearchConfig,
    *,
    half_life: int,
    adjustment: str,
    output: Path,
) -> dict[str, Any]:
    analysis = config.analysis
    run(
        [
            sys.executable,
            str(investor2 / "scripts/session_state_oos.py"),
            "--market-snapshot-dir",
            str(snapshot_root),
            "--market-regions",
            config.region,
            "--tickers",
            config.tickers_csv,
            "--benchmark-ticker",
            config.benchmark,
            "--start",
            analysis.start,
            "--end",
            analysis.end,
            "--train-start",
            analysis.train_start,
            "--test-start",
            analysis.test_start,
            "--adjustment",
            adjustment,
            "--half-life",
            str(half_life),
            "--min-periods",
            str(analysis.min_periods),
            "--trading-days",
            str(analysis.trading_days),
            "--costs-bps-per-side",
            ",".join(str(value) for value in analysis.costs_bps_per_side),
            "--primary-cost-bps-per-side",
            str(analysis.primary_cost_bps_per_side),
            "--stress-cost-bps-per-side",
            str(analysis.stress_cost_bps_per_side),
            "--one-way-turnover-per-asset-day",
            str(analysis.one_way_turnover_per_asset_day),
            "--minimum-ic",
            str(analysis.minimum_ic),
            "--minimum-mse-improvement",
            str(analysis.minimum_mse_improvement),
            "--minimum-positive-ic-tickers",
            str(analysis.minimum_positive_ic_tickers),
            "--minimum-primary-ann-return",
            str(analysis.minimum_primary_ann_return),
            "--minimum-primary-sharpe",
            str(analysis.minimum_primary_sharpe),
            "--minimum-stress-ann-return",
            str(analysis.minimum_stress_ann_return),
            "--minimum-stress-sharpe",
            str(analysis.minimum_stress_sharpe),
            "--output",
            str(output),
        ],
        cwd=investor2,
    )
    payload = load_manifest(output)
    validate_oos_payload(payload, config, half_life=half_life, adjustment=adjustment)
    return payload


def build_claim_audit(config: ResearchConfig, baseline: dict[str, Any]) -> dict[str, Any]:
    results = baseline.get("results")
    if not isinstance(results, list):
        raise AssertionError("baseline results are missing")
    by_ticker = {
        str(item.get("Ticker")): item
        for item in results
        if isinstance(item, dict) and isinstance(item.get("Ticker"), str)
    }
    claims: dict[str, Any] = {
        claim: {"status": config.claim_audit.unresolved_status}
        for claim in config.claim_audit.unresolved_claims
    }
    for analog in config.claim_audit.descriptive_analogs:
        result = by_ticker.get(analog.ticker)
        if result is None:
            raise AssertionError(f"baseline missing configured claim analog ticker: {analog.ticker}")
        claims[analog.claim] = {
            "status": config.claim_audit.unresolved_status,
            "ticker": analog.ticker,
            "independent_yahoo_adjusted_analog": result,
        }
    return {
        "schema_version": "investor2.session-state-claim-audit.v1",
        "policy": "published numeric claims are not reconstructed from undocumented assumptions",
        "claims": claims,
    }


def validate_existing_evidence(manifest: dict[str, Any], config: ResearchConfig, *, config_hash: str) -> None:
    if manifest.get("schema_version") != EVIDENCE_SCHEMA or manifest.get("immutable") is not True:
        raise AssertionError("unexpected evidence manifest schema or mutability")
    if manifest.get("config_sha256") != config_hash:
        raise AssertionError("research config changed after immutable evidence publication")
    if manifest.get("snapshot_prefix") != config.snapshot_prefix or manifest.get("evidence_prefix") != config.evidence_prefix:
        raise AssertionError("evidence prefix contract mismatch")
    if manifest.get("primary_result") != f"oos_{config.analysis.adjustment}_h{config.analysis.primary_half_life}.json":
        raise AssertionError("primary result contract mismatch")
    if manifest.get("claim_audit") != "article_claim_audit.json":
        raise AssertionError("claim audit contract mismatch")
    if manifest.get("final_decision") not in {"USE", "CONDITION", "REJECT"}:
        raise AssertionError("invalid final decision")
    if manifest.get("future_phase_status") != config.future_phase_status:
        raise AssertionError("future phase status mismatch")
    target = manifest.get("evidence_target")
    if target != {
        "repository": config.evidence_target.repository,
        "issue": config.evidence_target.issue,
    }:
        raise AssertionError("evidence target mismatch")


def publish_evidence(
    config: ResearchConfig,
    *,
    config_path: Path,
    investor2: Path,
    revision: str,
    snapshot_root: Path,
    snapshot_manifest: dict[str, Any],
    temp_dir: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = temp_dir / "evidence-build"
    root.mkdir(parents=True)

    adjusted_full = run_baseline(
        investor2,
        snapshot_root,
        config,
        start=config.analysis.start,
        adjustment=config.analysis.adjustment,
        output=root / f"baseline_{config.analysis.adjustment}_full.json",
    )
    run_baseline(
        investor2,
        snapshot_root,
        config,
        start=config.analysis.recent_descriptive_start,
        adjustment=config.analysis.adjustment,
        output=root / f"baseline_{config.analysis.adjustment}_recent.json",
    )
    if config.analysis.raw_robustness:
        run_baseline(
            investor2,
            snapshot_root,
            config,
            start=config.analysis.start,
            adjustment="raw",
            output=root / "baseline_raw_full.json",
        )

    claim_audit = build_claim_audit(config, adjusted_full)
    (root / "article_claim_audit.json").write_text(
        json.dumps(claim_audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    primary: dict[str, Any] | None = None
    for half_life in config.analysis.all_half_lives:
        output = root / f"oos_{config.analysis.adjustment}_h{half_life}.json"
        payload = run_oos(
            investor2,
            snapshot_root,
            config,
            half_life=half_life,
            adjustment=config.analysis.adjustment,
            output=output,
        )
        if half_life == config.analysis.primary_half_life:
            primary = payload
    if config.analysis.raw_robustness:
        run_oos(
            investor2,
            snapshot_root,
            config,
            half_life=config.analysis.primary_half_life,
            adjustment="raw",
            output=root / f"oos_raw_h{config.analysis.primary_half_life}.json",
        )
    if primary is None:
        raise AssertionError("primary OOS payload was not produced")

    snapshot_manifest_path = snapshot_root / "manifest.json"
    manifest = {
        "schema_version": EVIDENCE_SCHEMA,
        "immutable": True,
        "config_sha256": config_sha256(config_path),
        "snapshot_prefix": config.snapshot_prefix,
        "snapshot_manifest_sha256": sha256_file(snapshot_manifest_path),
        "snapshot_source_revision": snapshot_manifest.get("provenance", {}).get("revision", "unknown"),
        "evidence_prefix": config.evidence_prefix,
        "analysis_revision": revision,
        "publisher_repository": config.writer_repository,
        "publisher_revision": os.environ.get("GITHUB_SHA", "local"),
        "publisher_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "primary_result": f"oos_{config.analysis.adjustment}_h{config.analysis.primary_half_life}.json",
        "claim_audit": "article_claim_audit.json",
        "final_decision": primary["decision"],
        "future_phase_status": config.future_phase_status,
        "evidence_target": {
            "repository": config.evidence_target.repository,
            "issue": config.evidence_target.issue,
        },
        "files": build_file_manifest(root),
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verify_local_files(root, manifest)
    publish_snapshot(root, manifest, bucket=config.bucket, prefix=config.evidence_prefix)

    verified_root, verified_manifest = verified_remote_root(
        config, config.evidence_prefix, temp_dir / "evidence-readback"
    )
    validate_existing_evidence(verified_manifest, config, config_hash=config_sha256(config_path))
    verified_primary = load_manifest(verified_root / str(verified_manifest["primary_result"]))
    validate_oos_payload(
        verified_primary,
        config,
        half_life=config.analysis.primary_half_life,
        adjustment=config.analysis.adjustment,
    )
    claim = load_manifest(verified_root / str(verified_manifest["claim_audit"]))
    if claim.get("schema_version") != "investor2.session-state-claim-audit.v1":
        raise AssertionError("remote claim-audit readback mismatch")
    return verified_root, verified_manifest, verified_primary


def strategy_for_cost(primary: dict[str, Any], cost: float) -> dict[str, Any]:
    strategies = primary.get("strategies")
    if not isinstance(strategies, list):
        raise AssertionError("primary result has no strategies")
    for row in strategies:
        if isinstance(row, dict) and row.get("cost_bps_per_side") == cost:
            strategy = row.get("session_tilt")
            if isinstance(strategy, dict):
                return strategy
    raise AssertionError(f"strategy cost row is missing: {cost}")


def print_result(
    manifest_path: Path,
    manifest: dict[str, Any],
    primary: dict[str, Any],
    *,
    result: str,
) -> None:
    predictive = primary["predictive"]
    spec = primary["specification"]
    primary_cost = float(spec["primary_cost_bps_per_side"])
    stress_cost = float(spec["stress_cost_bps_per_side"])
    primary_strategy = strategy_for_cost(primary, primary_cost)
    stress_strategy = strategy_for_cost(primary, stress_cost)

    print(f"SESSION_STATE_PHASE_A_RESULT={result}")
    print(f"SESSION_STATE_PHASE_A_DECISION={primary['decision']}")
    print(f"SESSION_STATE_PHASE_A_IC={predictive['information_coefficient']}")
    print(
        "SESSION_STATE_PHASE_A_MSE_IMPROVEMENT_VS_INTERCEPT="
        f"{predictive['mse_improvement_vs_intercept']}"
    )
    print(
        "SESSION_STATE_PHASE_A_MSE_IMPROVEMENT_VS_LAG="
        f"{predictive['mse_improvement_vs_lag_session_spread']}"
    )
    print(f"SESSION_STATE_PHASE_A_POSITIVE_IC_TICKERS={predictive['positive_ic_tickers']}")
    print(f"SESSION_STATE_PHASE_A_PRIMARY_COST_BPS_PER_SIDE={primary_cost}")
    print(f"SESSION_STATE_PHASE_A_AFTER_COST_TOTAL_RETURN={primary_strategy['total_return']}")
    print(
        "SESSION_STATE_PHASE_A_AFTER_COST_ANNUALIZED_RETURN="
        f"{primary_strategy['annualized_arithmetic_return']}"
    )
    print(f"SESSION_STATE_PHASE_A_AFTER_COST_SHARPE={primary_strategy['sharpe']}")
    print(f"SESSION_STATE_PHASE_A_MAX_DRAWDOWN={primary_strategy['max_drawdown']}")
    print(f"SESSION_STATE_PHASE_A_BETA_TO_BENCHMARK={primary_strategy['beta_to_benchmark_close_to_close']}")
    print(
        "SESSION_STATE_PHASE_A_CORRELATION_TO_BENCHMARK="
        f"{primary_strategy['correlation_to_benchmark_close_to_close']}"
    )
    print(f"SESSION_STATE_PHASE_A_STRESS_COST_BPS_PER_SIDE={stress_cost}")
    print(
        "SESSION_STATE_PHASE_A_STRESS_ANNUALIZED_RETURN="
        f"{stress_strategy['annualized_arithmetic_return']}"
    )
    print(f"SESSION_STATE_PHASE_A_STRESS_SHARPE={stress_strategy['sharpe']}")
    print(f"SESSION_STATE_PHASE_A_SNAPSHOT_PREFIX={manifest['snapshot_prefix']}")
    print(f"SESSION_STATE_PHASE_A_SNAPSHOT_MANIFEST_SHA256={manifest['snapshot_manifest_sha256']}")
    print(f"SESSION_STATE_PHASE_A_EVIDENCE_PREFIX={manifest['evidence_prefix']}")
    print(f"SESSION_STATE_PHASE_A_EVIDENCE_MANIFEST_SHA256={sha256_file(manifest_path)}")
    print(f"SESSION_STATE_PHASE_A_SOURCE_REVISION={manifest['snapshot_source_revision']}")
    print(f"SESSION_STATE_PHASE_A_ANALYSIS_REVISION={manifest['analysis_revision']}")
    print(f"SESSION_STATE_PHASE_A_FUTURE_STATUS={manifest['future_phase_status']}")


def publish_from_config(config_path: Path) -> None:
    config = load_config(config_path)
    config_hash = config_sha256(config_path)

    with tempfile.TemporaryDirectory(prefix="investor2-session-state-phase-a-") as temp_raw:
        temp_dir = Path(temp_raw)
        existing_evidence = temp_dir / "evidence-existing-manifest.json"
        if remote_manifest(config.bucket, config.evidence_prefix, existing_evidence):
            manifest = load_manifest(existing_evidence)
            validate_existing_evidence(manifest, config, config_hash=config_hash)
            root, verified_manifest = verified_remote_root(
                config, config.evidence_prefix, temp_dir / "evidence-readback"
            )
            validate_existing_evidence(verified_manifest, config, config_hash=config_hash)
            primary = load_manifest(root / str(verified_manifest["primary_result"]))
            validate_oos_payload(
                primary,
                config,
                half_life=config.analysis.primary_half_life,
                adjustment=config.analysis.adjustment,
            )
            print_result(root / "manifest.json", verified_manifest, primary, result="SKIP_ALREADY_PUBLISHED")
            return

        investor2 = temp_dir / "investor2"
        revision = clone_investor2(
            investor2,
            repository=config.investor2_repository,
            ref=config.investor2_ref,
        )
        snapshot_root, snapshot_manifest, _ = ensure_snapshot(
            config,
            investor2=investor2,
            revision=revision,
            temp_dir=temp_dir,
        )
        evidence_root, manifest, primary = publish_evidence(
            config,
            config_path=config_path,
            investor2=investor2,
            revision=revision,
            snapshot_root=snapshot_root,
            snapshot_manifest=snapshot_manifest,
            temp_dir=temp_dir,
        )
        print_result(evidence_root / "manifest.json", manifest, primary, result="PUBLISHED")


def main() -> None:
    args = parse_args()
    publish_from_config(args.config)


if __name__ == "__main__":
    main()
