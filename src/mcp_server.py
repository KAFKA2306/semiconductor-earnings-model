from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from src.data_platform import DataPlatformService

PROTOCOL_VERSION = "2026-07-28"
MAX_REQUEST_BODY_SIZE = 64 * 1024

_service = DataPlatformService()
mcp = MCPServer(
    "semiconductor-earnings-data-platform",
    version="1.0.0",
    description="Read-only deterministic projections of the canonical earnings ledger.",
)


@mcp.tool()
def search_companies(query: str = "") -> dict[str, Any]:
    """Search canonical company identities by company id, name, or ticker."""
    return _service.search_companies(query)


@mcp.tool()
def get_company_earnings(company_id: str) -> dict[str, Any]:
    """Return the latest canonical earnings event for one company."""
    return _service.get_company_earnings(company_id)


@mcp.tool()
def get_earnings_history(company_id: str) -> dict[str, Any]:
    """Return the canonical earnings event history for one company."""
    return _service.get_earnings_history(company_id)


@mcp.tool()
def get_evidence(event_id: str = "") -> dict[str, Any]:
    """Return event evidence and the latest evidence audit."""
    return _service.get_evidence(event_id)


@mcp.tool()
def get_lineage() -> dict[str, Any]:
    """Return the SHA-256-bound canonical lineage manifest."""
    return _service.get_lineage()


@mcp.tool()
def get_audit_status() -> dict[str, Any]:
    """Return all canonical ledger audit artifacts and aggregate status."""
    return _service.get_audit_status()


@mcp.tool()
def get_publication_snapshot() -> dict[str, Any]:
    """Return the latest fail-closed publication snapshot."""
    return _service.get_publication_snapshot()


@mcp.tool()
def get_data_quality() -> dict[str, Any]:
    """Return deterministic audit, publication, and lineage quality status."""
    return _service.get_data_quality()


def _csv_env(name: str, default: tuple[str, ...]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise RuntimeError(f"{name} must not be empty when set")
    return values


def transport_security() -> TransportSecuritySettings:
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_csv_env(
            "MCP_ALLOWED_HOSTS",
            ("127.0.0.1:*", "localhost:*"),
        ),
        allowed_origins=_csv_env(
            "MCP_ALLOWED_ORIGINS",
            ("http://127.0.0.1:*", "http://localhost:*"),
        ),
    )


def build_http_app():
    """Build the official stateless Streamable HTTP application at /mcp."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=MAX_REQUEST_BODY_SIZE,
        transport_security=transport_security(),
        host="127.0.0.1",
    )


app = build_http_app()


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8000,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=MAX_REQUEST_BODY_SIZE,
        transport_security=transport_security(),
    )
