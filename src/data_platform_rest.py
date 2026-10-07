from __future__ import annotations

import json
from http import HTTPStatus
from typing import Callable
from urllib.parse import parse_qs, unquote

from src.data_platform import DataPlatformService
from src.ontology_actions import ActionAuthorizationError, ActionConflictError, ActionValidationError

_service = DataPlatformService()


def dispatch_rest(
    path: str,
    query_string: str = "",
    *,
    method: str = "GET",
    body: dict | None = None,
    authorization_token: str | None = None,
) -> dict:
    """Map REST requests to deterministic read or controlled action operations."""
    params = parse_qs(query_string, keep_blank_values=True)
    method = method.upper()
    if method == "POST":
        payload = body or {}
        if path == "/api/data-platform/v1/ontology/actions/execute":
            return _service.execute_ontology_action(
                action_type=str(payload.get("action_type") or ""),
                object_type=str(payload.get("object_type") or ""),
                primary_key=str(payload.get("primary_key") or ""),
                parameters=dict(payload.get("parameters") or {}),
                idempotency_key=str(payload.get("idempotency_key") or ""),
                expected_version=payload.get("expected_version"),
                dry_run=bool(payload.get("dry_run", False)),
                authorization_token=authorization_token,
            )
        if path == "/api/data-platform/v1/ontology/actions/rollback":
            return _service.rollback_ontology_action(
                action_id=str(payload.get("action_id") or ""),
                idempotency_key=str(payload.get("idempotency_key") or ""),
                expected_version=payload.get("expected_version"),
                authorization_token=authorization_token,
            )
        raise KeyError(path)
    if path == "/api/data-platform/v1/companies":
        return _service.search_companies(params.get("q", [""])[0])
    if path.startswith("/api/data-platform/v1/companies/") and path.endswith("/earnings"):
        company_id = path[len("/api/data-platform/v1/companies/") : -len("/earnings")].strip("/")
        return _service.get_company_earnings(company_id)
    if path.startswith("/api/data-platform/v1/companies/") and path.endswith("/history"):
        company_id = path[len("/api/data-platform/v1/companies/") : -len("/history")].strip("/")
        return _service.get_earnings_history(company_id)
    if path == "/api/data-platform/v1/evidence":
        return _service.get_evidence(params.get("event_id", [""])[0])
    if path == "/api/data-platform/v1/lineage":
        return _service.get_lineage()
    if path == "/api/data-platform/v1/audit":
        return _service.get_audit_status()
    if path == "/api/data-platform/v1/publication":
        return _service.get_publication_snapshot()
    if path == "/api/data-platform/v1/quality":
        return _service.get_data_quality()
    if path == "/api/data-platform/v1/ontology":
        return _service.get_ontology_definition()
    if path == "/api/data-platform/v1/ontology/snapshot":
        return _service.get_ontology_snapshot()
    if path == "/api/data-platform/v1/ontology/actions/status":
        return _service.get_ontology_action_status()
    if path == "/api/data-platform/v1/ontology/actions/log":
        return _service.get_ontology_action_log(
            int(params.get("limit", ["100"])[0])
        )
    if path == "/api/data-platform/v1/ontology/objects":
        return _service.search_ontology_objects(
            params.get("type", [""])[0],
            params.get("q", [""])[0],
            int(params.get("limit", ["50"])[0]),
        )
    prefix = "/api/data-platform/v1/ontology/objects/"
    if path.startswith(prefix):
        remainder = path[len(prefix):].strip("/")
        parts = [unquote(part) for part in remainder.split("/") if part]
        if len(parts) == 3 and parts[2] == "neighbors":
            return _service.get_ontology_neighbors(
                parts[0],
                parts[1],
                params.get("link_type", [""])[0],
            )
        if len(parts) == 2:
            return _service.get_ontology_object(parts[0], parts[1])
    raise KeyError(path)


def application(environ: dict, start_response: Callable) -> list[bytes]:
    """WSGI adapter for deterministic reads and controlled ontology actions."""
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if method not in {"GET", "POST"}:
        payload = {"error": "METHOD_NOT_ALLOWED", "allowed": ["GET", "POST"]}
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        start_response(
            f"{HTTPStatus.METHOD_NOT_ALLOWED.value} {HTTPStatus.METHOD_NOT_ALLOWED.phrase}",
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
                ("Allow", "GET, POST"),
            ],
        )
        return [body]

    request_body: dict | None = None
    authorization_token: str | None = None
    if method == "POST":
        try:
            content_length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            content_length = 0
        if content_length < 0 or content_length > 64 * 1024:
            payload = {"error": "REQUEST_TOO_LARGE"}
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            start_response(
                f"{HTTPStatus.REQUEST_ENTITY_TOO_LARGE.value} {HTTPStatus.REQUEST_ENTITY_TOO_LARGE.phrase}",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]
        raw = environ["wsgi.input"].read(content_length) if content_length else b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("body must be an object")
            request_body = parsed
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            payload = {"error": "INVALID_JSON"}
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            start_response(
                f"{HTTPStatus.BAD_REQUEST.value} {HTTPStatus.BAD_REQUEST.phrase}",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]

        authorization = str(environ.get("HTTP_AUTHORIZATION") or "")
        if authorization.startswith("Bearer "):
            authorization_token = authorization[len("Bearer "):]
        else:
            authorization_token = ""

    try:
        payload = dispatch_rest(
            str(environ.get("PATH_INFO") or ""),
            str(environ.get("QUERY_STRING") or ""),
            method=method,
            body=request_body,
            authorization_token=authorization_token,
        )
        status = HTTPStatus.OK
    except ActionAuthorizationError as exc:
        payload = {"error": "FORBIDDEN", "detail": str(exc)}
        status = HTTPStatus.FORBIDDEN
    except ActionConflictError as exc:
        payload = {"error": "CONFLICT", "detail": str(exc)}
        status = HTTPStatus.CONFLICT
    except ActionValidationError as exc:
        payload = {"error": "INVALID_ACTION", "detail": str(exc)}
        status = HTTPStatus.BAD_REQUEST
    except ValueError as exc:
        payload = {"error": "BAD_REQUEST", "detail": str(exc)}
        status = HTTPStatus.BAD_REQUEST
    except KeyError:
        payload = {"error": "NOT_FOUND"}
        status = HTTPStatus.NOT_FOUND

    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    start_response(
        f"{status.value} {status.phrase}",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    with make_server("127.0.0.1", 8080, application) as server:
        server.serve_forever()
