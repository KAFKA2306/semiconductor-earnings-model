from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from src.ontology_runtime import OntologyContractError, OntologyRuntime

ACTION_STATE_SCHEMA_VERSION = "ontology-action-state.v1"
ACTION_LOG_SCHEMA_VERSION = "ontology-action-log.v1"


class ActionError(RuntimeError):
    pass


class ActionAuthorizationError(ActionError):
    pass


class ActionConflictError(ActionError):
    pass


class ActionValidationError(ActionError):
    pass


class OntologyActionExecutor:
    """Controlled ontology mutations written only to an audited overlay."""

    def __init__(
        self,
        root: Path | str,
        ontology: OntologyRuntime | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.ontology = ontology or OntologyRuntime(self.root)
        self.runtime_dir = self.root / "data" / "ontology_runtime"
        self.state_path = self.runtime_dir / "action_state.json"
        self.log_path = self.runtime_dir / "action_log.jsonl"
        self.lock_path = self.runtime_dir / ".action.lock"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _canonical(payload: Any) -> str:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _record_hash(record: dict[str, Any]) -> str:
        payload = dict(record)
        payload.pop("record_hash", None)
        return hashlib.sha256(
            OntologyActionExecutor._canonical(payload).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _target_key(object_type: str, primary_key: str) -> str:
        return f"{object_type}|{primary_key}"

    def _ensure_storage(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self._write_state(
                {
                    "schema_version": ACTION_STATE_SCHEMA_VERSION,
                    "global_version": 0,
                    "overrides": {},
                }
            )
        if not self.log_path.exists():
            self.log_path.write_text("", encoding="utf-8")

    def _read_state(self) -> dict[str, Any]:
        self._ensure_storage()
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != ACTION_STATE_SCHEMA_VERSION:
            raise ActionValidationError("unsupported action state schema")
        if not isinstance(payload.get("overrides"), dict):
            raise ActionValidationError("action state overrides must be an object")
        return payload

    def _write_state(self, payload: dict[str, Any]) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temp.replace(self.state_path)

    def _read_log(self) -> list[dict[str, Any]]:
        self._ensure_storage()
        rows: list[dict[str, Any]] = []
        previous_hash: str | None = None
        for line_number, raw in enumerate(
            self.log_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if row.get("schema_version") != ACTION_LOG_SCHEMA_VERSION:
                raise ActionValidationError(
                    f"unsupported action log schema at line {line_number}"
                )
            if row.get("previous_hash") != previous_hash:
                raise ActionValidationError(
                    f"action log hash chain broken at line {line_number}"
                )
            actual_hash = self._record_hash(row)
            if not hmac.compare_digest(
                str(row.get("record_hash") or ""),
                actual_hash,
            ):
                raise ActionValidationError(
                    f"action log record hash mismatch at line {line_number}"
                )
            rows.append(row)
            previous_hash = actual_hash
        return rows

    def _append_log(self, record: dict[str, Any]) -> dict[str, Any]:
        rows = self._read_log()
        record = dict(record)
        record["schema_version"] = ACTION_LOG_SCHEMA_VERSION
        record["previous_hash"] = (
            rows[-1]["record_hash"] if rows else None
        )
        record["record_hash"] = self._record_hash(record)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(self._canonical(record) + "\n")
        return record

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise ActionConflictError(
                "another ontology action is already in progress"
            ) from exc
        try:
            os.close(descriptor)
            yield
        finally:
            self.lock_path.unlink(missing_ok=True)

    def status(self) -> dict[str, Any]:
        configured = os.getenv("ONTOLOGY_ACTIONS_ENABLED") == "1"
        actor = os.getenv("ONTOLOGY_ACTION_ACTOR", "").strip()
        role = os.getenv("ONTOLOGY_ACTION_ROLE", "").strip()
        token_configured = bool(os.getenv("ONTOLOGY_ACTION_TOKEN"))
        state = self._read_state()
        log = self._read_log()
        return {
            "schema_version": "ontology-action-status.v1",
            "enabled": configured and bool(actor) and role == "operator",
            "configured": configured,
            "actor": actor or None,
            "role": role or None,
            "token_configured": token_configured,
            "write_mode": "overlay_only",
            "global_version": state["global_version"],
            "override_count": len(state["overrides"]),
            "action_count": len(log),
            "last_record_hash": log[-1]["record_hash"] if log else None,
        }

    def _authorize(self, authorization_token: str | None) -> tuple[str, str]:
        if os.getenv("ONTOLOGY_ACTIONS_ENABLED") != "1":
            raise ActionAuthorizationError(
                "ontology actions are disabled; set ONTOLOGY_ACTIONS_ENABLED=1"
            )
        actor = os.getenv("ONTOLOGY_ACTION_ACTOR", "").strip()
        role = os.getenv("ONTOLOGY_ACTION_ROLE", "").strip()
        if not actor:
            raise ActionAuthorizationError(
                "ONTOLOGY_ACTION_ACTOR is required"
            )
        if role != "operator":
            raise ActionAuthorizationError(
                "ONTOLOGY_ACTION_ROLE must be operator"
            )

        expected = os.getenv("ONTOLOGY_ACTION_TOKEN", "")
        if authorization_token is not None:
            if not expected:
                raise ActionAuthorizationError(
                    "ONTOLOGY_ACTION_TOKEN is not configured"
                )
            if not hmac.compare_digest(
                authorization_token,
                expected,
            ):
                raise ActionAuthorizationError("invalid action token")
        return actor, role

    def _action_contract(self, action_type: str) -> dict[str, Any]:
        definition = self.ontology.definition()
        for action in definition["action_types"]:
            if action["api_name"] == action_type:
                if not action.get("executable"):
                    raise ActionValidationError(
                        f"action {action_type} is not executable"
                    )
                return action
        raise ActionValidationError(f"unknown action type: {action_type}")

    @staticmethod
    def _validate_parameter_type(
        name: str,
        value: Any,
        type_name: str,
    ) -> None:
        valid = True
        if type_name == "string":
            valid = isinstance(value, str)
        elif type_name == "boolean":
            valid = isinstance(value, bool)
        elif type_name == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif type_name == "number":
            valid = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
            )
        elif type_name in {"date", "datetime"}:
            valid = isinstance(value, str)
        if not valid:
            raise ActionValidationError(
                f"parameter {name} must be {type_name}"
            )

    def _validate_parameters(
        self,
        contract: dict[str, Any],
        parameters: dict[str, Any],
    ) -> None:
        declared = {
            row["api_name"]: row
            for row in contract.get("parameters", [])
        }
        unknown = set(parameters) - set(declared)
        if unknown:
            raise ActionValidationError(
                f"unknown action parameters: {sorted(unknown)}"
            )
        for name, spec in declared.items():
            if spec.get("required") and name not in parameters:
                raise ActionValidationError(
                    f"missing required action parameter: {name}"
                )
            if name in parameters:
                self._validate_parameter_type(
                    name,
                    parameters[name],
                    spec["type"],
                )

    def _request_fingerprint(
        self,
        *,
        action_type: str,
        object_type: str,
        primary_key: str,
        parameters: dict[str, Any],
    ) -> str:
        return hashlib.sha256(
            self._canonical(
                {
                    "action_type": action_type,
                    "object_type": object_type,
                    "primary_key": primary_key,
                    "parameters": parameters,
                }
            ).encode("utf-8")
        ).hexdigest()

    def execute(
        self,
        *,
        action_type: str,
        object_type: str,
        primary_key: str,
        parameters: dict[str, Any],
        idempotency_key: str,
        expected_version: int | None = None,
        dry_run: bool = False,
        authorization_token: str | None = None,
    ) -> dict[str, Any]:
        actor, role = self._authorize(authorization_token)
        if not idempotency_key.strip():
            raise ActionValidationError("idempotency_key is required")
        contract = self._action_contract(action_type)
        required_role = str(contract.get("required_role") or "")
        if required_role and role != required_role:
            raise ActionAuthorizationError(
                f"action {action_type} requires role {required_role}"
            )
        if contract["target_object_type"] != object_type:
            raise ActionValidationError(
                f"action {action_type} targets "
                f"{contract['target_object_type']}, not {object_type}"
            )
        self._validate_parameters(contract, parameters)

        target = self.ontology.get_object(
            object_type=object_type,
            primary_key=primary_key,
        )
        if target["record"] is None:
            raise ActionValidationError(
                f"target object does not exist: {object_type}/{primary_key}"
            )

        if action_type == "supersedeObservation":
            replacement_id = str(
                parameters["replacement_observation_id"]
            )
            if replacement_id == primary_key:
                raise ActionValidationError(
                    "replacement observation must differ from target"
                )
            replacement = self.ontology.get_object(
                object_type="Observation",
                primary_key=replacement_id,
            )
            if replacement["record"] is None:
                raise ActionValidationError(
                    f"replacement observation does not exist: {replacement_id}"
                )

        fingerprint = self._request_fingerprint(
            action_type=action_type,
            object_type=object_type,
            primary_key=primary_key,
            parameters=parameters,
        )

        with self._lock():
            rows = self._read_log()
            for row in rows:
                if (
                    row.get("idempotency_key") == idempotency_key
                    and row.get("actor") == actor
                    and row.get("record_type") == "action"
                ):
                    if row.get("request_fingerprint") != fingerprint:
                        raise ActionConflictError(
                            "idempotency key was already used for a different request"
                        )
                    return {
                        "schema_version": "ontology-action-result.v1",
                        "status": "IDEMPOTENT_REPLAY",
                        "action": row,
                    }

            state = self._read_state()
            key = self._target_key(object_type, primary_key)
            current = state["overrides"].get(key)
            current_version = int(
                current.get("version", 0) if current else 0
            )
            if (
                expected_version is not None
                and expected_version != current_version
            ):
                raise ActionConflictError(
                    f"expected_version={expected_version}, "
                    f"current_version={current_version}"
                )

            before_properties = dict(
                current.get("properties", {}) if current else {}
            )
            after_properties = dict(before_properties)
            for mutation in contract.get("mutations", []):
                operation = mutation["operation"]
                if operation == "set":
                    value = mutation.get("value")
                elif operation == "set_from_parameter":
                    value = parameters[mutation["parameter"]]
                else:
                    raise ActionValidationError(
                        f"unsupported mutation operation: {operation}"
                    )
                after_properties[mutation["property"]] = value

            new_version = current_version + 1
            action_id = "action:" + hashlib.sha256(
                f"{actor}|{idempotency_key}|{fingerprint}".encode("utf-8")
            ).hexdigest()[:24]
            record = {
                "record_type": "action",
                "action_id": action_id,
                "action_type": action_type,
                "actor": actor,
                "role": role,
                "executed_at": self._now(),
                "idempotency_key": idempotency_key,
                "request_fingerprint": fingerprint,
                "target": {
                    "object_type": object_type,
                    "primary_key": primary_key,
                },
                "parameters": parameters,
                "prior_version": current_version,
                "new_version": new_version,
                "before": before_properties,
                "after": after_properties,
                "dry_run": dry_run,
            }

            if dry_run:
                return {
                    "schema_version": "ontology-action-result.v1",
                    "status": "DRY_RUN",
                    "action": record,
                }

            state["overrides"][key] = {
                "version": new_version,
                "properties": after_properties,
                "updated_at": record["executed_at"],
                "last_action_id": action_id,
            }
            state["global_version"] = int(state["global_version"]) + 1
            self._write_state(state)
            logged = self._append_log(record)

            return {
                "schema_version": "ontology-action-result.v1",
                "status": "EXECUTED",
                "action": logged,
            }

    def rollback(
        self,
        *,
        action_id: str,
        idempotency_key: str,
        expected_version: int | None = None,
        authorization_token: str | None = None,
    ) -> dict[str, Any]:
        actor, role = self._authorize(authorization_token)
        if not idempotency_key.strip():
            raise ActionValidationError("idempotency_key is required")

        with self._lock():
            rows = self._read_log()
            original = next(
                (
                    row
                    for row in rows
                    if row.get("action_id") == action_id
                    and row.get("record_type") == "action"
                ),
                None,
            )
            if original is None:
                raise ActionValidationError(
                    f"action not found: {action_id}"
                )

            for row in rows:
                if (
                    row.get("idempotency_key") == idempotency_key
                    and row.get("actor") == actor
                    and row.get("record_type") == "rollback"
                ):
                    if row.get("rollback_of") != action_id:
                        raise ActionConflictError(
                            "idempotency key was already used for a different rollback"
                        )
                    return {
                        "schema_version": "ontology-action-result.v1",
                        "status": "IDEMPOTENT_REPLAY",
                        "action": row,
                    }

            target = original["target"]
            key = self._target_key(
                target["object_type"],
                target["primary_key"],
            )
            state = self._read_state()
            current = state["overrides"].get(key)
            current_version = int(
                current.get("version", 0) if current else 0
            )
            required_version = int(original["new_version"])
            if current_version != required_version:
                raise ActionConflictError(
                    "cannot rollback because target has changed since the action"
                )
            if (
                expected_version is not None
                and expected_version != current_version
            ):
                raise ActionConflictError(
                    f"expected_version={expected_version}, "
                    f"current_version={current_version}"
                )

            rollback_id = "rollback:" + hashlib.sha256(
                f"{actor}|{idempotency_key}|{action_id}".encode("utf-8")
            ).hexdigest()[:24]
            before = dict(current.get("properties", {}) if current else {})
            restored = dict(original.get("before") or {})
            new_version = current_version + 1
            timestamp = self._now()

            if restored:
                state["overrides"][key] = {
                    "version": new_version,
                    "properties": restored,
                    "updated_at": timestamp,
                    "last_action_id": rollback_id,
                }
            else:
                state["overrides"].pop(key, None)
            state["global_version"] = int(state["global_version"]) + 1
            self._write_state(state)

            record = self._append_log(
                {
                    "record_type": "rollback",
                    "action_id": rollback_id,
                    "rollback_of": action_id,
                    "actor": actor,
                    "role": role,
                    "executed_at": timestamp,
                    "idempotency_key": idempotency_key,
                    "target": target,
                    "prior_version": current_version,
                    "new_version": new_version,
                    "before": before,
                    "after": restored,
                }
            )
            return {
                "schema_version": "ontology-action-result.v1",
                "status": "ROLLED_BACK",
                "action": record,
            }

    def log(
        self,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        rows = self._read_log()
        selected = rows[-limit:]
        return {
            "schema_version": ACTION_LOG_SCHEMA_VERSION,
            "count": len(selected),
            "records": selected,
        }
