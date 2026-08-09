from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
REGISTRY_PATH = LEDGER_DIR / "source_registry.json"
AUDIT_PATH = LEDGER_DIR / "audit_latest.json"
STATE_PATH = LEDGER_DIR / "state.json"
EVENTS_PATH = LEDGER_DIR / "events.ndjson"
REJECTED_PATH = LEDGER_DIR / "rejected.ndjson"
OUTPUT_PATH = LEDGER_DIR / "source_state.json"


def parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise RuntimeError(f"timezone missing: {value}")
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _status_by_source(registry: dict[str, Any], audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError("source registry must contain sources")
    source_ids = [source.get("id") for source in sources]
    if any(not source_id for source_id in source_ids) or len(source_ids) != len(set(source_ids)):
        raise RuntimeError("source registry ids must be unique and non-empty")

    statuses = audit.get("source_status")
    if not isinstance(statuses, list):
        raise RuntimeError("audit source_status must be a list")
    by_source: dict[str, dict[str, Any]] = {}
    for item in statuses:
        source_id = item.get("source_id")
        if source_id in by_source:
            raise RuntimeError(f"duplicate audit source status: {source_id}")
        by_source[source_id] = item
    if set(by_source) != set(source_ids):
        raise RuntimeError("audit source_status must cover registry sources exactly")
    if any(item.get("status") == "error" for item in by_source.values()):
        raise RuntimeError("cannot persist source cursor from failed source collection")
    return by_source


def _resolve_source_id(row: dict[str, Any], registry: dict[str, Any]) -> str:
    adapter = row.get("source_adapter")
    company_id = row.get("company_id")
    if not adapter or not company_id:
        raise RuntimeError("ledger row missing source_adapter/company_id")

    sources = registry["sources"]
    exact = [
        source
        for source in sources
        if source.get("id") == company_id and source.get("adapter") == adapter
    ]
    if len(exact) == 1:
        return str(exact[0]["id"])

    adapter_sources = [
        source
        for source in sources
        if source.get("adapter") == adapter and source.get("enabled", True)
    ]
    if len(adapter_sources) != 1:
        raise RuntimeError(
            f"ledger row cannot be mapped to exactly one source: adapter={adapter!r} company_id={company_id!r}"
        )
    return str(adapter_sources[0]["id"])


def build_source_state(
    registry: dict[str, Any],
    audit: dict[str, Any],
    state: dict[str, Any],
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> dict[str, Any]:
    if audit.get("status") != "PASS" or audit.get("issues") not in ([], None):
        raise RuntimeError("latest ledger audit must be PASS with no issues")
    if state.get("audit_status") != "PASS":
        raise RuntimeError("latest ledger state must be PASS")
    run_at_raw = audit.get("run_at")
    if not run_at_raw or state.get("last_run_at") != run_at_raw:
        raise RuntimeError("ledger audit/state run binding mismatch")
    run_at = parse_dt(str(run_at_raw))
    status_by_source = _status_by_source(registry, audit)

    latest: dict[str, tuple[datetime, str, str]] = {}
    for disposition, rows in (("accepted", accepted), ("rejected", rejected)):
        for row in rows:
            event_id = row.get("event_id")
            published_at = row.get("published_at")
            if not event_id or not published_at:
                raise RuntimeError("ledger row missing event_id/published_at")
            published = parse_dt(str(published_at))
            if published > run_at + timedelta(minutes=5):
                raise RuntimeError(f"future published_at in ledger row: {event_id}")
            source_id = _resolve_source_id(row, registry)
            candidate = (published, str(event_id), disposition)
            current = latest.get(source_id)
            if current is None or candidate[:2] > current[:2]:
                latest[source_id] = candidate

    output_sources: list[dict[str, Any]] = []
    for source in registry["sources"]:
        source_id = str(source["id"])
        cursor = latest.get(source_id)
        output_sources.append(
            {
                "source_id": source_id,
                "adapter": source.get("adapter"),
                "enabled": bool(source.get("enabled", True)),
                "collection_status": status_by_source[source_id].get("status"),
                "last_seen_id": cursor[1] if cursor else None,
                "last_seen_published_at": iso(cursor[0]) if cursor else None,
                "last_seen_disposition": cursor[2] if cursor else None,
            }
        )

    return {
        "schema_version": "earnings-source-state.v1",
        "generated_from_run_at": iso(run_at),
        "sources": output_sources,
        "contract": {
            "derived_from_persisted_ledgers_only": True,
            "audit_state_run_binding_required": True,
            "timezone_required": True,
            "failed_source_persistence": "forbidden",
        },
    }


def main() -> int:
    result = build_source_state(
        load_json(REGISTRY_PATH),
        load_json(AUDIT_PATH),
        load_json(STATE_PATH),
        load_ndjson(EVENTS_PATH),
        load_ndjson(REJECTED_PATH),
    )
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "sources": len(result["sources"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
