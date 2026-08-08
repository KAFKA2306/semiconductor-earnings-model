from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "earnings_ledger"
PUBLIC = ROOT / "site" / "public" / "api" / "v1" / "earnings-ledger" / "index.json"
SNAPSHOT = LEDGER / "publication_latest.json"

AUDITS = {
    "ledger": "audit_latest.json",
    "semantic_duplicates": "semantic_duplicate_audit_latest.json",
    "period_normalization": "period_normalization_latest.json",
    "accounting_basis": "accounting_basis_audit_latest.json",
    "evidence": "evidence_latest.json",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def require_pass(name: str, payload: dict) -> None:
    status = payload.get("status")
    if status is not None and status != "PASS":
        raise SystemExit(f"{name} audit is not PASS: {status}")
    if payload.get("issues"):
        raise SystemExit(f"{name} audit contains issues")


def build_publication() -> dict:
    audits: dict[str, dict] = {}
    for name, filename in AUDITS.items():
        path = LEDGER / filename
        if not path.exists():
            raise SystemExit(f"required audit artifact missing: {filename}")
        payload = load_json(path)
        require_pass(name, payload)
        audits[name] = payload

    ledger_audit = audits["ledger"]
    events = load_events(LEDGER / "events.ndjson")
    accepted_total = ledger_audit.get("accepted_events_total")
    if accepted_total != len(events):
        raise SystemExit(
            f"accepted event count mismatch: audit={accepted_total} events={len(events)}"
        )

    safe_events = []
    for event in events:
        if event.get("freshness") != "PASS":
            raise SystemExit(f"non-PASS event cannot be published: {event.get('event_id')}")
        safe_events.append(
            {
                key: event.get(key)
                for key in (
                    "event_id",
                    "company_id",
                    "company_name",
                    "document_type",
                    "published_at",
                    "source_url",
                    "freshness",
                )
            }
        )

    return {
        "schema_version": "earnings-ledger-publication.v1",
        "generated_from_run_at": ledger_audit.get("run_at"),
        "audit_status": "PASS",
        "accepted_events_total": accepted_total,
        "rejected_events_total": ledger_audit.get("rejected_events_total"),
        "unsupported_or_disabled_sources": ledger_audit.get(
            "unsupported_or_disabled_sources", []
        ),
        "events": safe_events,
        "audit_artifacts": {name: filename for name, filename in AUDITS.items()},
        "contract": {
            "primary_sources_only": True,
            "freshness_gate_hours": 24,
            "fail_closed": True,
            "unverified_values_published": False,
        },
    }


def main() -> None:
    payload = build_publication()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(text, encoding="utf-8")
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.write_text(text, encoding="utf-8")
    print(f"published {payload['accepted_events_total']} audited earnings events")


if __name__ == "__main__":
    main()
