#!/usr/bin/env python3
"""SEC EDGAR bulk-first acquisition, normalization, and deterministic audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ARCHIVES = {
    "companyfacts": "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
    "submissions": "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip",
}
MAX_REQUESTS_PER_SECOND = 10.0
MIN_REQUEST_INTERVAL_SECONDS = 1.0 / MAX_REQUESTS_PER_SECOND


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


@dataclass
class RequestPolicy:
    """Enforce SEC fair-access identity and at most 10 requests/second."""

    user_agent: str
    min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS
    monotonic: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    _last_request_started: float | None = None

    def __post_init__(self) -> None:
        if not self.user_agent.strip():
            raise ValueError("SEC requests require a declared User-Agent")
        if self.min_interval_seconds < MIN_REQUEST_INTERVAL_SECONDS:
            raise ValueError("SEC request interval must enforce <= 10 requests/second")

    def wait(self) -> None:
        now = self.monotonic()
        if self._last_request_started is not None:
            remaining = self.min_interval_seconds - (now - self._last_request_started)
            if remaining > 0:
                self.sleeper(remaining)
                now = self.monotonic()
        self._last_request_started = now


def download(
    url: str,
    destination: Path,
    user_agent: str,
    *,
    policy: RequestPolicy | None = None,
    timeout: int = 600,
) -> dict[str, object]:
    """Download atomically so a failed or invalid transfer cannot replace a good snapshot."""
    policy = policy or RequestPolicy(user_agent)
    policy.wait()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": policy.user_agent, "Accept": "application/zip", "Accept-Encoding": "identity"},
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, temporary.open("wb") as handle:
            headers = response.headers
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        if not zipfile.is_zipfile(temporary):
            raise ValueError(f"SEC response is not a ZIP archive: {url}")
        new_sha = sha256_path(temporary)
        old_sha = sha256_path(destination) if destination.exists() else None
        changed = new_sha != old_sha
        if changed:
            os.replace(temporary, destination)
        else:
            temporary.unlink(missing_ok=True)
        return {
            "source_url": url,
            "retrieved_at": utc_now(),
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


def extract_selected(zip_path: Path, output_dir: Path, wanted: dict[str, str]) -> list[dict[str, object]]:
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
                    "sha256": sha256_bytes(raw),
                }
            )
    return extracted


def record_id(kind: str, *parts: object) -> str:
    payload = "|".join([kind, *("" if value is None else str(value) for value in parts)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_companyfacts(payload: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    cik = int(payload["cik"])
    records: list[dict[str, Any]] = []
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise ValueError(f"companyfacts payload for CIK {cik} has no facts object")
    for taxonomy, concepts in sorted(facts.items()):
        if not isinstance(concepts, dict):
            continue
        for concept, definition in sorted(concepts.items()):
            if not isinstance(definition, dict):
                continue
            units = definition.get("units", {})
            if not isinstance(units, dict):
                continue
            for unit, observations in sorted(units.items()):
                if not isinstance(observations, list):
                    continue
                for observation in observations:
                    if not isinstance(observation, dict):
                        continue
                    rid = record_id(
                        "company_fact",
                        cik,
                        taxonomy,
                        concept,
                        unit,
                        observation.get("start"),
                        observation.get("end"),
                        observation.get("accn"),
                        observation.get("form"),
                        observation.get("filed"),
                        observation.get("frame"),
                    )
                    records.append(
                        {
                            "schema_version": "sec-normalized-record.v1",
                            "record_type": "company_fact",
                            "record_id": rid,
                            "source_id": source_id,
                            "cik": cik,
                            "entity_name": payload.get("entityName"),
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "label": definition.get("label"),
                            "description": definition.get("description"),
                            "unit": unit,
                            "value": observation.get("val"),
                            "start": observation.get("start"),
                            "end": observation.get("end"),
                            "accession_number": observation.get("accn"),
                            "fiscal_year": observation.get("fy"),
                            "fiscal_period": observation.get("fp"),
                            "form": observation.get("form"),
                            "filed": observation.get("filed"),
                            "frame": observation.get("frame"),
                        }
                    )
    return records


def normalize_submissions(payload: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    cik = int(payload["cik"])
    recent = payload.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        raise ValueError(f"submissions payload for CIK {cik} has no filings.recent object")
    accessions = recent.get("accessionNumber", [])
    if not isinstance(accessions, list):
        raise ValueError(f"submissions payload for CIK {cik} has invalid accessionNumber")
    fields = (
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "act",
        "form",
        "fileNumber",
        "filmNumber",
        "items",
        "size",
        "isXBRL",
        "isInlineXBRL",
        "primaryDocument",
        "primaryDocDescription",
    )
    records: list[dict[str, Any]] = []
    for index, accession in enumerate(accessions):
        if not accession:
            continue
        values = {
            field: (recent.get(field, [])[index] if index < len(recent.get(field, [])) else None)
            for field in fields
        }
        records.append(
            {
                "schema_version": "sec-normalized-record.v1",
                "record_type": "filing",
                "record_id": record_id("filing", cik, accession),
                "source_id": source_id,
                "cik": cik,
                "entity_name": payload.get("name"),
                "accession_number": accession,
                "filing_date": values["filingDate"],
                "report_date": values["reportDate"],
                "acceptance_datetime": values["acceptanceDateTime"],
                "act": values["act"],
                "form": values["form"],
                "file_number": values["fileNumber"],
                "film_number": values["filmNumber"],
                "items": values["items"],
                "size": values["size"],
                "is_xbrl": values["isXBRL"],
                "is_inline_xbrl": values["isInlineXBRL"],
                "primary_document": values["primaryDocument"],
                "primary_document_description": values["primaryDocDescription"],
            }
        )
    return records


def normalize_selected(archive: str, selected_dir: Path, wanted: dict[str, str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for filename in sorted(wanted):
        payload = json.loads((selected_dir / filename).read_text(encoding="utf-8"))
        if archive == "companyfacts":
            rows = normalize_companyfacts(payload, wanted[filename])
        elif archive == "submissions":
            rows = normalize_submissions(payload, wanted[filename])
        else:
            raise ValueError(f"unsupported SEC archive: {archive}")
        records.extend(rows)
    records.sort(key=lambda row: row["record_id"])
    return records


def merge_records(base: list[dict[str, Any]], delta: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    merged = {row["record_id"]: row for row in base}
    duplicate_count = 0
    conflicts: list[dict[str, Any]] = []
    added_count = 0
    for row in delta:
        rid = row["record_id"]
        existing = merged.get(rid)
        if existing is None:
            merged[rid] = row
            added_count += 1
            continue
        if canonical_json(existing) == canonical_json(row):
            duplicate_count += 1
            continue
        conflicts.append(
            {
                "record_id": rid,
                "base_sha256": sha256_bytes(canonical_json(existing)),
                "delta_sha256": sha256_bytes(canonical_json(row)),
            }
        )
    output = [merged[key] for key in sorted(merged)]
    return output, {
        "schema_version": "sec-bulk-delta-audit.v1",
        "base_record_count": len(base),
        "delta_record_count": len(delta),
        "added_record_count": added_count,
        "duplicate_record_count": duplicate_count,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "status": "PASS" if not conflicts else "CONFLICT",
    }


def write_ndjson(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = b"".join(canonical_json(row) + b"\n" for row in rows)
    path.write_bytes(data)
    return sha256_bytes(data)


def materialize_archive(
    archive: str,
    *,
    registry_path: Path,
    output_dir: Path,
    user_agent: str,
) -> dict[str, Any]:
    wanted = sec_ciks(registry_path)
    archive_dir = output_dir / archive
    zip_path = archive_dir / f"{archive}.zip"
    source = download(ARCHIVES[archive], zip_path, user_agent)
    selected_dir = archive_dir / "selected"
    normalized_path = archive_dir / "normalized.ndjson"

    if source["changed"] or not normalized_path.exists():
        selected = extract_selected(zip_path, selected_dir, wanted)
        normalized = normalize_selected(archive, selected_dir, wanted)
        normalized_sha = write_ndjson(normalized_path, normalized)
    else:
        selected = []
        normalized_sha = sha256_path(normalized_path)
        normalized = [json.loads(line) for line in normalized_path.read_text(encoding="utf-8").splitlines() if line]

    issuer_count = len({row["cik"] for row in normalized})
    if issuer_count < min(10, len(wanted)):
        raise ValueError(f"normalized SEC bulk output covers only {issuer_count} configured issuers")

    manifest = {
        "schema_version": "sec-bulk-snapshot.v2",
        "archive": archive,
        "source": source,
        "configured_sec_issuer_count": len(wanted),
        "normalized_issuer_count": issuer_count,
        "selected_record_count": len(selected) if selected else len(wanted),
        "normalized_record_count": len(normalized),
        "normalized_path": normalized_path.as_posix(),
        "normalized_sha256": normalized_sha,
        "normalization_schema": "sec-normalized-record.v1",
        "status": "PASS",
    }
    manifest_path = archive_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", choices=sorted(ARCHIVES))
    parser.add_argument("--registry", type=Path, default=Path("data/earnings_ledger/source_registry.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/sec_bulk"))
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()

    manifest = materialize_archive(
        args.archive,
        registry_path=args.registry,
        output_dir=args.output_dir,
        user_agent=args.user_agent,
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
