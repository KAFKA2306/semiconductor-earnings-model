from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_earnings_lineage_manifest.py"
SPEC = importlib.util.spec_from_file_location("verify_earnings_lineage_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def write_manifest(root: Path, *, payload: bytes = b"canonical\n") -> tuple[Path, Path]:
    artifact = root / "data" / "earnings_ledger" / "events.ndjson"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(payload)
    manifest = artifact.parent / "lineage_latest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "earnings-ledger-lineage.v2",
                "generated_from_run_at": "2026-08-12T00:00:00Z",
                "status": "PASS",
                "artifacts": [
                    {
                        "path": "data/earnings_ledger/events.ndjson",
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "size_bytes": len(payload),
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest, artifact


def test_verifier_accepts_exact_hash_and_size(tmp_path: Path) -> None:
    manifest, _ = write_manifest(tmp_path)
    result = verifier.verify_manifest(tmp_path, manifest)
    assert result["status"] == "PASS"
    assert result["verified_artifact_count"] == 1


def test_verifier_rejects_content_drift(tmp_path: Path) -> None:
    manifest, artifact = write_manifest(tmp_path)
    artifact.write_bytes(b"mutated\n")
    try:
        verifier.verify_manifest(tmp_path, manifest)
    except RuntimeError as exc:
        assert "SHA-256 mismatch" in str(exc)
    else:
        raise AssertionError("content drift must fail closed")


def test_verifier_rejects_duplicate_paths(tmp_path: Path) -> None:
    manifest, _ = write_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["artifacts"].append(dict(payload["artifacts"][0]))
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    try:
        verifier.verify_manifest(tmp_path, manifest)
    except RuntimeError as exc:
        assert "duplicate lineage artifact path" in str(exc)
    else:
        raise AssertionError("duplicate paths must fail closed")


def test_verifier_rejects_path_escape(tmp_path: Path) -> None:
    manifest, _ = write_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["artifacts"][0]["path"] = "../outside.bin"
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    try:
        verifier.verify_manifest(tmp_path, manifest)
    except RuntimeError as exc:
        assert "escapes repository root" in str(exc)
    else:
        raise AssertionError("path escape must fail closed")
