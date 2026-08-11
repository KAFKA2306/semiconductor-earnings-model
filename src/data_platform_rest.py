from __future__ import annotations

import json
from http import HTTPStatus
from typing import Callable
from urllib.parse import parse_qs

from src.data_platform import DataPlatformService

_service = DataPlatformService()


def dispatch_rest(path: str, query_string: str = "") -> dict:
    """Map a read-only REST path to the canonical service without recomputation."""
    params = parse_qs(query_string, keep_blank_values=True)
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
    raise KeyError(path)


def application(environ: dict, start_response: Callable) -> list[bytes]:
    """Minimal read-only WSGI Data API adapter."""
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if method != "GET":
        payload = {"error": "METHOD_NOT_ALLOWED", "allowed": ["GET"]}
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        start_response(
            f"{HTTPStatus.METHOD_NOT_ALLOWED.value} {HTTPStatus.METHOD_NOT_ALLOWED.phrase}",
            [("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Allow", "GET")],
        )
        return [body]
    try:
        payload = dispatch_rest(
            str(environ.get("PATH_INFO") or ""),
            str(environ.get("QUERY_STRING") or ""),
        )
        status = HTTPStatus.OK
    except (KeyError, ValueError):
        payload = {"error": "NOT_FOUND"}
        status = HTTPStatus.NOT_FOUND

    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    start_response(
        f"{status.value} {status.phrase}",
        [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))],
    )
    return [body]


if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    with make_server("127.0.0.1", 8080, application) as server:
        server.serve_forever()
