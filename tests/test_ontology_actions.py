from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.ontology_actions import (
    ActionAuthorizationError,
    ActionConflictError,
    OntologyActionExecutor,
)
from src.ontology_projection import (
    CONCEPT_PATH,
    OBSERVATION_PATHS,
    REGISTRY_PATHS,
)
from src.data_platform import DataPlatformService
import src.data_platform_rest as rest_api
from src.ontology_runtime import OntologyRuntime

ROOT = Path(__file__).resolve().parents[1]


def action_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    inputs = [
        "ontology/semiconductor.ontology.json",
        CONCEPT_PATH,
        *REGISTRY_PATHS,
        *OBSERVATION_PATHS,
        "data/ontology_runtime/action_state.json",
        "data/ontology_runtime/action_log.jsonl",
    ]
    for relative in inputs:
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return root


def enable_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONTOLOGY_ACTIONS_ENABLED", "1")
    monkeypatch.setenv("ONTOLOGY_ACTION_ACTOR", "pytest-operator")
    monkeypatch.setenv("ONTOLOGY_ACTION_ROLE", "operator")
    monkeypatch.setenv("ONTOLOGY_ACTION_TOKEN", "test-secret")


def test_actions_fail_closed_when_not_enabled(tmp_path: Path) -> None:
    root = action_root(tmp_path)
    executor = OntologyActionExecutor(root)

    with pytest.raises(ActionAuthorizationError, match="disabled"):
        executor.execute(
            action_type="supersedeObservation",
            object_type="Observation",
            primary_key="micron:2026-05-28:eps_diluted:consolidated:actual:gaap",
            parameters={
                "replacement_observation_id":
                    "micron:2026-05-28:eps_diluted:consolidated:actual:non_gaap"
            },
            idempotency_key="disabled-test",
        )


def test_execute_replay_and_rollback_overlay_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = action_root(tmp_path)
    enable_actions(monkeypatch)
    runtime = OntologyRuntime(root)
    executor = OntologyActionExecutor(root, runtime)

    target = "micron:2026-05-28:eps_diluted:consolidated:actual:gaap"
    replacement = (
        "micron:2026-05-28:eps_diluted:consolidated:actual:non_gaap"
    )

    before = runtime.get_object(
        object_type="Observation",
        primary_key=target,
    )
    assert before["record"]["properties"]["status"] == "active"

    result = executor.execute(
        action_type="supersedeObservation",
        object_type="Observation",
        primary_key=target,
        parameters={"replacement_observation_id": replacement},
        idempotency_key="supersede-gaap-eps",
        expected_version=0,
    )
    assert result["status"] == "EXECUTED"
    assert result["action"]["new_version"] == 1

    after = runtime.get_object(
        object_type="Observation",
        primary_key=target,
    )
    assert after["record"]["properties"]["status"] == "superseded"
    assert runtime.build_snapshot()["action_state_version"] == 1

    replay = executor.execute(
        action_type="supersedeObservation",
        object_type="Observation",
        primary_key=target,
        parameters={"replacement_observation_id": replacement},
        idempotency_key="supersede-gaap-eps",
        expected_version=0,
    )
    assert replay["status"] == "IDEMPOTENT_REPLAY"
    assert replay["action"]["action_id"] == result["action"]["action_id"]

    with pytest.raises(ActionConflictError, match="expected_version"):
        executor.execute(
            action_type="supersedeObservation",
            object_type="Observation",
            primary_key=target,
            parameters={"replacement_observation_id": replacement},
            idempotency_key="stale-write",
            expected_version=0,
        )

    rollback = executor.rollback(
        action_id=result["action"]["action_id"],
        idempotency_key="rollback-gaap-eps",
        expected_version=1,
    )
    assert rollback["status"] == "ROLLED_BACK"
    assert rollback["action"]["new_version"] == 2

    restored = runtime.get_object(
        object_type="Observation",
        primary_key=target,
    )
    assert restored["record"]["properties"]["status"] == "active"
    assert runtime.build_snapshot()["action_state_version"] == 2

    log = executor.log()
    assert log["count"] == 2
    assert log["records"][0]["record_type"] == "action"
    assert log["records"][1]["record_type"] == "rollback"
    assert (
        log["records"][1]["previous_hash"]
        == log["records"][0]["record_hash"]
    )


def test_rest_style_token_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = action_root(tmp_path)
    enable_actions(monkeypatch)
    executor = OntologyActionExecutor(root)

    with pytest.raises(ActionAuthorizationError, match="invalid action token"):
        executor.execute(
            action_type="supersedeObservation",
            object_type="Observation",
            primary_key="micron:2026-05-28:eps_diluted:consolidated:actual:gaap",
            parameters={
                "replacement_observation_id":
                    "micron:2026-05-28:eps_diluted:consolidated:actual:non_gaap"
            },
            idempotency_key="wrong-token",
            authorization_token="wrong-secret",
        )


def test_rest_action_endpoint_requires_bearer_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = action_root(tmp_path)
    enable_actions(monkeypatch)
    monkeypatch.setattr(rest_api, "_service", DataPlatformService(root))

    payload = {
        "action_type": "supersedeObservation",
        "object_type": "Observation",
        "primary_key":
            "micron:2026-05-28:eps_diluted:consolidated:actual:gaap",
        "parameters": {
            "replacement_observation_id":
                "micron:2026-05-28:eps_diluted:consolidated:actual:non_gaap"
        },
        "idempotency_key": "rest-action-001",
        "expected_version": 0,
        "dry_run": False,
    }

    with pytest.raises(ActionAuthorizationError, match="invalid action token"):
        rest_api.dispatch_rest(
            "/api/data-platform/v1/ontology/actions/execute",
            method="POST",
            body=payload,
            authorization_token="wrong-secret",
        )

    result = rest_api.dispatch_rest(
        "/api/data-platform/v1/ontology/actions/execute",
        method="POST",
        body=payload,
        authorization_token="test-secret",
    )
    assert result["status"] == "EXECUTED"

    status = rest_api.dispatch_rest(
        "/api/data-platform/v1/ontology/actions/status",
    )
    assert status["global_version"] == 1
    assert status["action_count"] == 1
