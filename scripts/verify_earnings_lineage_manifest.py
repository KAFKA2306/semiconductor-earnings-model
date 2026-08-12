from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def verify_manifest(root: Path, manifest_path: Path) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    if root != manifest_path and root not in manifest_path.parents:
        raise RuntimeError("manifest path escapes repository root")
    if not manifest_path.is_file():
        raise RuntimeError(f"lineage manifest missing: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS":
        raise RuntimeError("lineage manifest status is not PASS")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RuntimeError("lineage manifest artifacts must be a non-empty list")

    seen: set[str] = set()
    verified: list[dict[str, object]] = []
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict):
            raise RuntimeError(f"artifact entry {index} is not an object")
        relative = str(item.get("path") or "").strip().replace("\\", "/")
        expected_hash = str(item.get("sha256") or "").strip().lower()
        expected_size = item.get("size_bytes")
        if not relative:
            raise RuntimeError(f"artifact entry {index} missing path")
        if relative in seen:
            raise RuntimeError(f"duplicate lineage artifact path: {relative}")
        seen.add(relative)
        if not SHA256_RE.fullmatch(expected_hash):
            raise RuntimeError(f"invalid SHA-256 for {relative}")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise RuntimeError(f"invalid size_bytes for {relative}")

        artifact_path = (root / relative).resolve()
        if root != artifact_path and root not in artifact_path.parents:
            raise RuntimeError(f"artifact path escapes repository root: {relative}")
        if artifact_path == manifest_path:
            raise RuntimeError("lineage manifest must not bind itself")
        if not artifact_path.is_file():
            raise RuntimeError(f"lineage artifact missing: {relative}")

        payload = artifact_path.read_bytes()
        actual_hash = hashlib.sha256(payload).hexdigest()
        actual_size = len(payload)
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"lineage SHA-256 mismatch for {relative}: expected {expected_hash}, got {actual_hash}"
            )
        if actual_size != expected_size:
            raise RuntimeError(
                f"lineage size mismatch for {relative}: expected {expected_size}, got {actual_size}"
            )
        verified.append({"path": relative, "sha256": actual_hash, "size_bytes": actual_size})

    return {
        "schema_version": manifest.get("schema_version"),
        "generated_from_run_at": manifest.get("generated_from_run_at"),
        "status": "PASS",
        "verified_artifact_count": len(verified),
        "artifacts": verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify every artifact bound by earnings lineage_latest.json")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/earnings_ledger/lineage_latest.json"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
    result = verify_manifest(root, manifest)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
