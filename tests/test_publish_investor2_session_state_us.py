from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.publish_investor2_session_state_us import (
    evidence_prefix,
    load_config,
    validate_snapshot_contract,
)


def _payload() -> dict[str, object]:
    return {
        "schema_version": "investor2.session-state-us-publish.v1",
        "bucket": "bucket/example",
        "snapshot_prefix": "research/session/input/v1",
        "evidence_prefix": "research/session/evidence/v1",
        "investor2_repository": "https://github.com/example/research.git",
        "investor2_ref": "main",
        "writer_repository": "example/writer",
        "issue_repository": "example/research",
        "issue_number": 42,
        "region": "us",
        "tickers": ["AAA", "BBB", "BENCH"],
        "benchmark": "BENCH",
        "snapshot_start": "2001-01-01",
        "snapshot_end_exclusive": "2026-02-01",
        "train_start": "2021-01-01",
        "test_start": "2025-01-01",
        "test_end": "2026-01-31",
        "trading_days": 250,
        "costs_bps_per_side": [0, 2, 7],
        "primary_cost_bps_per_side": 2,
        "collection": {
            "batch_size": 3,
            "request_pause_seconds": 0.1,
            "download_timeout_seconds": 12,
        },
        "specifications": [
            {
                "id": "adjusted-h90",
                "adjustment": "adjusted",
                "half_life": 90,
                "min_periods": 45,
                "primary": True,
            },
            {
                "id": "raw-h30",
                "adjustment": "raw",
                "half_life": 30,
                "min_periods": 20,
                "primary": False,
            },
        ],
        "post_23_5_status": "PENDING_FUTURE_DATA",
    }


def _config(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    return path, load_config(path)


def test_load_config_is_parameter_driven(tmp_path: Path) -> None:
    _, config = _config(tmp_path)

    assert config.tickers == ("AAA", "BBB", "BENCH")
    assert config.primary_spec.id == "adjusted-h90"
    assert config.primary_cost_bps_per_side == 2.0
    assert config.trading_days == 250
    assert config.batch_size == 3


def test_load_config_rejects_ambiguous_primary_spec(tmp_path: Path) -> None:
    payload = _payload()
    specs = payload["specifications"]
    assert isinstance(specs, list)
    assert isinstance(specs[1], dict)
    specs[1]["primary"] = True
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one specification"):
        load_config(path)


def test_evidence_prefix_is_content_addressed(tmp_path: Path) -> None:
    _, config = _config(tmp_path)
    prefix = evidence_prefix(
        config,
        snapshot_sha="a" * 64,
        source_revision="b" * 40,
        config_sha="c" * 64,
    )

    assert prefix == f"{config.evidence_prefix}/{'a' * 64}/{'b' * 40}/{'c' * 64}"


def test_validate_snapshot_contract_accepts_exact_explicit_universe(tmp_path: Path) -> None:
    _, config = _config(tmp_path)
    manifest = {
        "schema_version": "investor2.market-snapshot.v2",
        "source": "Yahoo Finance via yfinance",
        "immutable": True,
        "regions": ["us"],
        "start": "2001-01-01",
        "end_exclusive": "2026-02-01",
        "benchmark": "BENCH",
        "ticker_count": 3,
        "universe_contract": {"mode": "explicit_tickers", "tickers": ["AAA", "BBB", "BENCH"]},
        "collection_contract": {
            "batch_size": 3,
            "request_pause_seconds": 0.1,
            "download_timeout_seconds": 12.0,
            "interval": "1d",
            "auto_adjust": False,
            "actions": True,
            "repair": True,
        },
        "storage_contract": {
            "writer_repository": "example/writer",
            "bucket": "bucket/example",
            "prefix": "research/session/input/v1",
        },
        "files": [{"path": "universe.parquet", "size_bytes": 1, "sha256": "d" * 64}],
    }

    validate_snapshot_contract(manifest, config)

    manifest["universe_contract"]["tickers"] = ["AAA", "BENCH"]
    with pytest.raises(AssertionError, match="ticker universe"):
        validate_snapshot_contract(manifest, config)
