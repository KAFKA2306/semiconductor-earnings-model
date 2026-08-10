from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "data_lake_publish.json"
DEFAULT_OUTPUT = ROOT / ".data_lake_bundle"
EDINETDB_PROJECTION_KEYS = {
    "schema_version",
    "consumer",
    "projection_id",
    "provider",
    "attribution",
    "provider_terms",
    "source_endpoint",
    "request_fingerprint",
    "fetched_at",
    "response_sha256",
    "record_count",
    "records",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_inside_repo(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes repository: {path}") from exc
    return resolved


def validate_edinetdb_projection(path: Path) -> None:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"EDINETDB projection must be a JSON object: {path}")
    if payload.get("schema_version") != "edinetdb.consumer-projection.v1":
        raise ValueError(f"unexpected EDINETDB projection schema: {path}")
    if payload.get("provider") != "EDINET DB":
        raise ValueError(f"unexpected EDINETDB projection provider: {path}")
    unknown = set(payload) - EDINETDB_PROJECTION_KEYS
    if unknown:
        raise ValueError(f"unexpected EDINETDB projection top-level fields {sorted(unknown)}: {path}")
    if not isinstance(payload.get("records"), list):
        raise ValueError(f"EDINETDB projection records must be a list: {path}")
    if payload.get("record_count") != len(payload["records"]):
        raise ValueError(f"EDINETDB projection record_count mismatch: {path}")
    fingerprint = str(payload.get("request_fingerprint", ""))
    response_sha = str(payload.get("response_sha256", ""))
    if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
        raise ValueError(f"invalid request fingerprint: {path}")
    if len(response_sha) != 64 or any(ch not in "0123456789abcdef" for ch in response_sha):
        raise ValueError(f"invalid response SHA-256: {path}")


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != "data-lake-publish.v1":
        raise ValueError("unsupported data lake publish schema")
    bucket = config.get("bucket")
    if not isinstance(bucket, str) or bucket.count("/") != 1:
        raise ValueError("bucket must be namespace/name")
    prefix = config.get("destination_prefix")
    if not isinstance(prefix, str) or not prefix.strip("/"):
        raise ValueError("destination_prefix is required")
    policy = config.get("policy", {})
    required_policy = {
        "allow_list_only": True,
        "raw_provider_responses": False,
        "manifest_required": True,
        "sha256_readback_required": True,
        "consumer_repository_authentication": False,
    }
    for key, expected in required_policy.items():
        if policy.get(key) is not expected:
            raise ValueError(f"data lake policy {key} must be {expected}")
    roots = config.get("publish_roots")
    if not isinstance(roots, list) or not roots:
        raise ValueError("publish_roots must be a non-empty list")


def collect_files(config: dict[str, Any], output: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    prefix = config["destination_prefix"].strip("/")
    payload_root = output / "payload"

    for entry in config["publish_roots"]:
        source_rel = Path(entry["source"])
        source = ensure_inside_repo(ROOT / source_rel)
        destination = str(entry["destination"]).strip("/")
        required = bool(entry.get("required", True))
        extensions = set(entry.get("extensions", []))

        if not source.exists():
            if required:
                raise FileNotFoundError(f"required publish root does not exist: {source_rel}")
            continue
        if not source.is_dir():
            raise ValueError(f"publish root is not a directory: {source_rel}")

        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            if path.is_symlink():
                raise ValueError(f"symlink is not allowed in publish roots: {path}")
            if extensions and path.suffix not in extensions:
                continue
            ensure_inside_repo(path)

            if source_rel.as_posix() == "data/edinetdb_projections":
                validate_edinetdb_projection(path)

            relative = path.relative_to(source)
            remote_path = Path(prefix) / destination / relative
            local_copy = payload_root / remote_path
            local_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, local_copy)
            files.append(
                {
                    "source_path": path.relative_to(ROOT).as_posix(),
                    "bundle_path": local_copy.relative_to(output).as_posix(),
                    "remote_path": remote_path.as_posix(),
                    "size_bytes": local_copy.stat().st_size,
                    "sha256": sha256_file(local_copy),
                }
            )

    return files


def build_bundle(
    config_path: Path,
    output: Path,
    *,
    source_repo: str,
    source_revision: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = load_json(config_path)
    validate_config(config)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    files = collect_files(config, output)
    timestamp = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "data-lake-manifest.v1",
        "generated_at": timestamp,
        "source_repository": source_repo,
        "source_revision": source_revision,
        "bucket": config["bucket"],
        "destination_prefix": config["destination_prefix"].strip("/"),
        "file_count": len(files),
        "total_bytes": sum(item["size_bytes"] for item in files),
        "policy": config["policy"],
        "files": files,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an allow-listed central data lake bundle.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--source-repo", default="KAFKA2306/semiconductor-earnings-model")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--generated-at")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_bundle(
        Path(args.config),
        Path(args.output),
        source_repo=args.source_repo,
        source_revision=args.source_revision,
        generated_at=args.generated_at,
    )
    print(json.dumps({"file_count": manifest["file_count"], "total_bytes": manifest["total_bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
