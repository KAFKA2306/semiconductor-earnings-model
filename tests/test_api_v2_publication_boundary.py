import json
from pathlib import Path

from semicon.build_api_v2 import build


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _fixture(root: Path, rows: list[dict]) -> None:
    (root / "data/registry").mkdir(parents=True)
    (root / "data/registry/entities.json").write_text('{"entities": []}', encoding="utf-8")
    (root / "data/derived").mkdir(parents=True)
    (root / "data/derived/project_economics.json").write_text('{"projects": []}', encoding="utf-8")
    (root / "data/derived/earnings_inputs.json").write_text('{"inputs": []}', encoding="utf-8")
    for name in ("facts.jsonl", "events.jsonl", "capex_projects.jsonl", "facilities.jsonl", "customer_commitments.jsonl", "orders_backlog.jsonl"):
        _jsonl(root / "data/canonical" / name, rows)


def test_research_keeps_unverified_rows_while_gold_fails_closed(tmp_path: Path) -> None:
    verified = {"id": "verified", "quality_flag": "primary_source_extracted"}
    imported = {"id": "imported", "quality_flag": "imported_unverified"}
    missing = {"id": "missing"}
    _fixture(tmp_path, [verified, imported, missing])
    build(tmp_path)
    research = json.loads((tmp_path / "site/public/api/v2/events/index.json").read_text())
    gold = json.loads((tmp_path / "site/public/api/v2/gold/events/index.json").read_text())
    assert research["publication_tier"] == "research"
    assert [row["id"] for row in research["events"]] == ["verified", "imported", "missing"]
    assert gold == {"schema_version": "canonical-events.v1", "publication_tier": "gold", "events": [verified]}


def test_every_gold_row_set_contains_only_verified_primary_sources(tmp_path: Path) -> None:
    _fixture(tmp_path, [{"id": "ok", "quality_flag": "primary_source_extracted"}, {"id": "no", "quality_flag": "imported_unverified"}])
    build(tmp_path)
    paths = list((tmp_path / "site/public/api/v2/gold").glob("*/index.json"))
    assert len(paths) == 6
    for path in paths:
        payload = json.loads(path.read_text())
        rows = next(value for key, value in payload.items() if key not in {"schema_version", "publication_tier"})
        assert rows
        assert all(row["quality_flag"] == "primary_source_extracted" for row in rows)
