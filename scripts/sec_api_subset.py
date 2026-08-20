#!/usr/bin/env python3
"""Bulk-first SEC materialization with a bounded per-CIK API fallback.

The official SEC bulk ZIPs remain the preferred source. Some hosted execution
networks receive HTTP 403 from www.sec.gov while data.sec.gov remains available.
In that case, this module materializes exactly one JSON response per configured
CIK, through the same normalized record contract used by the bulk path.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import sec_bulk

API_URLS = {
    "companyfacts": "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
    "submissions": "https://data.sec.gov/submissions/CIK{cik:010d}.json",
}


def download_json(
    url: str,
    destination: Path,
    expected_cik: int,
    *,
    policy: sec_bulk.RequestPolicy,
    timeout: int = 60,
) -> dict[str, Any]:
    """Fetch one SEC JSON object atomically and retain request provenance."""
    policy.wait()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": policy.user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            headers = response.headers
            status = getattr(response, "status", 200)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"SEC API response is not an object: {url}")
        if int(payload.get("cik", 0)) != expected_cik:
            raise ValueError(f"SEC API embedded CIK mismatch for {expected_cik}: {url}")
        temporary.write_bytes(raw)
        new_sha = sec_bulk.sha256_bytes(raw)
        old_sha = sec_bulk.sha256_path(destination) if destination.exists() else None
        changed = new_sha != old_sha
        if changed:
            os.replace(temporary, destination)
        else:
            temporary.unlink(missing_ok=True)
        return {
            "source_url": url,
            "retrieved_at": sec_bulk.utc_now(),
            "http_status": status,
            "content_type": headers.get("Content-Type"),
            "content_length_header": headers.get("Content-Length"),
            "etag": headers.get("ETag"),
            "last_modified": headers.get("Last-Modified"),
            "size_bytes": destination.stat().st_size,
            "sha256": new_sha,
            "changed": changed,
        }
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def materialize_api_subset(
    archive: str,
    *,
    registry_path: Path,
    output_dir: Path,
    user_agent: str,
    bulk_http_status: int,
) -> dict[str, Any]:
    wanted = sec_bulk.sec_ciks(registry_path)
    archive_dir = output_dir / archive
    selected_dir = archive_dir / "selected"
    normalized_path = archive_dir / "normalized.ndjson"
    policy = sec_bulk.RequestPolicy(user_agent)
    sources: list[dict[str, Any]] = []

    for filename, source_id in sorted(wanted.items()):
        cik = int(filename.removeprefix("CIK").removesuffix(".json"))
        url = API_URLS[archive].format(cik=cik)
        metadata = download_json(url, selected_dir / filename, cik, policy=policy)
        metadata.update({"source_id": source_id, "cik": cik})
        sources.append(metadata)

    normalized = sec_bulk.normalize_selected(archive, selected_dir, wanted)
    normalized_sha = sec_bulk.write_ndjson(normalized_path, normalized)
    issuer_count = len({row["cik"] for row in normalized})
    if issuer_count < min(10, len(wanted)):
        raise ValueError(f"normalized SEC API subset covers only {issuer_count} configured issuers")

    manifest = {
        "schema_version": "sec-canonical-snapshot.v2",
        "archive": archive,
        "source_mode": "api_subset_fallback",
        "bulk_source_url": sec_bulk.ARCHIVES[archive],
        "bulk_http_status": bulk_http_status,
        "fallback_reason": "official bulk archive returned HTTP 403 in this execution environment",
        "api_template": API_URLS[archive],
        "request_policy": {
            "declared_user_agent": True,
            "max_requests_per_second": sec_bulk.MAX_REQUESTS_PER_SECOND,
            "requests_made": len(sources),
            "dedupe_scope": "one request per configured CIK",
        },
        "sources": sources,
        "configured_sec_issuer_count": len(wanted),
        "normalized_issuer_count": issuer_count,
        "selected_record_count": len(sources),
        "normalized_record_count": len(normalized),
        "normalized_path": normalized_path.as_posix(),
        "normalized_sha256": normalized_sha,
        "normalization_schema": "sec-normalized-record.v1",
        "status": "PASS",
    }
    manifest_path = archive_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def materialize_auto(
    archive: str,
    *,
    registry_path: Path,
    output_dir: Path,
    user_agent: str,
) -> dict[str, Any]:
    """Prefer SEC bulk and fall back only on an observed HTTP 403."""
    try:
        manifest = sec_bulk.materialize_archive(
            archive,
            registry_path=registry_path,
            output_dir=output_dir,
            user_agent=user_agent,
        )
        manifest["source_mode"] = "bulk"
        manifest["bulk_http_status"] = 200
        manifest_path = output_dir / archive / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
        return materialize_api_subset(
            archive,
            registry_path=registry_path,
            output_dir=output_dir,
            user_agent=user_agent,
            bulk_http_status=exc.code,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", choices=sorted(sec_bulk.ARCHIVES))
    parser.add_argument("--registry", type=Path, default=Path("data/earnings_ledger/source_registry.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/sec_bulk"))
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()
    manifest = materialize_auto(
        args.archive,
        registry_path=args.registry,
        output_dir=args.output_dir,
        user_agent=args.user_agent,
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
