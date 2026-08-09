from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "earnings_ledger"
PUBLICATION_PATH = LEDGER_DIR / "publication_latest.json"
AUDIT_PATH = LEDGER_DIR / "audit_latest.json"
OUTPUT_PATH = LEDGER_DIR / "publication_latest.md"
EXPECTED_SCHEMA = "earnings-ledger-publication.v1"
FRESHNESS_HOURS = 24


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_dt(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"required timestamp missing: {field}")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        raise ValueError(f"timezone missing: {field}")
    return dt.astimezone(timezone.utc)


def safe_text(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def validate(publication: dict[str, Any], audit: dict[str, Any]) -> datetime:
    if publication.get("schema_version") != EXPECTED_SCHEMA:
        raise ValueError("unsupported publication schema")
    if publication.get("audit_status") != "PASS":
        raise ValueError("publication audit_status is not PASS")
    if audit.get("status") != "PASS" or audit.get("issues"):
        raise ValueError("ledger audit is not clean PASS")

    contract = publication.get("contract")
    required_contract = {
        "primary_sources_only": True,
        "freshness_gate_hours": FRESHNESS_HOURS,
        "publication_rechecks_freshness": True,
        "fail_closed": True,
        "unverified_values_published": False,
    }
    if not isinstance(contract, dict) or any(contract.get(k) != v for k, v in required_contract.items()):
        raise ValueError("publication safety contract mismatch")

    run_at = parse_dt(publication.get("generated_from_run_at"), "publication.generated_from_run_at")
    audit_run_at = parse_dt(audit.get("run_at"), "audit.run_at")
    if run_at != audit_run_at:
        raise ValueError("publication/audit run mismatch")

    events = publication.get("events")
    if not isinstance(events, list):
        raise ValueError("publication events must be a list")
    if publication.get("accepted_events_total") != len(events):
        raise ValueError("publication accepted event count mismatch")
    if publication.get("ledger_accepted_events_total") != audit.get("accepted_events_total"):
        raise ValueError("ledger accepted event count mismatch")
    if publication.get("rejected_events_total") != audit.get("rejected_events_total"):
        raise ValueError("rejected event count mismatch")

    seen: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("publication event must be an object")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("publication event_id missing")
        if event_id in seen:
            raise ValueError(f"duplicate publication event_id: {event_id}")
        seen.add(event_id)
        if event.get("freshness") != "PASS":
            raise ValueError(f"non-PASS event in publication: {event_id}")
        source_url = event.get("source_url")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            raise ValueError(f"verified HTTPS source_url missing: {event_id}")
        published_at = parse_dt(event.get("published_at"), f"event[{event_id}].published_at")
        age = run_at - published_at
        if age < timedelta(0):
            raise ValueError(f"future event in publication: {event_id}")
        if age > timedelta(hours=FRESHNESS_HOURS):
            raise ValueError(f"expired event in publication: {event_id}")

    disabled = publication.get("unsupported_or_disabled_sources", [])
    if not isinstance(disabled, list) or any(not isinstance(item, str) or not item for item in disabled):
        raise ValueError("invalid disabled source list")
    return run_at


def build_markdown(publication: dict[str, Any], audit: dict[str, Any]) -> str:
    run_at = validate(publication, audit)
    events = publication["events"]
    disabled = publication.get("unsupported_or_disabled_sources", [])

    lines = [
        "# 決算収集・監査 公開スナップショット",
        "",
        f"- 監査run: `{run_at.isoformat().replace('+00:00', 'Z')}`",
        f"- 公開可能（24時間以内）: **{len(events)}件**",
        f"- 履歴accepted: **{publication['ledger_accepted_events_total']}件**",
        f"- 期限切れ除外: **{publication['expired_events_total']}件**",
        f"- rejected: **{publication['rejected_events_total']}件**",
        "- 契約: 一次情報のみ / 24時間鮮度 / fail-closed / 未確認値を公開しない",
        "",
        "## 公開対象",
        "",
    ]
    if not events:
        lines.append("現在、24時間鮮度ゲートを通過した公開対象はありません。")
    else:
        lines.extend([
            "| 企業 | 文書 | 公開時刻 | 一次情報 |",
            "|---|---|---|---|",
        ])
        for event in events:
            company = safe_text(event.get("company_name") or event.get("company_id"))
            document = safe_text(event.get("document_type"))
            published = safe_text(event.get("published_at"))
            source = event["source_url"]
            lines.append(f"| {company} | {document} | `{published}` | [一次情報]({source}) |")

    lines.extend(["", "## 未対応・無効化中の情報源", ""])
    if disabled:
        lines.extend(f"- `{safe_text(source_id)}`" for source_id in disabled)
    else:
        lines.append("なし")
    lines.extend(["", "> このMarkdownは監査済みpublication artifactのみから生成し、期限切れ・未確認の値を復元しません。", ""])
    return "\n".join(lines)


def main() -> int:
    publication = load_json(PUBLICATION_PATH)
    audit = load_json(AUDIT_PATH)
    try:
        text = build_markdown(publication, audit)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"PASS: wrote {OUTPUT_PATH} with {publication['accepted_events_total']} fresh events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
