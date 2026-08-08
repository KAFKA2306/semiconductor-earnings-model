from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "earnings_ledger" / "source_registry.json"


def test_storage_infrastructure_sec_sources_are_enabled_with_verified_ciks():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in registry["sources"]}

    expected = {
        "western-digital": {"ticker": "WDC", "cik": 106040},
        "seagate": {"ticker": "STX", "cik": 1137789},
    }

    for source_id, contract in expected.items():
        source = sources[source_id]
        assert source["adapter"] == "sec_edgar"
        assert source["enabled"] is True
        assert source["ticker"] == contract["ticker"]
        assert source["cik"] == contract["cik"]
        assert source["official_source"] == (
            f"https://www.sec.gov/edgar/browse/?CIK={contract['cik']}"
        )
