from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "data/financial_db/nand_kpi_sources.json"


def test_nand_source_registry_preserves_value_and_period_evidence() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    micron = next(source for source in registry["sources"] if source["entity_id"] == "micron")
    assert len(micron["documents"]) >= 4
    for document in micron["documents"]:
        assert document["source_url"].startswith("https://investors.micron.com/")
        assert document["period_source_url"].startswith("https://investors.micron.com/")
        assert document["period_end"]
        assert document["fiscal_period"] in {"Q1", "Q2", "Q3", "Q4"}


def test_all_discovery_and_document_urls_stay_on_allowlisted_official_domains() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for source in registry["sources"]:
        domains = set(source["official_domains"])
        urls = list(source.get("discovery_urls", []))
        for document in source.get("documents", []):
            urls.extend([document["source_url"], document.get("period_source_url")])
        for url in filter(None, urls):
            host = (urlparse(url).hostname or "").lower()
            assert any(host == domain or host.endswith("." + domain) for domain in domains), (source["entity_id"], url)
