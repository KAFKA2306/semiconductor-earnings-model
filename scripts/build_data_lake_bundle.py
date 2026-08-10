from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "data_lake_publish.json"
DEFAULT_OUTPUT = ROOT / ".data_lake_bundle"
EDINETDB_PLAN_REL = Path("config/edinetdb_quota_plan.json")
ALLOWED_REMOTE_REPOSITORY = re.compile(r"^KAFKA2306/[A-Za-z0-9_.-]+$")
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


def ensure_inside(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes its repository root: {path}") from exc
    return resolved


def ensure_inside_repo(path: Path) -> Path:
    return ensure_inside(path, ROOT, label="path")


def normalized_destination(value: str) -> PurePosixPath:
    destination = PurePosixPath(value.strip("/"))
    if (
        destination.is_absolute()
        or not destination.parts
        or any(part in {"", ".", ".."} for part in destination.parts)
    ):
        raise ValueError(f"invalid destination: {value!r}")
    if destination.parts[0] == "manifests":
        raise ValueError("publish roots cannot write into the reserved manifests prefix")
    return destination


def pattern_matches(relative_path: str, pattern: str) -> bool:
    if "/" not in pattern and "/" in relative_path:
        return False
    return fnmatch.fnmatchcase(relative_path, pattern)


def _projection_contract(
    payload: dict[str, Any], quota_plan: dict[str, Any]
) -> tuple[set[str], str]:
    consumer = payload.get("consumer")
    projection_id = payload.get("projection_id")
    if not isinstance(consumer, str) or not consumer:
        raise ValueError("EDINETDB projection consumer is required")
    if not isinstance(projection_id, str) or not projection_id:
        raise ValueError("EDINETDB projection_id is required")

    if projection_id.startswith("company-master-"):
        master = quota_plan.get("company_master", {})
        consumers = {
            repo
            for repos in master.get("code_consumers", {}).values()
            for repo in repos
        }
        if consumer not in consumers:
            raise ValueError(
                f"unregistered EDINETDB company-master consumer: {consumer}"
            )
        fields = set(master.get("projection_fields", []))
        if not fields:
            raise ValueError("EDINETDB company-master projection fields are empty")
        return fields, "/v1/companies"

    matches = [
        item
        for item in quota_plan.get("requests", [])
        if item.get("id") == projection_id and item.get("consumer") == consumer
    ]
    if len(matches) != 1:
        raise ValueError(
            f"EDINETDB projection is not in quota-plan allow list: {consumer}/{projection_id}"
        )
    request = matches[0]
    fields = set(request.get("projection_fields", []))
    if not fields:
        raise ValueError(
            f"EDINETDB projection allow list is empty: {consumer}/{projection_id}"
        )
    return fields, str(request.get("path", ""))


def validate_edinetdb_projection(
    path: Path, quota_plan: dict[str, Any] | None = None
) -> None:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"EDINETDB projection must be a JSON object: {path}")
    if payload.get("schema_version") != "edinetdb.consumer-projection.v1":
        raise ValueError(f"unexpected EDINETDB projection schema: {path}")
    if payload.get("provider") != "EDINET DB":
        raise ValueError(f"unexpected EDINETDB projection provider: {path}")
    unknown = set(payload) - EDINETDB_PROJECTION_KEYS
    if unknown:
        raise ValueError(
            f"unexpected EDINETDB projection top-level fields {sorted(unknown)}: {path}"
        )
    if not isinstance(payload.get("records"), list):
        raise ValueError(f"EDINETDB projection records must be a list: {path}")
    if payload.get("record_count") != len(payload["records"]):
        raise ValueError(f"EDINETDB projection record_count mismatch: {path}")
    fingerprint = str(payload.get("request_fingerprint", ""))
    response_sha = str(payload.get("response_sha256", ""))
    if len(fingerprint) != 64 or any(
        ch not in "0123456789abcdef" for ch in fingerprint
    ):
        raise ValueError(f"invalid request fingerprint: {path}")
    if len(response_sha) != 64 or any(
        ch not in "0123456789abcdef" for ch in response_sha
    ):
        raise ValueError(f"invalid response SHA-256: {path}")

    plan = quota_plan or load_json(ROOT / EDINETDB_PLAN_REL)
    allowed_fields, expected_endpoint = _projection_contract(payload, plan)
    if payload.get("source_endpoint") != expected_endpoint:
        raise ValueError(
            f"EDINETDB projection endpoint is not allow-listed for "
            f"{payload.get('consumer')}/{payload.get('projection_id')}: {path}"
        )

    for index, record in enumerate(payload["records"]):
        if not isinstance(record, dict):
            raise ValueError(
                f"EDINETDB projection record {index} must be an object: {path}"
            )
        unexpected_record_fields = set(record) - allowed_fields
        if unexpected_record_fields:
            raise ValueError(
                "unexpected EDINETDB record fields "
                f"{sorted(unexpected_record_fields)} for "
                f"{payload.get('consumer')}/{payload.get('projection_id')}: {path}"
            )


def validate_publish_root(entry: dict[str, Any]) -> None:
    source = entry.get("source")
    destination = entry.get("destination")
    if not isinstance(source, str) or not source:
        raise ValueError("publish root source is required")
    if not isinstance(destination, str) or not destination:
        raise ValueError("publish root destination is required")
    normalized_destination(destination)

    source_path = PurePosixPath(source)
    if source_path.is_absolute() or any(part == ".." for part in source_path.parts):
        raise ValueError(
            f"publish root source must stay inside its repository: {source!r}"
        )

    repository = entry.get("repository")
    if repository is not None:
        if (
            not isinstance(repository, str)
            or not ALLOWED_REMOTE_REPOSITORY.fullmatch(repository)
        ):
            raise ValueError(f"remote repository is not allow-listed: {repository!r}")
        if entry.get("ref") != "main":
            raise ValueError("remote repositories must use ref=main")
    elif "ref" in entry:
        raise ValueError("local publish roots must not declare ref")

    extensions = entry.get("extensions", [])
    if not isinstance(extensions, list) or not all(
        isinstance(extension, str) and extension.startswith(".")
        for extension in extensions
    ):
        raise ValueError(f"invalid extensions for publish root {source!r}")

    for field in ("include", "exclude"):
        patterns = entry.get(field, [])
        if not isinstance(patterns, list) or not all(
            isinstance(pattern, str) and pattern for pattern in patterns
        ):
            raise ValueError(f"invalid {field} patterns for publish root {source!r}")
        if any(".." in PurePosixPath(pattern).parts for pattern in patterns):
            raise ValueError(f"{field} pattern escapes publish root: {source!r}")


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

    destinations: list[PurePosixPath] = []
    for entry in roots:
        if not isinstance(entry, dict):
            raise ValueError("each publish root must be an object")
        validate_publish_root(entry)
        destination = normalized_destination(entry["destination"])
        for existing in destinations:
            if (
                destination == existing
                or destination.parts == existing.parts[: len(destination.parts)]
                or existing.parts == destination.parts[: len(existing.parts)]
            ):
                raise ValueError(
                    f"publish root destinations overlap: {existing} and {destination}"
                )
        destinations.append(destination)


def run_git(
    command: list[str], *, cwd: Path | None = None, capture: bool = False
) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", "-c", "credential.helper=", *command],
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )
    return completed.stdout.strip() if capture else ""


def checkout_public_repository(
    repository: str, ref: str, checkout_root: Path
) -> tuple[Path, str]:
    if not ALLOWED_REMOTE_REPOSITORY.fullmatch(repository):
        raise ValueError(f"remote repository is not allow-listed: {repository!r}")
    if ref != "main":
        raise ValueError("remote repositories must use ref=main")

    checkout_root.mkdir(parents=True, exist_ok=True)
    checkout = checkout_root / repository.replace("/", "__")
    if checkout.exists():
        shutil.rmtree(checkout)
    run_git(
        [
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            ref,
            f"https://github.com/{repository}.git",
            str(checkout),
        ]
    )
    revision = run_git(["rev-parse", "HEAD"], cwd=checkout, capture=True)
    if len(revision) != 40 or any(
        ch not in "0123456789abcdef" for ch in revision
    ):
        raise ValueError(f"invalid source revision from {repository}: {revision!r}")
    return checkout, revision


def selected_files(source: Path, entry: dict[str, Any]) -> list[Path]:
    extensions = set(entry.get("extensions", []))
    includes = entry.get("include", [])
    excludes = entry.get("exclude", [])
    files: list[Path] = []

    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError(f"symlink is not allowed in publish roots: {path}")
        relative = path.relative_to(source).as_posix()
        if extensions and path.suffix not in extensions:
            continue
        if includes and not any(
            pattern_matches(relative, pattern) for pattern in includes
        ):
            continue
        if excludes and any(
            pattern_matches(relative, pattern) for pattern in excludes
        ):
            continue
        files.append(path)
    return files


def collect_files(
    config: dict[str, Any],
    output: Path,
    *,
    source_repo: str,
    source_revision: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files: list[dict[str, Any]] = []
    roots_manifest: list[dict[str, Any]] = []
    prefix = config["destination_prefix"].strip("/")
    payload_root = output / "payload"
    checkout_root = output / "_sources"
    checkout_cache: dict[tuple[str, str], tuple[Path, str]] = {}
    edinetdb_plan: dict[str, Any] | None = None

    try:
        for entry in config["publish_roots"]:
            repository = entry.get("repository")
            if repository:
                key = (repository, entry["ref"])
                if key not in checkout_cache:
                    checkout_cache[key] = checkout_public_repository(
                        repository, entry["ref"], checkout_root
                    )
                repository_root, revision = checkout_cache[key]
                origin_repository = repository
            else:
                repository_root = ROOT
                revision = source_revision
                origin_repository = source_repo

            source_rel = Path(entry["source"])
            source = ensure_inside(
                repository_root / source_rel,
                repository_root,
                label="publish root",
            )
            destination = normalized_destination(entry["destination"])
            required = bool(entry.get("required", True))
            destination_root = payload_root / prefix / Path(*destination.parts)
            destination_root.mkdir(parents=True, exist_ok=True)

            if not source.exists():
                if required:
                    raise FileNotFoundError(
                        f"required publish root does not exist: "
                        f"{origin_repository}:{source_rel}"
                    )
                roots_manifest.append(
                    {
                        "source_repository": origin_repository,
                        "source_revision": revision,
                        "source_path": source_rel.as_posix(),
                        "destination": (
                            PurePosixPath(prefix) / destination
                        ).as_posix(),
                        "file_count": 0,
                        "total_bytes": 0,
                    }
                )
                continue
            if not source.is_dir():
                raise ValueError(
                    f"publish root is not a directory: "
                    f"{origin_repository}:{source_rel}"
                )

            if repository is None and source_rel.as_posix() == "data/edinetdb_projections":
                edinetdb_plan = load_json(ROOT / EDINETDB_PLAN_REL)

            root_files: list[dict[str, Any]] = []
            for path in selected_files(source, entry):
                ensure_inside(path, repository_root, label="publish file")
                if repository is None and source_rel.as_posix() == "data/edinetdb_projections":
                    assert edinetdb_plan is not None
                    validate_edinetdb_projection(path, edinetdb_plan)

                relative = path.relative_to(source)
                remote_path = (
                    PurePosixPath(prefix)
                    / destination
                    / PurePosixPath(relative.as_posix())
                )
                local_copy = payload_root / Path(*remote_path.parts)
                local_copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, local_copy)
                item = {
                    "source_repository": origin_repository,
                    "source_revision": revision,
                    "source_path": (source_rel / relative).as_posix(),
                    "bundle_path": local_copy.relative_to(output).as_posix(),
                    "remote_path": remote_path.as_posix(),
                    "size_bytes": local_copy.stat().st_size,
                    "sha256": sha256_file(local_copy),
                }
                files.append(item)
                root_files.append(item)

            if required and not root_files:
                raise ValueError(
                    f"required publish root selected zero files: "
                    f"{origin_repository}:{source_rel}"
                )
            roots_manifest.append(
                {
                    "source_repository": origin_repository,
                    "source_revision": revision,
                    "source_path": source_rel.as_posix(),
                    "destination": (PurePosixPath(prefix) / destination).as_posix(),
                    "file_count": len(root_files),
                    "total_bytes": sum(
                        item["size_bytes"] for item in root_files
                    ),
                }
            )
    finally:
        shutil.rmtree(checkout_root, ignore_errors=True)

    return files, roots_manifest


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

    files, roots_manifest = collect_files(
        config,
        output,
        source_repo=source_repo,
        source_revision=source_revision,
    )
    timestamp = generated_at or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "data-lake-manifest.v2",
        "generated_at": timestamp,
        "source_repository": source_repo,
        "source_revision": source_revision,
        "bucket": config["bucket"],
        "destination_prefix": config["destination_prefix"].strip("/"),
        "file_count": len(files),
        "total_bytes": sum(item["size_bytes"] for item in files),
        "policy": config["policy"],
        "roots": roots_manifest,
        "files": files,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an allow-listed central data lake bundle."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--source-repo", default="KAFKA2306/semiconductor-earnings-model"
    )
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
    print(
        json.dumps(
            {
                "file_count": manifest["file_count"],
                "total_bytes": manifest["total_bytes"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
