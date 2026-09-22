from __future__ import annotations

import argparse
from pathlib import Path

from semicon.ledger import load_json, load_jsonl, write_json

ROOT = Path(__file__).resolve().parents[1]


def build(root: Path = ROOT) -> dict[str, int]:
    output = root / "site/public/api/v2"
    datasets = {
        "entities/index.json": load_json(root / "data/registry/entities.json", {"entities": []}),
        "facts/index.json": {"schema_version": "canonical-facts.v1", "facts": load_jsonl(root / "data/canonical/facts.jsonl")},
        "events/index.json": {"schema_version": "canonical-events.v1", "events": load_jsonl(root / "data/canonical/events.jsonl")},
        "capex/index.json": {"schema_version": "canonical-capex-projects.v1", "projects": load_jsonl(root / "data/canonical/capex_projects.jsonl")},
        "facilities/index.json": {"schema_version": "canonical-facilities.v1", "facilities": load_jsonl(root / "data/canonical/facilities.jsonl")},
        "projects/index.json": {
            "schema_version": "semiconductor-project-view.v1",
            "projects": load_jsonl(root / "data/canonical/capex_projects.jsonl"),
            "economics": load_json(root / "data/derived/project_economics.json", {"projects": []}),
            "earnings_inputs": load_json(root / "data/derived/earnings_inputs.json", {"inputs": []}),
        },
    }
    for rel, payload in datasets.items():
        write_json(output / rel, payload)
    return {
        key: len(value.get(next((k for k in ("entities", "facts", "events", "projects", "facilities") if k in value), "_"), []))
        if isinstance(value, dict) else 0
        for key, value in datasets.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(build(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
