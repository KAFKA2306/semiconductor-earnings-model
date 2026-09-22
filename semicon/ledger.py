from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

NULL_REASONS = {
    "not_disclosed",
    "not_applicable",
    "extraction_failed",
    "not_available_for_period",
    "stale_source",
    "not_provided_in_source",
}

SOURCE_PRIORITY = {
    "sec_edgar": 1,
    "edinet": 1,
    "company_ir": 2,
    "canonical_existing": 3,
    "google_sheets": 4,
    "xlsx_import": 4,
}

DERIVED_METRICS = {
    "capex_to_revenue",
    "capex_to_depreciation",
    "cip_to_ppe",
    "free_cash_flow",
    "free_cash_flow_proxy",
    "fcf_proxy",
    "required_revenue",
    "payback",
    "roic",
    "irr",
    "evidence_status",
    "plan_vs_actual",
    "gross_margin",
    "operating_margin",
    "capex_to_operating_cf",
}

CANONICAL_FACT_METRICS = {
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cf",
    "investing_cf",
    "capex",
    "depreciation",
    "ppe",
    "construction_in_progress",
    "rnd",
    "inventory",
    "order_backlog",
    "orders_received",
    "cash",
    "debt",
}

CANONICAL_EVENT_TYPES = {
    "capacity_expansion",
    "new_factory",
    "production_start",
    "qualification",
    "long_term_agreement",
    "customer_commitment",
    "prepayment",
    "delay",
    "capex_plan",
    "capex_avoidance",
}


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any, length: int = 24) -> str:
    return hashlib.sha256(json_dumps(value).encode("utf-8")).hexdigest()[:length]


def normalize_header(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.strip().lower()
    text = re.sub(r"[\s\-/]+", "_", text)
    text = re.sub(r"[^0-9a-z_]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def coerce_number(value: Any) -> int | float | None:
    value = blank_to_none(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def normalize_date(value: Any) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", text):
        y, m, d = text.split("/")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return text


def fiscal_year_from_value(value: Any) -> int | None:
    value = blank_to_none(value)
    if value is None:
        return None
    text = str(value).strip().upper()
    m = re.search(r"(?:FY)?\s*(20\d{2})", text)
    return int(m.group(1)) if m else None


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda r: str(r.get("fact_id") or r.get("event_id") or r.get("project_id") or r.get("facility_id") or r.get("commitment_id") or r.get("record_id") or ""))
    path.write_text("".join(json_dumps(record) + "\n" for record in ordered), encoding="utf-8")


def source_rank(source_system: str | None) -> int:
    return SOURCE_PRIORITY.get((source_system or "").lower(), 99)


def semantic_equal(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        try:
            return json_dumps(a) == json_dumps(b)
        except (TypeError, ValueError):
            return a == b
    na = coerce_number(a)
    nb = coerce_number(b)
    if na is not None and nb is not None:
        return Decimal(str(na)) == Decimal(str(nb))
    return str(a).strip() == str(b).strip()


def provenance_identity(item: dict[str, Any]) -> tuple[Any, ...]:
    """Identity of one imported source row, excluding volatile collection time.

    Replaying the same semantic raw snapshot must not append another provenance
    entry just because imported_at changed.
    """
    return (
        item.get("import_source"),
        item.get("spreadsheet_id"),
        item.get("sheet_name"),
        item.get("source_row"),
        item.get("original_source_url"),
        item.get("doc_id"),
        item.get("raw_snapshot_sha256"),
    )


def merge_provenance(existing: list[dict[str, Any]] | None, incoming: dict[str, Any]) -> list[dict[str, Any]]:
    by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in [*(existing or []), incoming]:
        key = provenance_identity(item)
        current = by_identity.get(key)
        if current is None:
            by_identity[key] = dict(item)
            continue
        current_time = str(current.get("imported_at") or "")
        incoming_time = str(item.get("imported_at") or "")
        if incoming_time and (not current_time or incoming_time < current_time):
            by_identity[key] = dict(item)
    return sorted(by_identity.values(), key=lambda item: tuple("" if value is None else str(value) for value in provenance_identity(item)))


@dataclass(frozen=True)
class Conflict:
    record_type: str
    key: str
    existing: dict[str, Any]
    incoming: dict[str, Any]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "key": self.key,
            "reason": self.reason,
            "existing": self.existing,
            "incoming": self.incoming,
        }


def validate_fact(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = [
        "fact_id",
        "entity_id",
        "metric",
        "unit",
        "period_start",
        "period_end",
        "fiscal_year",
        "source_system",
        "source_doc_id",
        "source_url",
        "native_concept",
        "quality_flag",
    ]
    for field in required:
        if record.get(field) in (None, ""):
            errors.append(f"missing:{field}")
    if record.get("metric") not in CANONICAL_FACT_METRICS:
        errors.append(f"unsupported_metric:{record.get('metric')}")
    if record.get("metric") in DERIVED_METRICS:
        errors.append(f"derived_metric_in_canonical:{record.get('metric')}")
    if record.get("value") is None and not record.get("null_reason"):
        errors.append("null_without_reason")
    if record.get("value") == 0 and record.get("null_reason"):
        errors.append("zero_with_null_reason")
    return errors


def validate_provenance(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    provenance = record.get("provenance")
    if not isinstance(provenance, list) or not provenance:
        return ["missing:provenance"]
    for idx, item in enumerate(provenance):
        for field in ("import_source", "spreadsheet_id", "sheet_name", "source_row", "imported_at", "original_source_url", "doc_id"):
            if field not in item:
                errors.append(f"provenance[{idx}].missing:{field}")
    return errors


def canonical_key(record_type: str, record: dict[str, Any]) -> str:
    if record_type == "fact":
        return "|".join(
            str(record.get(k) or "")
            for k in ("entity_id", "metric", "period_start", "period_end", "unit", "native_concept")
        )
    fields = {
        "event": ("event_id",),
        "project": ("project_id",),
        "facility": ("facility_id",),
        "commitment": ("commitment_id",),
        "backlog": ("record_id",),
    }.get(record_type, ("id",))
    return "|".join(str(record.get(k) or "") for k in fields)


def dedupe_or_conflict(
    record_type: str,
    existing_records: list[dict[str, Any]],
    incoming_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, list[Conflict]]:
    index = {canonical_key(record_type, r): dict(r) for r in existing_records}
    duplicates = 0
    conflicts: list[Conflict] = []
    for incoming in incoming_records:
        key = canonical_key(record_type, incoming)
        current = index.get(key)
        if current is None:
            index[key] = incoming
            continue

        compare_fields = {
            "fact": ("value", "unit", "period_start", "period_end", "native_concept"),
            "event": ("event_type", "entity_id", "announcement_date", "status"),
            "project": ("entity_id", "project_name", "capex_plan", "capex_actual", "capacity_before", "capacity_after", "status"),
            "facility": ("entity_id", "facility_name", "fiscal_year", "book_value_total"),
            "commitment": ("entity_id", "customer_name", "commitment_type", "amount", "volume", "period_start", "period_end"),
            "backlog": ("entity_id", "fiscal_year", "segment", "orders_received", "order_backlog"),
        }.get(record_type, ())
        equal = all(semantic_equal(current.get(field), incoming.get(field)) for field in compare_fields)
        if equal:
            duplicates += 1
            for p in incoming.get("provenance") or []:
                current["provenance"] = merge_provenance(current.get("provenance"), p)
            index[key] = current
            continue

        current_rank = source_rank(current.get("source_system"))
        incoming_rank = source_rank(incoming.get("source_system"))
        conflicts.append(
            Conflict(
                record_type=record_type,
                key=key,
                existing=current,
                incoming=incoming,
                reason=f"value_mismatch existing_priority={current_rank} incoming_priority={incoming_rank}",
            )
        )
    return list(index.values()), duplicates, conflicts
