from __future__ import annotations

import argparse
import json
from typing import Any

from src.data_platform import DataPlatformService

_service = DataPlatformService()


def execute(operation: str, argument: str = "") -> dict[str, Any]:
    if operation == "search_companies":
        return _service.search_companies(argument)
    if operation == "get_company_earnings":
        return _service.get_company_earnings(argument)
    if operation == "get_earnings_history":
        return _service.get_earnings_history(argument)
    if operation == "get_evidence":
        return _service.get_evidence(argument)
    if operation == "get_lineage":
        return _service.get_lineage()
    if operation == "get_audit_status":
        return _service.get_audit_status()
    if operation == "get_publication_snapshot":
        return _service.get_publication_snapshot()
    if operation == "get_data_quality":
        return _service.get_data_quality()
    raise ValueError(f"unknown operation: {operation}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only canonical Data Platform Standard v1 CLI")
    parser.add_argument(
        "operation",
        choices=[
            "search_companies",
            "get_company_earnings",
            "get_earnings_history",
            "get_evidence",
            "get_lineage",
            "get_audit_status",
            "get_publication_snapshot",
            "get_data_quality",
        ],
    )
    parser.add_argument("argument", nargs="?", default="")
    args = parser.parse_args()
    print(json.dumps(execute(args.operation, args.argument), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
