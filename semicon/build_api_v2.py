from __future__ import annotations

import argparse
from pathlib import Path

from semicon.ledger import load_json, load_jsonl, write_json

ROOT = Path(__file__).resolve().parents[1]
GOLD_QUALITY = "primary_source_extracted"


def _gold(rows: list[dict]) -> list[dict]:
    """Fail closed: only source-verified canonical rows are publishable Gold."""
    return [row for row in rows if row.get("quality_flag") == GOLD_QUALITY]


def build(root: Path = ROOT) -> dict[str, int]:
    output = root / "site/public/api/v2"
    events = load_jsonl(root / "data/canonical/events.jsonl")
    projects = load_jsonl(root / "data/canonical/capex_projects.jsonl")
    # API v2 remains the research/Silver surface so imported rows stay queryable.
    datasets = {
        "entities/index.json": load_json(root / "data/registry/entities.json", {"entities": []}),
        "facts/index.json": {"schema_version": "canonical-facts.v1", "facts": load_jsonl(root / "data/canonical/facts.jsonl")},
        "events/index.json": {"schema_version": "canonical-events.v1", "publication_tier": "silver", "events": events},
        "capex/index.json": {"schema_version": "canonical-capex-projects.v1", "publication_tier": "silver", "projects": projects},
        "facilities/index.json": {"schema_version": "canonical-facilities.v1", "facilities": load_jsonl(root / "data/canonical/facilities.jsonl")},
        "customer-commitments/index.json": {"schema_version": "canonical-customer-commitments.v1", "commitments": load_jsonl(root / "data/canonical/customer_commitments.jsonl")},
        "orders-backlog/index.json": {"schema_version": "canonical-orders-backlog.v1", "backlog": load_jsonl(root / "data/canonical/orders_backlog.jsonl")},
        "projects/index.json": {
            "schema_version": "semiconductor-project-view.v1",
            "publication_tier": "silver",
            "projects": projects,
            "economics": load_json(root / "data/derived/project_economics.json", {"projects": []}),
            "earnings_inputs": load_json(root / "data/derived/earnings_inputs.json", {"inputs": []}),
        },
        # Gold is a separate fail-closed namespace; absence/unknown quality never publishes.
        "gold/events/index.json": {"schema_version": "canonical-events.v1", "publication_tier": "gold", "events": _gold(events)},
        "gold/capex/index.json": {"schema_version": "canonical-capex-projects.v1", "publication_tier": "gold", "projects": _gold(projects)},
        "gold/projects/index.json": {"schema_version": "semiconductor-project-view.v1", "publication_tier": "gold", "projects": _gold(projects)},
    }
    for rel, payload in datasets.items():
        write_json(output / rel, payload)
    return {
        key: len(value.get(next((k for k in ("entities", "facts", "events", "projects", "facilities", "commitments", "backlog") if k in value), "_"), []))
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
