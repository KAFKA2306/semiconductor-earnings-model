#!/usr/bin/env python3
"""Fetch SEC EDGAR bulk archives and materialize only configured issuer records."""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ARCHIVES = {
    "companyfacts": "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
    "submissions": "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip",
}


def sec_ciks(registry_path: Path) -> dict[str, str]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    wanted: dict[str, str] = {}
    for source in registry["sources"]:
        if source.get("adapter") != "sec_edgar" or not source.get("enabled"):
            continue
        cik = source.get("cik")
        if not isinstance(cik, int) or cik <= 0:
            raise ValueError(f"enabled SEC source {source.get('id')!r} has no valid CIK")
        filename = f"CIK{cik:010d}.json"
        if filename in wanted:
            raise ValueError(f"duplicate SEC CIK in source registry: {cik}")
        wanted[filename] = str(source["id"])
    if not wanted:
        raise ValueError("source registry contains no enabled sec_edgar CIKs")
    return wanted


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, user_agent: str) -> dict[str, object]:
    if not user_agent.strip():
        raise ValueError("SEC requests require a declared User-Agent")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/zip"},
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())
        headers = response.headers
    return {
        "source_url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "size_bytes": destination.stat().st_size,
        "sha256": sha256_path(destination),
        "etag": headers.get("ETag"),
        "last_modified": headers.get("Last-Modified"),
    }


def extract_selected(
    zip_path: Path, output_dir: Path, wanted: dict[str, str]
) -> list[dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[dict[str, object]] = []
    with zipfile.ZipFile(zip_path) as archive:
        members = {Path(name).name: name for name in archive.namelist() if not name.endswith("/")}
        missing = sorted(set(wanted) - set(members))
        if missing:
            raise ValueError(f"SEC bulk archive is missing configured CIK files: {missing}")
        for filename in sorted(wanted):
            raw = archive.read(members[filename])
            payload = json.loads(raw)
            expected_cik = int(filename.removeprefix("CIK").removesuffix(".json"))
            if int(payload.get("cik", 0)) != expected_cik:
                raise ValueError(f"embedded CIK mismatch for {filename}")
            target = output_dir / filename
            target.write_bytes(raw)
            extracted.append(
                {
                    "source_id": wanted[filename],
                    "cik": expected_cik,
                    "path": target.as_posix(),
                    "size_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    return extracted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", choices=sorted(ARCHIVES))
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("data/earnings_ledger/source_registry.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/sec_bulk"))
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()

    wanted = sec_ciks(args.registry)
    archive_dir = args.output_dir / args.archive
    zip_path = archive_dir / f"{args.archive}.zip"
    source = download(ARCHIVES[args.archive], zip_path, args.user_agent)
    selected = extract_selected(zip_path, archive_dir / "selected", wanted)
    manifest = {
        "schema_version": "sec-bulk-snapshot.v1",
        "archive": args.archive,
        "source": source,
        "configured_sec_issuer_count": len(wanted),
        "selected_record_count": len(selected),
        "records": selected,
    }
    manifest_path = archive_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(manifest_path)


if __name__ == "__main__":
    main()
