from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "config" / "edinetdb_quota_plan.json"
DEFAULT_LEDGER = ROOT / "data" / "edinetdb_quota" / "ledger.json"
DEFAULT_PROJECTIONS = ROOT / "data" / "edinetdb_projections"
BASE_URL = "https://edinetdb.jp"
MAX_MASTER_CODES_PER_REQUEST = 50


@dataclass
class ProjectionSpec:
    consumer: str
    projection_id: str
    fields: tuple[str, ...]
    edinet_codes: tuple[str, ...] = ()


@dataclass
class PlannedRequest:
    method: str
    path: str
    params: tuple[tuple[str, str], ...]
    projections: list[ProjectionSpec] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "method": self.method,
                "path": self.path,
                "params": self.params,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @property
    def url(self) -> str:
        query = urlencode(list(self.params), doseq=True)
        return f"{BASE_URL}{self.path}" + (f"?{query}" if query else "")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "edinetdb.quota-ledger.v1", "days": {}}
    data = load_json(path)
    if data.get("schema_version") != "edinetdb.quota-ledger.v1":
        raise ValueError("unsupported quota ledger schema")
    return data


def consumer_slug(repo: str) -> str:
    return repo.replace("/", "__")


def projection_path(root: Path, spec: ProjectionSpec) -> Path:
    return root / consumer_slug(spec.consumer) / f"{spec.projection_id}.json"


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def build_plan(config: dict[str, Any]) -> list[PlannedRequest]:
    requests_by_key: dict[tuple[str, str, tuple[tuple[str, str], ...]], PlannedRequest] = {}

    master = config.get("company_master", {})
    codes = sorted(set(master.get("codes", [])))
    fields = tuple(master.get("projection_fields", []))
    code_consumers = master.get("code_consumers", {})

    for chunk_index, chunk in enumerate(_chunked(codes, MAX_MASTER_CODES_PER_REQUEST), 1):
        params = tuple(("edinet_code", code) for code in chunk)
        request = PlannedRequest(method="GET", path="/v1/companies", params=params)
        consumers = sorted(
            {
                consumer
                for code in chunk
                for consumer in code_consumers.get(code, [])
            }
        )
        for consumer in consumers:
            consumer_codes = tuple(
                code for code in chunk if consumer in code_consumers.get(code, [])
            )
            if consumer_codes:
                request.projections.append(
                    ProjectionSpec(
                        consumer=consumer,
                        projection_id=f"company-master-{chunk_index:02d}",
                        fields=fields,
                        edinet_codes=consumer_codes,
                    )
                )
        requests_by_key[(request.method, request.path, request.params)] = request

    for item in config.get("requests", []):
        method = item.get("method", "GET").upper()
        if method != "GET":
            raise ValueError(f"quota owner supports read-only GET only: {item.get('id')}")
        params = tuple(sorted((str(key), str(value)) for key, value in item.get("params", {}).items()))
        key = (method, item["path"], params)
        request = requests_by_key.setdefault(
            key,
            PlannedRequest(method=method, path=item["path"], params=params),
        )
        request.projections.append(
            ProjectionSpec(
                consumer=item["consumer"],
                projection_id=item["id"],
                fields=tuple(item.get("projection_fields", [])),
            )
        )

    return list(requests_by_key.values())


def validate_plan(config: dict[str, Any], plan: list[PlannedRequest]) -> None:
    daily_limit = int(config["daily_limit"])
    reserve = int(config["reserve_requests"])
    usable = daily_limit - reserve
    if daily_limit <= 0 or reserve < 0 or usable <= 0:
        raise ValueError("invalid daily_limit/reserve_requests")
    if len(plan) > usable:
        raise ValueError(
            f"planned authenticated requests={len(plan)} exceeds usable budget={usable} "
            f"(daily_limit={daily_limit}, reserve={reserve})"
        )
    for request in plan:
        if request.path == "/v1/companies":
            codes = [value for key, value in request.params if key == "edinet_code"]
            if len(codes) > MAX_MASTER_CODES_PER_REQUEST:
                raise ValueError("company master batch exceeds 50 EDINET codes")
        if not request.projections:
            raise ValueError(f"request has no consumer projection: {request.path}")


def _unwrap_records(payload: Any) -> list[dict[str, Any]]:
    value = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("companies", "financials", "items", "results"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return [value]
    return []


def _project_record(record: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: record[field] for field in fields if field in record}


def build_projection(payload: Any, spec: ProjectionSpec) -> list[dict[str, Any]]:
    records = _unwrap_records(payload)
    if spec.edinet_codes:
        wanted = set(spec.edinet_codes)
        records = [row for row in records if row.get("edinet_code") in wanted]
    return [_project_record(row, spec.fields) for row in records]


def request_json(request: PlannedRequest, api_key: str) -> tuple[Any, str]:
    http_request = Request(
        request.url,
        method="GET",
        headers={
            "Accept": "application/json",
            "X-API-Key": api_key,
            "User-Agent": "KAFKA2306-edinetdb-quota-owner/1.0",
        },
    )
    try:
        with urlopen(http_request, timeout=60) as response:
            body = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"EDINETDB HTTP {exc.code} for {request.url}; not retrying") from exc
    except URLError as exc:
        raise RuntimeError(f"EDINETDB network error for {request.url}; not retrying") from exc
    sha256 = hashlib.sha256(body).hexdigest()
    return json.loads(body.decode("utf-8")), sha256


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def already_materialized(
    ledger: dict[str, Any],
    day: str,
    request: PlannedRequest,
    projections_root: Path,
) -> bool:
    day_state = ledger.get("days", {}).get(day, {})
    record = day_state.get("requests", {}).get(request.fingerprint)
    if not record or record.get("status") != "success":
        return False
    return all(projection_path(projections_root, spec).exists() for spec in request.projections)


def write_projection(
    root: Path,
    request: PlannedRequest,
    spec: ProjectionSpec,
    projected: list[dict[str, Any]],
    response_sha256: str,
    fetched_at: str,
    attribution: str,
) -> None:
    path = projection_path(root, spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "edinetdb.consumer-projection.v1",
        "consumer": spec.consumer,
        "projection_id": spec.projection_id,
        "provider": "EDINET DB",
        "attribution": attribution,
        "provider_terms": "https://edinetdb.jp/legal/terms",
        "source_endpoint": request.path,
        "request_fingerprint": request.fingerprint,
        "fetched_at": fetched_at,
        "response_sha256": response_sha256,
        "record_count": len(projected),
        "records": projected,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_success(
    ledger: dict[str, Any],
    day: str,
    request: PlannedRequest,
    response_sha256: str,
    fetched_at: str,
) -> None:
    day_state = ledger.setdefault("days", {}).setdefault(day, {"requests": {}})
    day_state.setdefault("requests", {})[request.fingerprint] = {
        "status": "success",
        "method": request.method,
        "path": request.path,
        "params": list(request.params),
        "consumers": sorted({spec.consumer for spec in request.projections}),
        "response_sha256": response_sha256,
        "completed_at": fetched_at,
    }


def print_plan(config: dict[str, Any], plan: list[PlannedRequest], *, day: str) -> None:
    usable = int(config["daily_limit"]) - int(config["reserve_requests"])
    print(f"day={day}")
    print(f"unique_authenticated_requests={len(plan)}")
    print(f"usable_budget={usable}")
    print(f"reserved={config['reserve_requests']}")
    for index, request in enumerate(plan, 1):
        consumers = ",".join(sorted({spec.consumer for spec in request.projections}))
        print(f"{index:02d} {request.method} {request.url} -> {consumers}")


def run(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    ledger_path = Path(args.ledger)
    projections_root = Path(args.projections)
    config = load_json(plan_path)
    plan = build_plan(config)
    validate_plan(config, plan)
    day = args.day or today_utc()
    print_plan(config, plan, day=day)

    if args.plan_only:
        return 0

    api_key = os.environ.get("EDINETDB_API_KEY")
    if not api_key:
        raise RuntimeError("EDINETDB_API_KEY is required for fetch mode")

    ledger = load_ledger(ledger_path)
    fetched_count = 0
    skipped_count = 0
    for request in plan:
        if already_materialized(ledger, day, request, projections_root) and not args.force:
            skipped_count += 1
            continue
        payload, response_sha256 = request_json(request, api_key)
        fetched_at = now_utc()
        for spec in request.projections:
            projected = build_projection(payload, spec)
            write_projection(
                projections_root,
                request,
                spec,
                projected,
                response_sha256,
                fetched_at,
                config["attribution"],
            )
        record_success(ledger, day, request, response_sha256, fetched_at)
        fetched_count += 1

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"fetched_requests={fetched_count}")
    print(f"reused_requests={skipped_count}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deduplicate EDINETDB requests and materialize consumer-only projections."
    )
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--projections", default=str(DEFAULT_PROJECTIONS))
    parser.add_argument("--day")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        sys.exit(run(parse_args()))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
