from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "extract_verified_sec_revenue.py"
SPEC = importlib.util.spec_from_file_location("extract_verified_sec_revenue_bulk_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def payload(cik: int, accession: str) -> dict[str, object]:
    return {
        "cik": cik,
        "entityName": "Issuer",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2026-01-01",
                                "end": "2026-03-31",
                                "val": 100,
                                "accn": accession,
                                "fy": 2026,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2026-04-20",
                            }
                        ]
                    }
                }
            }
        },
    }


def test_load_companyfacts_prefers_materialized_bulk_without_api_key_or_request(tmp_path: Path) -> None:
    cik = 123
    accession = "0000000123-26-000001"
    bulk_dir = tmp_path / "selected"
    bulk_dir.mkdir()
    (bulk_dir / f"CIK{cik:010d}.json").write_text(json.dumps(payload(cik, accession)), encoding="utf-8")

    result = module.load_companyfacts(cik, "", required_accessions={accession}, bulk_dir=bulk_dir)

    assert result["_canonical_source"]["kind"] == "bulk"
    assert result["_canonical_source"]["source_url"] == module.SEC_COMPANYFACTS_BULK_URL


def test_load_companyfacts_uses_api_only_when_bulk_lacks_required_accession(tmp_path: Path, monkeypatch) -> None:
    cik = 123
    old_accession = "0000000123-26-000001"
    new_accession = "0000000123-26-000002"
    bulk_dir = tmp_path / "selected"
    bulk_dir.mkdir()
    (bulk_dir / f"CIK{cik:010d}.json").write_text(json.dumps(payload(cik, old_accession)), encoding="utf-8")
    calls: list[str] = []

    def fake_request(url: str, user_agent: str, retries: int = 3, timeout: int = 30):
        calls.append(url)
        assert user_agent == "contact@example.com"
        return payload(cik, new_accession)

    monkeypatch.setattr(module, "request_json", fake_request)
    result = module.load_companyfacts(
        cik,
        "contact@example.com",
        required_accessions={new_accession},
        bulk_dir=bulk_dir,
    )

    assert calls == [module.SEC_COMPANYFACTS_URL.format(cik=cik)]
    assert result["_canonical_source"]["kind"] == "api_freshness_delta"


def test_revenue_metric_records_bulk_provenance() -> None:
    cik = 123
    accession = "0000000123-26-000001"
    companyfacts = payload(cik, accession)
    companyfacts["_canonical_source"] = {
        "kind": "bulk",
        "source": "SEC Company Facts bulk ZIP",
        "source_url": module.SEC_COMPANYFACTS_BULK_URL,
    }
    event = {
        "event_id": "e1",
        "company_id": "issuer",
        "ticker": "TEST",
        "cik": cik,
        "accession_number": accession,
        "report_date": "2026-03-31",
        "document_type": "10-Q",
    }

    metric, issues = module.extract_event_revenue(event, companyfacts)

    assert issues == []
    assert metric is not None
    assert metric["source_kind"] == "bulk"
    assert metric["source_url"] == module.SEC_COMPANYFACTS_BULK_URL
