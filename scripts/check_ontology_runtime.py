from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ontology_runtime import OntologyRuntime


def main() -> None:
    runtime = OntologyRuntime(ROOT)
    definition = runtime.describe()
    snapshot = runtime.build_snapshot()
    assert snapshot["schema_version"] == "kafka-ontology-snapshot.v0.3"
    assert snapshot["action_state_version"] >= 0
    assert snapshot["object_type_counts"].get("Observation", 0) > 0
    assert snapshot["object_type_counts"].get("Source", 0) > 0
    assert snapshot["object_type_counts"].get("Document", 0) > 0
    assert snapshot["link_type_counts"].get("observationSource", 0) == snapshot["object_type_counts"]["Observation"]

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
