from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
OUT_PATH = LEDGER_DIR / "lineage_latest.json"

CORE_ARTIFACTS = (
    "events.ndjson",
    "rejected.ndjson",
    "source_registry.json",
    "state.json",
    "audit_latest.json",
    "publication_latest.json",
    "source_state.json",
)

DERIVED_AUDIT_ARTIFACTS = (
    "semantic_duplicate_audit_latest.json",
    "period_normalization_latest.json",
    "accounting_basis_audit_latest.json",
    "rejection_reason_audit_latest.json",
    "published_at_audit_latest.json",
    "source_registry_audit_latest.json",
    "consensus_separation_audit_latest.json",
)

LINEAGE_ARTIFACTS = CORE_ARTIFACTS + DERIVED_AUDIT_ARTIFACTS


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid required JSON artifact: {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"required JSON artifact is not an object: {path.name}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_clean_audit(name: str, value: dict) -> None:
    if value.get("status") != "PASS":
        raise RuntimeError(f"derived audit is not PASS: {name}")
    if value.get("issues") != []:
        raise RuntimeError(f"derived audit has issues: {name}")


def build_manifest(ledger_dir: Path = LEDGER_DIR) -> dict:
    missing = [name for name in LINEAGE_ARTIFACTS if not (ledger_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"missing required lineage artifacts: {', '.join(missing)}")

    state = read_json(ledger_dir / "state.json")
    audit = read_json(ledger_dir / "audit_latest.json")
    publication = read_json(ledger_dir / "publication_latest.json")
    source_state = read_json(ledger_dir / "source_state.json")

    run_at = state.get("last_run_at")
    if not isinstance(run_at, str) or not run_at:
        raise RuntimeError("state.last_run_at is required")
    if state.get("audit_status") != "PASS":
        raise RuntimeError("state audit_status is not PASS")
    if audit.get("status") != "PASS" or audit.get("issues") != []:
        raise RuntimeError("ledger audit is not a clean PASS")

    bindings = {
        "audit_latest.json": audit.get("run_at"),
        "publication_latest.json": publication.get("generated_from_run_at"),
        "source_state.json": source_state.get("generated_from_run_at"),
    }
    mismatched = {name: value for name, value in bindings.items() if value != run_at}
    if mismatched:
        raise RuntimeError(f"run binding mismatch: expected {run_at}, got {mismatched}")
    if publication.get("audit_status") != "PASS":
        raise RuntimeError("publication audit_status is not PASS")

    for name in DERIVED_AUDIT_ARTIFACTS:
        require_clean_audit(name, read_json(ledger_dir / name))

    artifacts = []
    for name in LINEAGE_ARTIFACTS:
        path = ledger_dir / name
        artifacts.append(
            {
                "path": f"data/earnings_ledger/{name}",
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )

    return {
        "schema_version": "earnings-ledger-lineage.v2",
        "generated_from_run_at": run_at,
        "status": "PASS",
        "artifacts": artifacts,
        "contract": {
            "sha256_bound": True,
            "single_run_binding_required": True,
            "ledger_audit_pass_required": True,
            "publication_audit_pass_required": True,
            "derived_audit_clean_pass_required": True,
            "fail_closed": True,
        },
    }


def main() -> int:
    manifest = build_manifest()
    OUT_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "artifacts": len(manifest["artifacts"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
