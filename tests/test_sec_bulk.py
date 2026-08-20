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


def write_registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {"id": "alpha", "adapter": "sec_edgar", "enabled": True, "cik": 123},
                    {"id": "beta", "adapter": "sec_edgar", "enabled": True, "cik": 456},
                    {"id": "disabled", "adapter": "sec_edgar", "enabled": False, "cik": 789},
                    {"id": "other", "adapter": "tdnet_public", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )


def write_zip(path: Path, ciks: list[int]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for cik in ciks:
            archive.writestr(
                f"CIK{cik:010d}.json",
                json.dumps({"cik": cik, "entityName": f"Issuer {cik}"}),
            )


def test_extracts_only_enabled_registry_ciks(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    archive = tmp_path / "companyfacts.zip"
    output = tmp_path / "selected"
    write_registry(registry)
    write_zip(archive, [123, 456, 999])

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
    write_zip(archive, [123])

    with pytest.raises(ValueError, match="missing configured CIK"):
        sec_bulk.extract_selected(archive, tmp_path / "selected", sec_bulk.sec_ciks(registry))


def test_download_rejects_blank_user_agent(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="declared User-Agent"):
        sec_bulk.download(
            sec_bulk.ARCHIVES["companyfacts"], tmp_path / "companyfacts.zip", ""
        )
