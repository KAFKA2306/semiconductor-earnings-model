from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sec_bulk.py"
SPEC = importlib.util.spec_from_file_location("sec_bulk", MODULE_PATH)
assert SPEC and SPEC.loader
sec_bulk = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sec_bulk
SPEC.loader.exec_module(sec_bulk)


def write_registry(path: Path, ciks: list[int] | None = None) -> None:
    ciks = ciks or [123, 456]
    sources = [
        {"id": f"issuer-{cik}", "adapter": "sec_edgar", "enabled": True, "cik": cik}
        for cik in ciks
    ]
    sources.extend(
        [
            {"id": "disabled", "adapter": "sec_edgar", "enabled": False, "cik": 789},
            {"id": "other", "adapter": "tdnet_public", "enabled": True},
        ]
    )
    path.write_text(json.dumps({"sources": sources}), encoding="utf-8")


def companyfacts_payload(cik: int, value: int = 100) -> dict[str, object]:
    return {
        "cik": cik,
        "entityName": f"Issuer {cik}",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenue",
                    "description": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "start": "2026-01-01",
                                "end": "2026-03-31",
                                "val": value,
                                "accn": f"000000{cik}-26-000001",
                                "fy": 2026,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2026-04-20",
                                "frame": "CY2026Q1",
                            }
                        ]
                    },
                }
            }
        },
    }


def submissions_payload(cik: int) -> dict[str, object]:
    return {
        "cik": cik,
        "name": f"Issuer {cik}",
        "filings": {
            "recent": {
                "accessionNumber": [f"000000{cik}-26-000001"],
                "filingDate": ["2026-04-20"],
                "reportDate": ["2026-03-31"],
                "acceptanceDateTime": ["20260420123456"],
                "act": ["34"],
                "form": ["10-Q"],
                "fileNumber": ["001-00001"],
                "filmNumber": ["261234567"],
                "items": [""],
                "size": [12345],
                "isXBRL": [1],
                "isInlineXBRL": [1],
                "primaryDocument": ["form10q.htm"],
                "primaryDocDescription": ["FORM 10-Q"],
            }
        },
    }


def write_zip(path: Path, payloads: dict[int, dict[str, object]]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for cik, payload in payloads.items():
            archive.writestr(f"CIK{cik:010d}.json", json.dumps(payload))


def test_extracts_only_enabled_registry_ciks(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    archive = tmp_path / "companyfacts.zip"
    output = tmp_path / "selected"
    write_registry(registry)
    write_zip(
        archive,
        {
            123: companyfacts_payload(123),
            456: companyfacts_payload(456),
            999: companyfacts_payload(999),
        },
    )

    wanted = sec_bulk.sec_ciks(registry)
    records = sec_bulk.extract_selected(archive, output, wanted)

    assert set(wanted) == {"CIK0000000123.json", "CIK0000000456.json"}
    assert [record["cik"] for record in records] == [123, 456]
    assert sorted(path.name for path in output.iterdir()) == [
        "CIK0000000123.json",
        "CIK0000000456.json",
    ]


def test_missing_configured_cik_fails_closed(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    archive = tmp_path / "companyfacts.zip"
    write_registry(registry)
    write_zip(archive, {123: companyfacts_payload(123)})

    with pytest.raises(ValueError, match="missing configured CIK"):
        sec_bulk.extract_selected(archive, tmp_path / "selected", sec_bulk.sec_ciks(registry))


def test_download_rejects_blank_user_agent(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="declared User-Agent"):
        sec_bulk.download(sec_bulk.ARCHIVES["companyfacts"], tmp_path / "companyfacts.zip", "")


def test_request_policy_enforces_sec_ten_requests_per_second_limit() -> None:
    clock = [0.0]
    slept: list[float] = []

    def monotonic() -> float:
        return clock[0]

    def sleeper(delay: float) -> None:
        slept.append(delay)
        clock[0] += delay

    policy = sec_bulk.RequestPolicy("example@example.com", monotonic=monotonic, sleeper=sleeper)
    policy.wait()
    clock[0] += 0.02
    policy.wait()

    assert slept == pytest.approx([0.08])
    with pytest.raises(ValueError, match="10 requests/second"):
        sec_bulk.RequestPolicy("example@example.com", min_interval_seconds=0.01)


def test_companyfacts_normalization_preserves_xbrl_provenance() -> None:
    records = sec_bulk.normalize_companyfacts(companyfacts_payload(123), "issuer-123")
    assert len(records) == 1
    record = records[0]
    assert record["schema_version"] == "sec-normalized-record.v1"
    assert record["record_type"] == "company_fact"
    assert record["taxonomy"] == "us-gaap"
    assert record["concept"] == "Revenues"
    assert record["unit"] == "USD"
    assert record["accession_number"] == "000000123-26-000001"
    assert record["start"] == "2026-01-01"
    assert record["end"] == "2026-03-31"
    assert record["filed"] == "2026-04-20"


def test_submissions_normalization_preserves_filing_provenance() -> None:
    records = sec_bulk.normalize_submissions(submissions_payload(123), "issuer-123")
    assert len(records) == 1
    record = records[0]
    assert record["schema_version"] == "sec-normalized-record.v1"
    assert record["record_type"] == "filing"
    assert record["accession_number"] == "000000123-26-000001"
    assert record["form"] == "10-Q"
    assert record["filing_date"] == "2026-04-20"
    assert record["report_date"] == "2026-03-31"
    assert record["primary_document"] == "form10q.htm"


def test_bulk_and_api_payloads_use_identical_record_identity() -> None:
    payload = companyfacts_payload(123)
    bulk = sec_bulk.normalize_companyfacts(payload, "issuer-123")
    api = sec_bulk.normalize_companyfacts(json.loads(json.dumps(payload)), "issuer-123")
    assert bulk == api
    assert bulk[0]["record_id"] == api[0]["record_id"]


def test_merge_dedupes_identical_records_and_never_silently_overwrites_conflicts() -> None:
    base = sec_bulk.normalize_companyfacts(companyfacts_payload(123, value=100), "issuer-123")
    identical = sec_bulk.normalize_companyfacts(companyfacts_payload(123, value=100), "issuer-123")
    merged, audit = sec_bulk.merge_records(base, identical)
    assert merged == base
    assert audit["duplicate_record_count"] == 1
    assert audit["conflict_count"] == 0
    assert audit["status"] == "PASS"

    changed = sec_bulk.normalize_companyfacts(companyfacts_payload(123, value=101), "issuer-123")
    conflicted, conflict_audit = sec_bulk.merge_records(base, changed)
    assert conflicted == base
    assert conflict_audit["conflict_count"] == 1
    assert conflict_audit["status"] == "CONFLICT"
    assert conflicted[0]["value"] == 100


def test_ten_issuer_bulk_subset_normalizes_for_both_archives(tmp_path: Path) -> None:
    ciks = list(range(1001, 1011))
    registry = tmp_path / "registry.json"
    write_registry(registry, ciks)
    wanted = sec_bulk.sec_ciks(registry)

    companyfacts_zip = tmp_path / "companyfacts.zip"
    submissions_zip = tmp_path / "submissions.zip"
    write_zip(companyfacts_zip, {cik: companyfacts_payload(cik) for cik in ciks})
    write_zip(submissions_zip, {cik: submissions_payload(cik) for cik in ciks})

    companyfacts_selected = tmp_path / "companyfacts-selected"
    submissions_selected = tmp_path / "submissions-selected"
    sec_bulk.extract_selected(companyfacts_zip, companyfacts_selected, wanted)
    sec_bulk.extract_selected(submissions_zip, submissions_selected, wanted)

    facts = sec_bulk.normalize_selected("companyfacts", companyfacts_selected, wanted)
    filings = sec_bulk.normalize_selected("submissions", submissions_selected, wanted)

    assert len({record["cik"] for record in facts}) == 10
    assert len({record["cik"] for record in filings}) == 10
    assert {record["schema_version"] for record in facts + filings} == {"sec-normalized-record.v1"}


def test_write_ndjson_is_deterministic(tmp_path: Path) -> None:
    rows = sec_bulk.normalize_companyfacts(companyfacts_payload(123), "issuer-123")
    first = tmp_path / "first.ndjson"
    second = tmp_path / "second.ndjson"
    assert sec_bulk.write_ndjson(first, rows) == sec_bulk.write_ndjson(second, rows)
    assert first.read_bytes() == second.read_bytes()
