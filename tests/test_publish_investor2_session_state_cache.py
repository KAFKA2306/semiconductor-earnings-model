from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.publish_investor2_session_state_cache import (
    CONFIG_SCHEMA,
    load_config,
    result_remote_path,
    validate_cache_manifest,
)


def _config_payload() -> dict[str, object]:
    return {
        "schema_version": CONFIG_SCHEMA,
        "bucket": "example/bucket",
        "cache_prefix": "private/cache/v9",
        "result_prefix": "private/results/v4",
        "region": "zz",
        "tickers": ["AAA", "BBB", "CCC"],
        "start": "2010-01-01",
        "end_exclusive": "2026-03-15",
        "benchmark": "AAA",
        "investor2_repository": "https://example.invalid/investor2.git",
        "investor2_ref": "frozen-ref",
        "writer_repository": "example/writer",
        "collection": {
            "batch_size": 3,
            "request_pause_seconds": 0.07,
            "download_timeout_seconds": 11.0,
        },
        "evaluation": {
            "start": "2011-01-01",
            "end": "2026-03-14",
            "train_start": "2018-01-01",
            "test_start": "2024-01-01",
            "adjustment": "raw",
            "half_life": 41,
            "min_periods": 37,
            "trading_days": 247,
            "costs_bps_per_side": [0.0, 2.5, 7.0],
            "primary_cost_bps_per_side": 2.5,
        },
        "evidence_issue": 77,
    }


def _write_config(tmp_path: Path, payload: dict[str, object] | None = None):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload or _config_payload()), encoding="utf-8")
    return path


def test_load_config_has_no_hidden_market_or_evaluation_defaults(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path))

    assert config.bucket == "example/bucket"
    assert config.cache_prefix == "private/cache/v9"
    assert config.result_prefix == "private/results/v4"
    assert config.region == "zz"
    assert config.tickers == ("AAA", "BBB", "CCC")
    assert config.benchmark == "AAA"
    assert config.collection.batch_size == 3
    assert config.collection.request_pause_seconds == pytest.approx(0.07)
    assert config.collection.download_timeout_seconds == pytest.approx(11.0)
    assert config.evaluation.adjustment == "raw"
    assert config.evaluation.half_life == 41
    assert config.evaluation.min_periods == 37
    assert config.evaluation.trading_days == 247
    assert config.evaluation.costs_bps_per_side == (0.0, 2.5, 7.0)
    assert config.evaluation.primary_cost_bps_per_side == pytest.approx(2.5)
    assert config.evidence_issue == 77


def test_load_config_rejects_primary_cost_outside_sensitivity_grid(tmp_path: Path) -> None:
    payload = _config_payload()
    evaluation = payload["evaluation"]
    assert isinstance(evaluation, dict)
    evaluation["primary_cost_bps_per_side"] = 1.0

    with pytest.raises(ValueError, match="primary evaluation cost"):
        load_config(_write_config(tmp_path, payload))


def test_validate_cache_manifest_requires_exact_explicit_universe(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path))
    manifest = {
        "schema_version": "investor2.market-snapshot.v2",
        "source": "Yahoo Finance via yfinance",
        "immutable": True,
        "regions": ["zz"],
        "start": "2010-01-01",
        "end_exclusive": "2026-03-15",
        "benchmark": "AAA",
        "ticker_count": 3,
        "universe_contract": {"mode": "explicit_tickers", "tickers": ["AAA", "BBB", "CCC"]},
        "collection_contract": config.collection.manifest_contract(),
        "storage_contract": {
            "writer_repository": "example/writer",
            "bucket": "example/bucket",
            "prefix": "private/cache/v9",
            "consumer_repository_authentication": False,
        },
        "files": [{"path": "prices/zz/part-00000.parquet", "size_bytes": 1, "sha256": "x"}],
    }

    validate_cache_manifest(manifest, config=config)
    manifest["universe_contract"]["tickers"] = ["AAA", "BBB", "DDD"]
    with pytest.raises(AssertionError, match="ticker universe mismatch"):
        validate_cache_manifest(manifest, config=config)


def test_result_remote_path_is_content_and_analysis_addressed(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path))
    assert result_remote_path(config, manifest_sha="abc", analysis_revision="def") == (
        "private/results/v4/abc/def/result.json"
    )
