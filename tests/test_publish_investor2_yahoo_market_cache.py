from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.publish_investor2_yahoo_market_cache import (
    CONFIG_SCHEMA,
    MarketCacheConfig,
    annual_prefix,
    assert_converged_sync_plan,
    latest_safe_completed_year,
    load_config,
    parse_args,
    parse_sync_changes,
    validate_extension_contract,
    validate_manifest,
    verify_readback,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_config(tmp_path: Path) -> MarketCacheConfig:
    path = tmp_path / "cache-config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": CONFIG_SCHEMA,
                "bucket": "example-bucket",
                "base_prefix": "market/base/v7",
                "extensions_prefix": "market/extensions/v7",
                "regions": ["xx", "yy"],
                "start": "2013-04-01",
                "end_exclusive": "2024-09-01",
                "benchmark": "BENCH",
                "investor2_repository": "https://example.invalid/investor2.git",
                "investor2_ref": "research-ref",
                "writer_repository": "example/writer",
                "collection": {
                    "page_size": 17,
                    "batch_size": 13,
                    "request_pause_seconds": 0.07,
                    "max_request_attempts": 3,
                    "retry_base_seconds": 1.25,
                    "download_timeout_seconds": 11.0,
                },
                "annual_release": {"month": 2, "day": 14},
                "evidence_issue": 42,
            }
        ),
        encoding="utf-8",
    )
    return load_config(path)


def make_snapshot(
    root: Path,
    *,
    config: MarketCacheConfig,
    prefix: str,
    start: str,
    end: str,
    include_collection: bool = True,
) -> dict[str, object]:
    price = root / "prices/xx/part-00000.parquet"
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
    manifest: dict[str, object] = {
        "schema_version": "investor2.market-snapshot.v2",
        "source": "Yahoo Finance via yfinance",
        "immutable": True,
        "regions": list(config.regions),
        "start": start,
        "end_exclusive": end,
        "benchmark": config.benchmark,
        "ticker_count": 1,
        "files": files,
        "storage_contract": {
            "writer_repository": config.writer_repository,
            "bucket": config.bucket,
            "prefix": prefix,
            "consumer_repository_authentication": False,
        },
    }
    if include_collection:
        manifest["collection_contract"] = config.collection.manifest_contract()
    return manifest


def test_publisher_requires_explicit_config_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["publish_investor2_yahoo_market_cache.py"])
    with pytest.raises(SystemExit):
        parse_args()


def test_load_config_accepts_arbitrary_market_and_collection_contract(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    assert config.regions == ("xx", "yy")
    assert config.benchmark == "BENCH"
    assert config.start == "2013-04-01"
    assert config.end_exclusive == "2024-09-01"
    assert config.investor2_ref == "research-ref"
    assert config.collection.page_size == 17
    assert config.collection.batch_size == 13
    assert config.collection.request_pause_seconds == pytest.approx(0.07)
    assert config.collection.max_request_attempts == 3
    assert config.collection.retry_base_seconds == pytest.approx(1.25)
    assert config.collection.download_timeout_seconds == pytest.approx(11.0)
    assert config.evidence_issue == 42


def test_load_config_rejects_region_aliases_and_incomplete_collection(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": CONFIG_SCHEMA,
                "bucket": "b",
                "base_prefix": "base",
                "extensions_prefix": "ext",
                "regions": ["all"],
                "start": "2020-01-01",
                "end_exclusive": "2021-01-01",
                "benchmark": "B",
                "investor2_repository": "repo",
                "investor2_ref": "ref",
                "writer_repository": "writer",
                "collection": {},
                "annual_release": {"month": 1, "day": 1},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="aliases"):
        load_config(path)


def test_validate_manifest_and_readback_use_runtime_contract(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
    )

    validate_manifest(
        manifest,
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
    )

    readback = tmp_path / "readback"
    for entry in manifest["files"]:  # type: ignore[index]
        source = root / entry["path"]  # type: ignore[index]
        target = readback / entry["path"]  # type: ignore[index]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    verify_readback(manifest, readback)


def test_validate_manifest_rejects_collection_contract_mismatch(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
    )
    collection = manifest["collection_contract"]
    assert isinstance(collection, dict)
    collection["batch_size"] = 999

    with pytest.raises(AssertionError, match="collection contract mismatch"):
        validate_manifest(
            manifest,
            root,
            config=config,
            prefix=config.base_prefix,
            start=config.start,
            end=config.end_exclusive,
        )


def test_validate_existing_immutable_manifest_can_predate_collection_metadata(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
        include_collection=False,
    )

    validate_manifest(
        manifest,
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
        require_collection_contract=False,
    )


def test_validate_manifest_rejects_mutated_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
    )
    (root / "universe.parquet").write_bytes(b"mutated")

    with pytest.raises(AssertionError, match="size mismatch|SHA-256 mismatch"):
        validate_manifest(
            manifest,
            root,
            config=config,
            prefix=config.base_prefix,
            start=config.start,
            end=config.end_exclusive,
        )


def test_validate_manifest_rejects_contract_mismatch(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=config.base_prefix,
        start=config.start,
        end=config.end_exclusive,
    )
    manifest["regions"] = ["other"]

    with pytest.raises(AssertionError, match="region contract mismatch"):
        validate_manifest(
            manifest,
            root,
            config=config,
            prefix=config.base_prefix,
            start=config.start,
            end=config.end_exclusive,
        )


def test_sync_plan_parser_handles_json_spacing() -> None:
    plan = "\n".join(
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


def test_latest_safe_completed_year_uses_runtime_release_rule() -> None:
    assert latest_safe_completed_year(
        release_month=2,
        release_day=14,
        now=datetime(2027, 2, 13, tzinfo=UTC),
    ) == 2025
    assert latest_safe_completed_year(
        release_month=2,
        release_day=14,
        now=datetime(2027, 2, 14, tzinfo=UTC),
    ) == 2026


def test_annual_prefix_uses_runtime_namespace() -> None:
    assert annual_prefix("custom/extensions/v4", 2025) == "custom/extensions/v4/2025"
    with pytest.raises(ValueError, match="unsupported calendar year"):
        annual_prefix("custom/extensions/v4", 0)


def test_validate_extension_contract_accepts_runtime_market_contract(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    prefix = annual_prefix(config.extensions_prefix, 2025)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=prefix,
        start="2025-01-01",
        end="2026-01-01",
    )
    manifest["extension_contract"] = {
        "calendar_year": 2025,
        "base_prefix": config.base_prefix,
        "append_only": True,
    }

    validate_extension_contract(
        manifest,
        config=config,
        year=2025,
        prefix=prefix,
        require_collection_contract=True,
    )


def test_validate_extension_contract_rejects_partial_year(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    prefix = annual_prefix(config.extensions_prefix, 2025)
    root = tmp_path / "snapshot"
    manifest = make_snapshot(
        root,
        config=config,
        prefix=prefix,
        start="2025-01-01",
        end="2025-08-24",
    )
    manifest["extension_contract"] = {
        "calendar_year": 2025,
        "base_prefix": config.base_prefix,
        "append_only": True,
    }

    with pytest.raises(AssertionError, match="date contract mismatch"):
        validate_extension_contract(
            manifest,
            config=config,
            year=2025,
            prefix=prefix,
            require_collection_contract=True,
        )


def make_phase_a_config(tmp_path: Path) -> tuple[object, Path]:
    research = importlib.import_module("scripts.publish_investor2_session_state_research")
    path = tmp_path / "phase-a.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": research.CONFIG_SCHEMA,
                "bucket": "research-bucket",
                "snapshot_prefix": "research/snapshot/v9",
                "evidence_prefix": "research/evidence/v9",
                "region": "zz",
                "tickers": ["AAA", "BBB"],
                "benchmark": "BBB",
                "start": "2010-01-01",
                "end_exclusive": "2025-01-01",
                "investor2_repository": "https://example.invalid/investor2.git",
                "investor2_ref": "frozen-ref",
                "writer_repository": "example/writer",
                "future_phase_status": "PENDING_FUTURE_DATA",
                "evidence_target": {"repository": "example/research", "issue": 77},
                "collection": {
                    "batch_size": 2,
                    "request_pause_seconds": 0.125,
                    "download_timeout_seconds": 19.0,
                },
                "analysis": {
                    "start": "2010-01-01",
                    "end": "2024-12-31",
                    "train_start": "2015-01-01",
                    "test_start": "2022-01-01",
                    "adjustment": "adjusted",
                    "primary_half_life": 17,
                    "sensitivity_half_lives": [9, 33],
                    "min_periods": 12,
                    "trading_days": 240,
                    "costs_bps_per_side": [0.0, 2.0, 9.0],
                    "primary_cost_bps_per_side": 2.0,
                    "stress_cost_bps_per_side": 9.0,
                    "one_way_turnover_per_asset_day": 1.75,
                    "minimum_ic": 0.03,
                    "minimum_mse_improvement": 0.01,
                    "minimum_positive_ic_tickers": 1,
                    "minimum_primary_ann_return": 0.02,
                    "minimum_primary_sharpe": 0.25,
                    "minimum_stress_ann_return": -0.01,
                    "minimum_stress_sharpe": -0.1,
                    "raw_robustness": False,
                    "recent_descriptive_start": "2020-01-01",
                },
                "claim_audit": {
                    "unresolved_claims": ["missing_universe_claim"],
                    "descriptive_analogs": [{"claim": "aaa_long_run", "ticker": "AAA"}],
                    "unresolved_status": "NOT_REPRODUCIBLE_FROM_PUBLISHED_SPEC",
                },
            }
        ),
        encoding="utf-8",
    )
    return research.load_config(path), path


def test_phase_a_config_is_fully_runtime_driven(tmp_path: Path) -> None:
    config, _ = make_phase_a_config(tmp_path)
    assert config.region == "zz"  # type: ignore[attr-defined]
    assert config.tickers == ("AAA", "BBB")  # type: ignore[attr-defined]
    assert config.benchmark == "BBB"  # type: ignore[attr-defined]
    assert config.analysis.primary_half_life == 17  # type: ignore[attr-defined]
    assert config.analysis.sensitivity_half_lives == (9, 33)  # type: ignore[attr-defined]
    assert config.analysis.costs_bps_per_side == (0.0, 2.0, 9.0)  # type: ignore[attr-defined]
    assert config.analysis.one_way_turnover_per_asset_day == pytest.approx(1.75)  # type: ignore[attr-defined]
    assert config.analysis.minimum_ic == pytest.approx(0.03)  # type: ignore[attr-defined]
    assert config.analysis.minimum_positive_ic_tickers == 1  # type: ignore[attr-defined]
    assert config.evidence_target.repository == "example/research"  # type: ignore[attr-defined]


def test_phase_a_snapshot_validation_uses_explicit_universe(tmp_path: Path) -> None:
    research = importlib.import_module("scripts.publish_investor2_session_state_research")
    config, _ = make_phase_a_config(tmp_path)
    manifest = {
        "schema_version": "investor2.market-snapshot.v2",
        "source": "Yahoo Finance via yfinance",
        "immutable": True,
        "start": config.start,
        "end_exclusive": config.end_exclusive,
        "regions": [config.region],
        "benchmark": config.benchmark,
        "ticker_count": len(config.tickers),
        "universe_contract": {"mode": "explicit_tickers", "tickers": list(config.tickers)},
        "collection_contract": {
            "batch_size": config.collection.batch_size,
            "request_pause_seconds": config.collection.request_pause_seconds,
            "download_timeout_seconds": config.collection.download_timeout_seconds,
            "interval": "1d",
            "auto_adjust": False,
            "actions": True,
            "repair": True,
        },
        "storage_contract": {
            "writer_repository": config.writer_repository,
            "bucket": config.bucket,
            "prefix": config.snapshot_prefix,
        },
        "files": [{"path": "prices/zz/part-00000.parquet", "size_bytes": 1, "sha256": "x"}],
    }
    research.validate_snapshot_manifest(manifest, config)
    manifest["benchmark"] = "AAA"
    with pytest.raises(AssertionError, match="market contract mismatch"):
        research.validate_snapshot_manifest(manifest, config)


def test_phase_a_oos_v2_validation_uses_configured_thresholds(tmp_path: Path) -> None:
    research = importlib.import_module("scripts.publish_investor2_session_state_research")
    config, _ = make_phase_a_config(tmp_path)
    spec = research.expected_oos_spec(config, half_life=17, adjustment="adjusted")
    payload = {
        "schema_version": research.OOS_SCHEMA,
        "decision": "CONDITION",
        "specification": spec,
        "predictive": {"ticker_count": 2},
        "strategies": [{}],
        "decision_tests": {},
    }
    research.validate_oos_payload(payload, config, half_life=17, adjustment="adjusted")
    spec["minimum_ic"] = 0.99
    with pytest.raises(AssertionError, match="minimum_ic"):
        research.validate_oos_payload(payload, config, half_life=17, adjustment="adjusted")


def test_phase_a_claim_audit_does_not_hardcode_article_symbols(tmp_path: Path) -> None:
    research = importlib.import_module("scripts.publish_investor2_session_state_research")
    config, _ = make_phase_a_config(tmp_path)
    baseline = {
        "results": [
            {"Ticker": "AAA", "overnight_ann_arithmetic": 0.12, "intraday_ann_arithmetic": -0.04},
            {"Ticker": "BBB", "overnight_ann_arithmetic": 0.03, "intraday_ann_arithmetic": 0.02},
        ]
    }
    audit = research.build_claim_audit(config, baseline)
    assert audit["claims"]["missing_universe_claim"]["status"] == "NOT_REPRODUCIBLE_FROM_PUBLISHED_SPEC"
    assert audit["claims"]["aaa_long_run"]["ticker"] == "AAA"
    assert audit["claims"]["aaa_long_run"]["independent_yahoo_adjusted_analog"]["overnight_ann_arithmetic"] == pytest.approx(0.12)


def test_phase_a_existing_evidence_is_bound_to_config_hash(tmp_path: Path) -> None:
    research = importlib.import_module("scripts.publish_investor2_session_state_research")
    config, path = make_phase_a_config(tmp_path)
    manifest = {
        "schema_version": research.EVIDENCE_SCHEMA,
        "immutable": True,
        "config_sha256": research.config_sha256(path),
        "snapshot_prefix": config.snapshot_prefix,
        "evidence_prefix": config.evidence_prefix,
        "primary_result": "oos_adjusted_h17.json",
        "claim_audit": "article_claim_audit.json",
        "final_decision": "REJECT",
        "future_phase_status": config.future_phase_status,
        "evidence_target": {"repository": "example/research", "issue": 77},
    }
    research.validate_existing_evidence(manifest, config, config_hash=research.config_sha256(path))
    manifest["config_sha256"] = "0" * 64
    with pytest.raises(AssertionError, match="config changed"):
        research.validate_existing_evidence(manifest, config, config_hash=research.config_sha256(path))


def test_post_publishers_execute_only_repo_local_explicit_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = importlib.import_module("scripts.publish_investor2_yahoo_market_cache")
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    configs = repo / "config"
    scripts.mkdir(parents=True)
    configs.mkdir(parents=True)
    driver = scripts / "publish_investor2_yahoo_market_cache.py"
    driver.write_text("# marker\n", encoding="utf-8")
    child = scripts / "child.py"
    child.write_text("# child\n", encoding="utf-8")
    child_config = configs / "child.json"
    child_config.write_text("{}\n", encoding="utf-8")
    parent = configs / "parent.json"
    parent.write_text(
        json.dumps({"post_publishers": [{"script": "scripts/child.py", "config": "config/child.json"}]}),
        encoding="utf-8",
    )
    commands: list[tuple[list[str], Path | None]] = []
    monkeypatch.setattr(publisher, "__file__", str(driver))
    monkeypatch.setattr(publisher, "run", lambda command, *, cwd=None, capture=False: commands.append((command, cwd)) or "")

    publisher.run_post_publishers(parent)

    assert commands == [([sys.executable, str(child), "--config", str(child_config)], repo)]

    outside = tmp_path / "outside.py"
    outside.write_text("# outside\n", encoding="utf-8")
    parent.write_text(
        json.dumps({"post_publishers": [{"script": "../outside.py", "config": "config/child.json"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="repository Python file"):
        publisher.run_post_publishers(parent)
