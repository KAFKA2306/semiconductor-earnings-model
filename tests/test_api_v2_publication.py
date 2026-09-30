import json
from pathlib import Path

from semicon.build_api_v2 import build


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_gold_api_excludes_unverified_rows_but_silver_keeps_them(tmp_path: Path) -> None:
    verified = {"project_id": "verified", "quality_flag": "primary_source_extracted"}
    unverified = {"project_id": "research", "quality_flag": "imported_unverified"}
    _write_jsonl(tmp_path / "data/canonical/capex_projects.jsonl", [verified, unverified])
    _write_jsonl(tmp_path / "data/canonical/events.jsonl", [
        {"event_id": "verified", "quality_flag": "primary_source_extracted"},
        {"event_id": "research", "quality_flag": "imported_unverified"},
    ])

    build(tmp_path)

    silver = json.loads((tmp_path / "site/public/api/v2/projects/index.json").read_text())
    gold = json.loads((tmp_path / "site/public/api/v2/gold/projects/index.json").read_text())
    assert {row["project_id"] for row in silver["projects"]} == {"verified", "research"}
    assert [row["project_id"] for row in gold["projects"]] == ["verified"]
    assert silver["publication_tier"] == "silver"
    assert gold["publication_tier"] == "gold"


def test_gold_api_fails_closed_for_missing_or_unknown_quality(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "data/canonical/capex_projects.jsonl", [
        {"project_id": "missing"},
        {"project_id": "unknown", "quality_flag": "future_value"},
    ])
    _write_jsonl(tmp_path / "data/canonical/events.jsonl", [])

    build(tmp_path)

    gold = json.loads((tmp_path / "site/public/api/v2/gold/projects/index.json").read_text())
    assert gold["projects"] == []
