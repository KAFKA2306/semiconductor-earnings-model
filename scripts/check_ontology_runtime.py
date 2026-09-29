from __future__ import annotations

import json
from pathlib import Path

from src.ontology_runtime import OntologyRuntime

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    runtime = OntologyRuntime(ROOT)
    definition = runtime.describe()
    snapshot = runtime.build_snapshot()

    print(
        json.dumps(
            {
                "status": "PASS",
                "ontology_id": definition["ontology_id"],
                "object_types": definition["counts"]["object_types"],
                "link_types": definition["counts"]["link_types"],
                "action_types": definition["counts"]["action_types"],
                "interfaces": definition["counts"]["interfaces"],
                "object_type_counts": snapshot["object_type_counts"],
                "link_type_counts": snapshot["link_type_counts"],
                "definition_hash": snapshot["definition_hash"],
                "input_hashes": snapshot["input_hashes"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
