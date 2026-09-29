from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import Client

from src.data_platform import DataPlatformService
from src.data_platform_cli import execute as cli_execute
from src.data_platform_rest import dispatch_rest
from src.mcp_server import PROTOCOL_VERSION, mcp

_service = DataPlatformService()

EXPECTED_TOOLS = {
    "search_companies",
    "get_company_earnings",
    "get_earnings_history",
    "get_evidence",
    "get_lineage",
    "get_audit_status",
    "get_publication_snapshot",
    "get_data_quality",
    "get_ontology_definition",
    "get_ontology_snapshot",
    "search_ontology_objects",
    "get_ontology_object",
    "get_ontology_neighbors",
}


async def check() -> None:
    async with Client(mcp, raise_exceptions=True) as client:
        assert client.protocol_version == PROTOCOL_VERSION
        assert client.server_capabilities.tools is not None

        listing = await client.list_tools()
        names = {tool.name for tool in listing.tools}
        assert names == EXPECTED_TOOLS, (names, EXPECTED_TOOLS)

        companies = await client.call_tool("search_companies", {"query": ""})
        assert companies.is_error is False
        assert companies.structured_content is not None
        assert companies.structured_content["schema_version"] == "data-platform-standard.v1"

        quality = await client.call_tool("get_data_quality", {})
        assert quality.is_error is False
        assert quality.structured_content is not None
        assert quality.structured_content["records"][0]["record"]["fail_closed"] is True
        canonical = _service.get_data_quality()
        assert quality.structured_content == canonical
        assert cli_execute("get_data_quality") == canonical
        assert dispatch_rest("/api/data-platform/v1/quality") == canonical

        ontology = await client.call_tool("get_ontology_snapshot", {})
        assert ontology.is_error is False
        assert ontology.structured_content is not None
        ontology_canonical = _service.get_ontology_snapshot()
        assert ontology.structured_content == ontology_canonical
        assert cli_execute("get_ontology_snapshot") == ontology_canonical
        assert dispatch_rest("/api/data-platform/v1/ontology/snapshot") == ontology_canonical

        search_args = {"object_type": "Issuer", "query": "Micron", "limit": 10}
        ontology_search = await client.call_tool("search_ontology_objects", search_args)
        assert ontology_search.is_error is False
        search_canonical = _service.search_ontology_objects(**search_args)
        assert ontology_search.structured_content == search_canonical
        assert dispatch_rest(
            "/api/data-platform/v1/ontology/objects",
            "type=Issuer&q=Micron&limit=10",
        ) == search_canonical

        observation_id = "micron:2026-05-28:revenue:consolidated:actual"
        neighbors_args = {
            "object_type": "Observation",
            "primary_key": observation_id,
            "link_type": "",
        }
        ontology_neighbors = await client.call_tool(
            "get_ontology_neighbors",
            neighbors_args,
        )
        assert ontology_neighbors.is_error is False
        neighbors_canonical = _service.get_ontology_neighbors(**neighbors_args)
        assert ontology_neighbors.structured_content == neighbors_canonical
        assert {"Issuer", "NormalizedConcept", "Source", "Document"} <= {
            row["object_type"] for row in neighbors_canonical["neighbors"]
        }

        print(
            json.dumps(
                {
                    "status": "PASS",
                    "protocol_version": client.protocol_version,
                    "server": client.server_info.name if client.server_info else None,
                    "tool_count": len(names),
                    "tools": sorted(names),
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(check())
