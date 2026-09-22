from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from semicon.ledger import (
    CANONICAL_EVENT_TYPES,
    DERIVED_METRICS,
    blank_to_none,
    canonical_key,
    coerce_number,
    dedupe_or_conflict,
    fiscal_year_from_value,
    load_json,
    load_jsonl,
    normalize_date,
    normalize_header,
    stable_hash,
    validate_fact,
    validate_provenance,
    write_json,
    write_jsonl,
)

DEFAULT_SPREADSHEET_ID = "1lClRXXTUW8-yJtC_PxwvzQ03llC08nW6ovMzQMk5XDQ"
ROOT = Path(__file__).resolve().parents[2]

SHEET_CLASSIFICATION = {
    "readme": "metadata",
    "dashboard": "presentation",
    "issuer_master": "canonical",
    "company_master": "canonical",
    "index_membership": "metadata",
    "us_index_master": "metadata",
    "financials": "canonical",
    "annual_financials": "canonical",
    "latest_capex": "canonical",
    "capex_events": "canonical",
    "capex_plans": "canonical",
    "project_capex": "canonical",
    "capex_projects": "canonical",
    "facilities": "canonical",
    "orders_backlog": "canonical",
    "main_customers": "canonical",
    "demand_commitments": "canonical",
    "customer_commitments": "canonical",
    "capacity_metrics": "canonical",
    "decision_evidence": "derived",
    "decision_view": "derived",
    "decision_framework": "metadata",
    "economics_model": "derived",
    "project_lifecycle": "derived",
    "coverage": "metadata",
    "data_dictionary": "metadata",
    "data_quality": "metadata",
    "sources": "metadata",
    "ingestion_status": "metadata",
}

FINANCIAL_METRIC_ALIASES = {
    "revenue": "revenue", "revenue_mm": "revenue", "sales": "revenue", "net_sales": "revenue",
    "gross_profit": "gross_profit", "gross_profit_mm": "gross_profit",
    "operating_income": "operating_income", "operating_income_mm": "operating_income",
    "net_income": "net_income", "net_income_mm": "net_income",
    "operating_cf": "operating_cf", "operating_cf_mm": "operating_cf",
    "cash_flow_from_operations": "operating_cf",
    "investing_cf": "investing_cf", "investing_cf_mm": "investing_cf",
    "capex": "capex", "capex_mm": "capex", "latest_capex": "capex",
    "depreciation": "depreciation", "depreciation_mm": "depreciation",
    "ppe": "ppe", "ppe_mm": "ppe", "property_plant_equipment": "ppe",
    "construction_in_progress": "construction_in_progress",
    "construction_in_progress_mm": "construction_in_progress",
    "cip": "construction_in_progress", "cip_mm": "construction_in_progress",
    "rnd": "rnd", "r_d": "rnd", "research_and_development": "rnd",
    "inventory": "inventory", "inventory_mm": "inventory",
    "orders_received": "orders_received", "orders_received_mm": "orders_received",
    "order_backlog": "order_backlog", "backlog": "order_backlog", "backlog_mm": "order_backlog",
    "cash": "cash", "cash_mm": "cash", "debt": "debt", "debt_mm": "debt",
}

EVENT_TYPE_MAP = {
    "expansion": "capacity_expansion", "capacity expansion": "capacity_expansion",
    "capacity_expansion": "capacity_expansion", "new factory": "new_factory",
    "new_factory": "new_factory", "production start": "production_start",
    "production_start": "production_start", "qualification": "qualification",
    "long term agreement": "long_term_agreement", "long-term agreement": "long_term_agreement",
    "lta": "long_term_agreement", "customer commitment": "customer_commitment",
    "customer_commitment": "customer_commitment", "prepayment": "prepayment",
    "delay": "delay", "annual capex guidance": "capex_plan",
    "committed capex": "capex_plan", "capex plan": "capex_plan", "capex_plan": "capex_plan",
    "capex avoidance": "capex_avoidance", "capex_avoidance": "capex_avoidance",
}


def classify_sheet(name: str, headers: list[Any] | None = None) -> str:
    normalized = normalize_header(name)
    if normalized in SHEET_CLASSIFICATION:
        return SHEET_CLASSIFICATION[normalized]
    h = {normalize_header(x) for x in (headers or []) if blank_to_none(x) is not None}
    if {"entity_id", "metric", "value"}.issubset(h):
        return "canonical"
    if {"company", "ticker"}.intersection(h) and {"country", "currency"}.intersection(h):
        return "canonical"
    if any(x in h for x in DERIVED_METRICS):
        return "derived"
    return "metadata"


def _column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    result = 0
    for ch in letters:
        result = result * 26 + (ord(ch) - 64)
    return result - 1


def _date_style_ids(zf: zipfile.ZipFile) -> set[int]:
    try:
        root = ET.fromstring(zf.read("xl/styles.xml"))
    except KeyError:
        return set()
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    custom = {}
    for fmt in root.findall("x:numFmts/x:numFmt", ns):
        try:
            custom[int(fmt.attrib["numFmtId"])] = fmt.attrib.get("formatCode", "")
        except (KeyError, ValueError):
            pass
    builtin_date_ids = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
    date_styles: set[int] = set()
    xfs = root.find("x:cellXfs", ns)
    if xfs is None:
        return date_styles
    for idx, xf in enumerate(list(xfs)):
        num_fmt_id = int(xf.attrib.get("numFmtId", "0"))
        code = custom.get(num_fmt_id, "").lower()
        code_without_literals = re.sub(r'"[^"]*"', "", code)
        if num_fmt_id in builtin_date_ids or bool(re.search(r"[ymdhis]", code_without_literals)):
            date_styles.add(idx)
    return date_styles


def _excel_date(value: str) -> str:
    base = datetime(1899, 12, 30, tzinfo=timezone.utc)
    dt = base + timedelta(days=float(value))
    if abs(float(value) - int(float(value))) < 1e-9:
        return dt.date().isoformat()
    return dt.isoformat().replace("+00:00", "Z")


def parse_xlsx_bytes(blob: bytes, *, spreadsheet_id: str, imported_at: str, source_name: str = "google_sheets") -> dict[str, Any]:
    zf = zipfile.ZipFile(io.BytesIO(blob))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("r:Relationship", rel_ns)}

    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in root.findall("x:si", ns):
            shared.append("".join(t.text or "" for t in si.iterfind(".//x:t", ns)))

    date_styles = _date_style_ids(zf)
    sheets: list[dict[str, Any]] = []
    for sheet_el in workbook.findall("x:sheets/x:sheet", ns):
        name = sheet_el.attrib["name"]
        rel_id = sheet_el.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rel_map[rel_id].lstrip("/")
        path = target if target.startswith("xl/") else f"xl/{target}"
        root = ET.fromstring(zf.read(path))
        parsed_rows: list[list[Any]] = []
        max_col = 0
        for row_el in root.findall("x:sheetData/x:row", ns):
            cells: dict[int, Any] = {}
            for c in row_el.findall("x:c", ns):
                ref = c.attrib.get("r", "A1")
                col = _column_index(ref)
                max_col = max(max_col, col + 1)
                cell_type = c.attrib.get("t")
                style_id = int(c.attrib.get("s", "0"))
                inline = c.find("x:is", ns)
                v = c.find("x:v", ns)
                value: Any = None
                if inline is not None:
                    value = "".join(t.text or "" for t in inline.iterfind(".//x:t", ns))
                elif v is not None:
                    raw = v.text or ""
                    if cell_type == "s":
                        try:
                            value = shared[int(raw)]
                        except (ValueError, IndexError):
                            value = raw
                    elif cell_type == "b":
                        value = raw == "1"
                    elif cell_type in {"str", "inlineStr"}:
                        value = raw
                    elif style_id in date_styles and raw:
                        try:
                            value = _excel_date(raw)
                        except ValueError:
                            value = raw
                    else:
                        number = coerce_number(raw)
                        value = number if number is not None else raw
                cells[col] = value
            if cells:
                width = max(max_col, max(cells) + 1)
                row = [None] * width
                for col, value in cells.items():
                    row[col] = value
                parsed_rows.append(row)
        width = max((len(row) for row in parsed_rows), default=0)
        rows = [row + [None] * (width - len(row)) for row in parsed_rows]
        headers = rows[0] if rows else []
        sheets.append({"name": name, "classification": classify_sheet(name, headers), "rows": rows})

    binary_digest = hashlib.sha256(blob).hexdigest()
    semantic_bytes = json.dumps(sheets, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    semantic_digest = hashlib.sha256(semantic_bytes).hexdigest()
    return {
        "schema_version": "google-sheets-raw.v1",
        "spreadsheet_id": spreadsheet_id,
        "source_name": source_name,
        "imported_at": imported_at,
        "source_sha256": semantic_digest,
        "source_binary_sha256": binary_digest,
        "sheets": sheets,
    }


def fetch_google_sheet_xlsx(spreadsheet_id: str, token: str | None = None) -> bytes:
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
    headers = {"User-Agent": "semiconductor-earnings-model/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        hint = " Set GOOGLE_OAUTH_ACCESS_TOKEN for a private Sheet." if exc.code in {401, 403} else ""
        raise RuntimeError(f"Google Sheets export failed: HTTP {exc.code}.{hint}") from exc


def _rows_as_dicts(sheet: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    rows = sheet.get("rows") or []
    if not rows:
        return []
    headers = [normalize_header(x) for x in rows[0]]
    result: list[tuple[int, dict[str, Any]]] = []
    for source_row, row in enumerate(rows[1:], start=2):
        values = {headers[i]: blank_to_none(row[i] if i < len(row) else None) for i in range(len(headers)) if headers[i]}
        if any(v is not None for v in values.values()):
            result.append((source_row, values))
    return result


def _get(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        key = normalize_header(name)
        if key in row and row[key] is not None:
            return row[key]
    return None


def _source_url(row: dict[str, Any]) -> str | None:
    return _get(row, "source_url", "url", "original_source_url", "source")


def _provenance(snapshot: dict[str, Any], sheet: str, source_row: int, row: dict[str, Any]) -> dict[str, Any]:
    original_url = _source_url(row)
    doc_id = _get(row, "source_doc_id", "doc_id", "accession", "edinet_doc_id")
    if doc_id is None:
        doc_id = f"gsheet:{snapshot['spreadsheet_id']}:{sheet}:{source_row}"
    return {
        "import_source": "google_sheets" if snapshot.get("source_name") == "google_sheets" else "xlsx_import",
        "spreadsheet_id": snapshot.get("spreadsheet_id"),
        "sheet_name": sheet,
        "source_row": source_row,
        "imported_at": snapshot.get("imported_at"),
        "original_source_url": original_url,
        "doc_id": str(doc_id),
        "raw_snapshot_sha256": snapshot.get("source_sha256"),
    }


def _source_system(row: dict[str, Any], snapshot: dict[str, Any]) -> str:
    explicit = _get(row, "source_system", "source_type")
    text = str(explicit or "").lower()
    url = str(_source_url(row) or "").lower()
    if "sec.gov" in url or "edgar" in text:
        return "sec_edgar"
    if "edinet" in url or "edinet" in text:
        return "edinet"
    if url and any(x in url for x in ("investor", "ir.", "/ir/", "newsrelease", "coherent.com", "jx-nmm.com", "kioxia", "intc.com", "micron.com", "tsmc.com")):
        return "company_ir"
    return "google_sheets" if snapshot.get("source_name") == "google_sheets" else "xlsx_import"


def _entity_id(row: dict[str, Any]) -> str | None:
    value = _get(row, "entity_id", "issuer_id", "company_id")
    if value is not None:
        return str(value)
    ticker = _get(row, "ticker", "security_ticker_or_code", "security_code", "code")
    country = str(_get(row, "country") or "").upper()
    if ticker is not None and country in {"JP", "JAPAN"}:
        return f"JP:{ticker}"
    if ticker is not None and country in {"US", "USA", "UNITED STATES"}:
        return f"US:{ticker}"
    return None


def _entity_from_row(row: dict[str, Any], snapshot: dict[str, Any], sheet_name: str, source_row: int) -> dict[str, Any] | None:
    entity_id = _entity_id(row)
    if not entity_id:
        return None
    ticker = _get(row, "ticker")
    security_code = _get(row, "security_code", "security_ticker_or_code")
    if ticker is None and str(entity_id).startswith("US:"):
        ticker = str(entity_id).split(":", 1)[1]
    if security_code is None and str(entity_id).startswith("JP:"):
        security_code = str(entity_id).split(":", 1)[1]
    company_name = _get(row, "company_name", "company", "security_name", "name")
    memberships = []
    raw_memberships = _get(row, "index_membership")
    if isinstance(raw_memberships, str) and raw_memberships.strip():
        try:
            parsed = json.loads(raw_memberships)
            if isinstance(parsed, list):
                memberships = parsed
        except json.JSONDecodeError:
            pass
    return {
        "entity_id": str(entity_id),
        "id": str(entity_id),
        "company_name": company_name,
        "name": company_name,
        "ticker": ticker,
        "security_code": security_code,
        "cik": _get(row, "cik"),
        "edinet_code": _get(row, "edinet_code"),
        "country": _get(row, "country"),
        "currency": _get(row, "currency", "reporting_currency"),
        "role": _get(row, "primary_role", "role"),
        "index_membership": memberships,
        "provenance": [_provenance(snapshot, sheet_name, source_row, row)],
    }


def _merge_entities(existing: dict[str, Any], incoming: dict[str, Any], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    out = dict(existing)
    out.setdefault("entity_id", out.get("id"))
    out.setdefault("id", out.get("entity_id"))
    if out.get("name") and not out.get("company_name"):
        out["company_name"] = out["name"]
    if out.get("company_name") and not out.get("name"):
        out["name"] = out["company_name"]
    for field in ("company_name", "name", "ticker", "security_code", "cik", "edinet_code", "country", "currency", "role"):
        old, new = out.get(field), incoming.get(field)
        if old in (None, "") and new not in (None, ""):
            out[field] = new
        elif new not in (None, "") and old not in (None, "") and str(old) != str(new):
            if field in {"company_name", "name"}:
                aliases = set(out.get("aliases") or [])
                aliases.add(str(new))
                out["aliases"] = sorted(aliases)
            elif field == "ticker":
                aliases = set(out.get("ticker_aliases") or [])
                aliases.add(str(new))
                out["ticker_aliases"] = sorted(aliases)
            elif field == "security_code":
                aliases = set(out.get("security_codes") or [])
                aliases.add(str(new))
                out["security_codes"] = sorted(aliases)
            elif field == "role":
                roles = set(out.get("role_aliases") or [])
                roles.add(str(new))
                out["role_aliases"] = sorted(roles)
            else:
                conflicts.append({"record_type": "entity", "key": out.get("entity_id"), "field": field, "existing": old, "incoming": new})
    memberships = list(out.get("index_membership") or [])
    for item in incoming.get("index_membership") or []:
        if item not in memberships:
            memberships.append(item)
    out["index_membership"] = sorted(memberships, key=lambda x: (str(x.get("index_name")), str(x.get("as_of_date")), str(x.get("security_ticker_or_code"))))
    provenance = list(out.get("provenance") or [])
    for item in incoming.get("provenance") or []:
        if item not in provenance:
            provenance.append(item)
    out["provenance"] = provenance
    return out


def _fact_records(sheet: dict[str, Any], snapshot: dict[str, Any], invalid: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source_row, row in _rows_as_dicts(sheet):
        entity_id = _entity_id(row)
        period_start = normalize_date(_get(row, "period_start"))
        period_end = normalize_date(_get(row, "period_end", "as_of_date"))
        fiscal_year = fiscal_year_from_value(_get(row, "fiscal_year", "fiscal_period", "period_end"))
        period_type = _get(row, "period_type") or ("FY" if fiscal_year else None)
        currency = _get(row, "currency", "reporting_currency")
        source_url = _source_url(row)
        source_system = _source_system(row, snapshot)
        provenance = _provenance(snapshot, sheet["name"], source_row, row)

        explicit_metric = _get(row, "metric")
        if explicit_metric is not None:
            metric = FINANCIAL_METRIC_ALIASES.get(normalize_header(explicit_metric), normalize_header(explicit_metric))
            value = coerce_number(_get(row, "value"))
            native = _get(row, "native_concept", "concept", "xbrl_tag")
            unit = _get(row, "unit") or currency
            rec = _make_fact(entity_id, metric, value, unit, period_start, period_end, fiscal_year, period_type, source_system, source_url, native, provenance, row)
            errs = validate_fact(rec)
            if errs:
                invalid.append({"sheet": sheet["name"], "row": source_row, "errors": errs, "record": rec})
            else:
                out.append(rec)
            continue

        for header, raw in row.items():
            metric = FINANCIAL_METRIC_ALIASES.get(header)
            if not metric or metric in DERIVED_METRICS:
                continue
            if raw is None:
                continue
            value = coerce_number(raw)
            if value is None:
                invalid.append({"sheet": sheet["name"], "row": source_row, "errors": [f"non_numeric:{header}"], "value": raw})
                continue
            unit = currency
            if header.endswith("_mm"):
                unit = f"{currency}_million" if currency else "million"
            native = _get(row, f"{header}_native_concept", "native_concept") or header
            rec = _make_fact(entity_id, metric, value, unit, period_start, period_end, fiscal_year, period_type, source_system, source_url, native, provenance, row)
            errs = validate_fact(rec)
            if errs:
                invalid.append({"sheet": sheet["name"], "row": source_row, "errors": errs, "record": rec})
            else:
                out.append(rec)
    return out


def _make_fact(entity_id: str | None, metric: str, value: Any, unit: Any, period_start: str | None, period_end: str | None, fiscal_year: int | None, period_type: Any, source_system: str, source_url: str | None, native: Any, provenance: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    quality = _get(row, "quality_flag", "status") or "imported_unverified"
    source_doc_id = _get(row, "source_doc_id", "doc_id", "accession", "edinet_doc_id") or provenance["doc_id"]
    return {
        "fact_id": "fact:" + stable_hash([entity_id, metric, period_start, period_end, unit, native]),
        "entity_id": entity_id, "metric": metric, "value": value, "unit": unit,
        "period_start": period_start, "period_end": period_end, "fiscal_year": fiscal_year,
        "period_type": period_type, "source_system": source_system,
        "source_doc_id": str(source_doc_id) if source_doc_id is not None else None,
        "source_url": source_url, "native_concept": native,
        "accounting_standard": _get(row, "accounting_standard"),
        "quality_flag": quality, "null_reason": _get(row, "null_reason"),
        "provenance": [provenance],
    }


def _standard_event_type(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    mapped = EVENT_TYPE_MAP.get(text, normalize_header(text))
    return mapped if mapped in CANONICAL_EVENT_TYPES else None


def _event_and_project_records(sheet: dict[str, Any], snapshot: dict[str, Any], invalid: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events, projects = [], []
    for source_row, row in _rows_as_dicts(sheet):
        entity_id = _entity_id(row)
        event_type = _standard_event_type(_get(row, "event_type", "type"))
        if event_type is None and normalize_header(sheet["name"]) in {"capex_plans", "project_capex", "capex_events"}:
            event_type = "capex_plan"
        if entity_id is None or event_type is None:
            invalid.append({"sheet": sheet["name"], "row": source_row, "errors": ["missing entity_id or recognized event_type"], "record": row})
            continue
        provenance = _provenance(snapshot, sheet["name"], source_row, row)
        event_id = str(_get(row, "event_id") or f"event:{stable_hash([entity_id, event_type, _get(row, 'announcement_date'), _get(row, 'project_name'), source_row, sheet['name']])}")
        source_url = _source_url(row)
        source_system = _source_system(row, snapshot)
        source_doc_id = str(_get(row, "source_doc_id", "doc_id") or provenance["doc_id"])
        event = {
            "event_id": event_id, "entity_id": entity_id, "event_type": event_type,
            "announcement_date": normalize_date(_get(row, "announced_date", "announcement_date")),
            "period_start": normalize_date(_get(row, "period_start")),
            "period_end": normalize_date(_get(row, "period_end", "target_date")),
            "project_name": _get(row, "project_name", "project", "business_or_process"),
            "status": _get(row, "status") or "imported_unverified",
            "evidence_text": _get(row, "management_rationale", "source_note", "evidence_text"),
            "source_system": source_system, "source_doc_id": source_doc_id, "source_url": source_url,
            "quality_flag": _get(row, "quality_flag") or "imported_unverified",
            "provenance": [provenance],
        }
        events.append(event)

        if event_type in {"capex_plan", "capacity_expansion", "new_factory", "capex_avoidance", "production_start"}:
            project_id = str(_get(row, "project_id") or event_id.replace("event:", "project:"))
            low = coerce_number(_get(row, "amount_low_local_mm", "capex_plan_low", "capex_plan"))
            high = coerce_number(_get(row, "amount_high_local_mm", "capex_plan_high", "capex_plan"))
            currency = _get(row, "currency")
            projects.append({
                "project_id": project_id, "event_id": event_id, "event_type": event_type,
                "entity_id": entity_id, "project_name": _get(row, "project_name", "project") or event_id,
                "product": _get(row, "product", "business_or_process"), "technology": _get(row, "technology"),
                "facility_id": _get(row, "facility_id"), "location": _get(row, "region", "location", "site"),
                "announcement_date": event["announcement_date"], "period_start": normalize_date(_get(row, "period_start")),
                "period_end": normalize_date(_get(row, "period_end", "target_date")),
                "capex_plan": None if low is None and high is None else {"low": low, "high": high, "currency": currency, "scale": "million"},
                "capex_actual": coerce_number(_get(row, "capex_actual")), "currency": currency,
                "capacity_before": coerce_number(_get(row, "capacity_before", "capacity_current")),
                "capacity_after": coerce_number(_get(row, "capacity_after", "capacity_target")),
                "capacity_change": coerce_number(_get(row, "capacity_change")), "capacity_unit": _get(row, "capacity_unit"),
                "planned_start": normalize_date(_get(row, "planned_start")),
                "production_start": normalize_date(_get(row, "production_start", "target_date")) if event_type == "production_start" else normalize_date(_get(row, "production_start")),
                "demand_evidence": _get(row, "management_rationale", "demand_evidence"),
                "customer_commitment": _get(row, "customer_commitment"),
                "orders_backlog_reference": _get(row, "orders_backlog_reference"),
                "funding_source": _get(row, "funding_source"), "subsidy": coerce_number(_get(row, "subsidy")),
                "debt": coerce_number(_get(row, "debt")), "customer_deposit": coerce_number(_get(row, "customer_deposit", "prepayment")),
                "status": event["status"], "source_system": source_system, "source_doc_id": source_doc_id,
                "source_url": source_url, "quality_flag": event["quality_flag"], "provenance": [provenance],
            })
    return events, projects


def _facility_records(sheet: dict[str, Any], snapshot: dict[str, Any], invalid: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for source_row, row in _rows_as_dicts(sheet):
        entity_id = _entity_id(row)
        name = _get(row, "facility_name", "site", "facility")
        if not entity_id or not name:
            invalid.append({"sheet": sheet["name"], "row": source_row, "errors": ["missing entity_id/facility_name"]})
            continue
        p = _provenance(snapshot, sheet["name"], source_row, row)
        out.append({
            "facility_id": str(_get(row, "facility_id") or f"facility:{stable_hash([entity_id, name, _get(row, 'location')])}"),
            "entity_id": entity_id, "facility_name": name, "location": _get(row, "location"),
            "country": _get(row, "country"), "prefecture": _get(row, "prefecture"), "municipality": _get(row, "municipality"),
            "book_value_total": coerce_number(_get(row, "book_value_total")), "buildings": coerce_number(_get(row, "buildings")),
            "machinery": coerce_number(_get(row, "machinery")), "land": coerce_number(_get(row, "land")),
            "land_area_m2": coerce_number(_get(row, "land_area_m2")), "employees": coerce_number(_get(row, "employees")),
            "fiscal_year": fiscal_year_from_value(_get(row, "fiscal_year")),
            "source_system": _source_system(row, snapshot),
            "source_doc_id": str(_get(row, "source_doc_id", "doc_id") or p["doc_id"]),
            "source_url": _source_url(row), "quality_flag": _get(row, "quality_flag") or "imported_unverified",
            "provenance": [p],
        })
    return out

def _commitment_records(sheet: dict[str, Any], snapshot: dict[str, Any], invalid: list[dict[str, Any]], default_type: str | None = None) -> list[dict[str, Any]]:
    out = []
    for source_row, row in _rows_as_dicts(sheet):
        entity_id = _entity_id(row)
        customer = _get(row, "customer_name", "customer", "main_customer")
        ctype = _get(row, "commitment_type") or default_type
        if not entity_id or not customer:
            status = str(_get(row, "status", "note") or "").lower()
            if "no_order_disclosure" in status or "no >=10%" in status or "not disclosed" in status:
                continue
            invalid.append({"sheet": sheet["name"], "row": source_row, "errors": ["missing entity_id/customer_name"]})
            continue
        p = _provenance(snapshot, sheet["name"], source_row, row)
        out.append({
            "commitment_id": str(_get(row, "commitment_id") or f"commitment:{stable_hash([entity_id, customer, ctype, _get(row, 'period_start'), _get(row, 'period_end')])}"),
            "entity_id": entity_id, "customer_name": customer, "commitment_type": ctype or "customer_relationship",
            "amount": coerce_number(_get(row, "amount", "amount_local_mm", "revenue_mm")),
            "volume": coerce_number(_get(row, "volume", "minimum_volume")),
            "period_start": normalize_date(_get(row, "period_start", "term_start")),
            "period_end": normalize_date(_get(row, "period_end", "term_end")),
            "contract_status": _get(row, "contract_status", "status"), "evidence_text": _get(row, "evidence_text", "source_note"),
            "source_system": _source_system(row, snapshot), "source_url": _source_url(row),
            "source_doc_id": str(_get(row, "source_doc_id", "doc_id") or p["doc_id"]),
            "quality_flag": _get(row, "quality_flag") or "imported_unverified", "provenance": [p],
        })
    return out


def _backlog_records(sheet: dict[str, Any], snapshot: dict[str, Any], invalid: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for source_row, row in _rows_as_dicts(sheet):
        entity_id = _entity_id(row)
        fy = fiscal_year_from_value(_get(row, "fiscal_year", "period"))
        if not entity_id or fy is None:
            invalid.append({"sheet": sheet["name"], "row": source_row, "errors": ["missing entity_id/fiscal_year"]})
            continue
        orders = coerce_number(_get(row, "orders_received", "orders"))
        backlog = coerce_number(_get(row, "order_backlog", "backlog"))
        if orders is None and backlog is None:
            continue
        p = _provenance(snapshot, sheet["name"], source_row, row)
        out.append({
            "record_id": str(_get(row, "record_id") or f"backlog:{stable_hash([entity_id, fy, _get(row, 'segment')])}"),
            "entity_id": entity_id, "fiscal_year": fy, "segment": _get(row, "segment") or "total",
            "orders_received": orders, "order_backlog": backlog, "currency": _get(row, "currency"),
            "source_system": _source_system(row, snapshot),
            "source_doc_id": str(_get(row, "source_doc_id", "doc_id") or p["doc_id"]),
            "source_url": _source_url(row), "quality_flag": _get(row, "quality_flag", "status") or "imported_unverified",
            "provenance": [p],
        })
    return out


def build_import(snapshot: dict[str, Any], *, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    invalid: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    sheets = snapshot.get("sheets") or []

    legacy = load_json(root / "data/primary/entities.json", {"entities": []}) or {"entities": []}
    registry_existing = load_json(root / "data/registry/entities.json", {"entities": []}) or {"entities": []}
    entities_by_id: dict[str, dict[str, Any]] = {}
    sheet_entity_ids = {str(_entity_id(row)) for s in sheets if normalize_header(s.get("name", "")) in {"issuer_master", "company_master"} for _, row in _rows_as_dicts(s) if _entity_id(row)}
    for source_idx, source in enumerate((legacy.get("entities", []), registry_existing.get("entities", []))):
        for item in source:
            entity_id = str(item.get("entity_id") or item.get("id") or "")
            if source_idx == 0 and ":" not in entity_id and item.get("ticker"):
                candidate = f"US:{item['ticker']}"
                if candidate in sheet_entity_ids:
                    entity_id = candidate
            if not entity_id:
                continue
            normalized = dict(item)
            original_id = str(item.get("entity_id") or item.get("id") or "")
            normalized["entity_id"] = entity_id
            normalized["id"] = entity_id
            if original_id and original_id != entity_id:
                normalized["legacy_ids"] = sorted(set((normalized.get("legacy_ids") or []) + [original_id]))
            normalized.setdefault("company_name", normalized.get("name"))
            normalized.setdefault("name", normalized.get("company_name"))
            normalized.setdefault("index_membership", [])
            normalized.setdefault("provenance", [])
            entities_by_id[entity_id] = _merge_entities(entities_by_id.get(entity_id, {"entity_id": entity_id, "id": entity_id}), normalized, conflicts)

    facts: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    facilities: list[dict[str, Any]] = []
    commitments: list[dict[str, Any]] = []
    backlog: list[dict[str, Any]] = []
    derived_source_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for sheet in sheets:
        name = sheet.get("name", "")
        normalized = normalize_header(name)
        rows = _rows_as_dicts(sheet)

        if normalized in {"issuer_master", "company_master"}:
            for source_row, row in rows:
                entity = _entity_from_row(row, snapshot, name, source_row)
                if entity:
                    entities_by_id[entity["entity_id"]] = _merge_entities(entities_by_id.get(entity["entity_id"], {"entity_id": entity["entity_id"], "id": entity["entity_id"]}), entity, conflicts)
                else:
                    invalid.append({"sheet": name, "row": source_row, "errors": ["missing entity_id"]})
        elif normalized in {"index_membership", "us_index_master"}:
            for source_row, row in rows:
                entity_id = _entity_id(row)
                if not entity_id:
                    continue
                p = _provenance(snapshot, name, source_row, row)
                current = entities_by_id.get(entity_id, {
                    "entity_id": entity_id, "id": entity_id,
                    "company_name": _get(row, "company_name", "security_name", "name"),
                    "name": _get(row, "company_name", "security_name", "name"),
                    "index_membership": [], "provenance": [],
                })
                shell = {
                    "entity_id": entity_id, "id": entity_id,
                    "index_membership": [{
                        "index_name": _get(row, "index_name", "index"),
                        "as_of_date": normalize_date(_get(row, "as_of_date")),
                        "security_ticker_or_code": _get(row, "security_ticker_or_code", "ticker", "security_code"),
                        "security_name": _get(row, "security_name"), "source_url": _source_url(row),
                        "verification_status": _get(row, "verification_status"),
                    }],
                    "provenance": [p],
                }
                entities_by_id[entity_id] = _merge_entities(current, shell, conflicts)
        elif normalized in {"financials", "annual_financials", "latest_capex"}:
            facts.extend(_fact_records(sheet, snapshot, invalid))
        elif normalized in {"capex_events", "capex_plans", "project_capex", "capex_projects"}:
            e, p = _event_and_project_records(sheet, snapshot, invalid)
            events.extend(e); projects.extend(p)
        elif normalized == "facilities":
            facilities.extend(_facility_records(sheet, snapshot, invalid))
        elif normalized in {"demand_commitments", "customer_commitments"}:
            commitments.extend(_commitment_records(sheet, snapshot, invalid))
        elif normalized == "main_customers":
            commitments.extend(_commitment_records(sheet, snapshot, invalid, default_type="major_customer"))
        elif normalized == "orders_backlog":
            backlog.extend(_backlog_records(sheet, snapshot, invalid))
        elif classify_sheet(name, (sheet.get("rows") or [[]])[0] if sheet.get("rows") else []) == "derived":
            derived_source_rows[name] = [{"source_row": n, **row} for n, row in rows]

    existing_sets = {
        "fact": load_jsonl(root / "data/canonical/facts.jsonl"),
        "event": load_jsonl(root / "data/canonical/events.jsonl"),
        "project": load_jsonl(root / "data/canonical/capex_projects.jsonl"),
        "facility": load_jsonl(root / "data/canonical/facilities.jsonl"),
        "commitment": load_jsonl(root / "data/canonical/customer_commitments.jsonl"),
        "backlog": load_jsonl(root / "data/canonical/orders_backlog.jsonl"),
    }
    incoming_sets = {"fact": facts, "event": events, "project": projects, "facility": facilities, "commitment": commitments, "backlog": backlog}
    final_sets: dict[str, list[dict[str, Any]]] = {}
    duplicate_count = 0
    for record_type, incoming in incoming_sets.items():
        merged, duplicates, found_conflicts = dedupe_or_conflict(record_type, existing_sets[record_type], incoming)
        final_sets[record_type] = merged
        duplicate_count += duplicates
        conflicts.extend(c.as_dict() for c in found_conflicts)

    for record_type, records in incoming_sets.items():
        for record in records:
            errs = validate_provenance(record)
            if errs:
                invalid.append({"record_type": record_type, "key": canonical_key(record_type, record), "errors": errs})

    enrichment = load_json(root / "data/registry/entity_enrichment.json", {"entities": []}) or {"entities": []}
    for item in enrichment.get("entities", []):
        entity_id = str(item.get("entity_id") or item.get("id") or "")
        if not entity_id:
            continue
        normalized = dict(item)
        normalized.setdefault("id", entity_id)
        normalized.setdefault("company_name", normalized.get("name"))
        normalized.setdefault("name", normalized.get("company_name"))
        normalized.setdefault("index_membership", [])
        normalized.setdefault("provenance", [])
        entities_by_id[entity_id] = _merge_entities(entities_by_id.get(entity_id, {"entity_id": entity_id, "id": entity_id}), normalized, conflicts)

    registry = {
        "schema_version": "semiconductor-entity-registry.v2",
        "source_policy": "Primary filings/IR outrank canonical existing records; imported spreadsheet values never overwrite conflicting primary data.",
        "entities": sorted(entities_by_id.values(), key=lambda x: str(x.get("entity_id"))),
    }
    classification = [{"sheet_name": s.get("name"), "classification": classify_sheet(s.get("name", ""), (s.get("rows") or [[]])[0] if s.get("rows") else []), "rows_read": max(len(s.get("rows") or []) - 1, 0)} for s in sheets]
    report = {
        "schema_version": "google-sheets-import-report.v1",
        "spreadsheet_id": snapshot.get("spreadsheet_id"), "source_sha256": snapshot.get("source_sha256"),
        "sheets_read": len(sheets), "rows_read": sum(max(len(s.get("rows") or []) - 1, 0) for s in sheets),
        "facts_created": len(facts), "events_created": len(events), "projects_created": len(projects),
        "facilities_created": len(facilities), "commitments_created": len(commitments),
        "backlog_rows_created": len(backlog), "duplicates": duplicate_count,
        "conflicts": len(conflicts), "invalid_rows": len(invalid), "sheet_classification": classification,
    }
    payload = {
        "registry": registry, "facts": final_sets["fact"], "events": final_sets["event"],
        "projects": final_sets["project"], "facilities": final_sets["facility"],
        "commitments": final_sets["commitment"], "backlog": final_sets["backlog"],
        "derived_source_rows": dict(derived_source_rows), "conflicts": conflicts,
        "invalid": invalid, "report": report,
    }
    return report, payload


def persist_import(snapshot: dict[str, Any], payload: dict[str, Any], *, root: Path = ROOT, raw_blob: bytes | None = None) -> None:
    digest = snapshot.get("source_sha256") or stable_hash(snapshot, 64)
    raw_dir = root / "data/raw/google_sheets_import" / str(snapshot.get("spreadsheet_id")) / str(digest)
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "source_manifest.json", {
        "schema_version": "google-sheets-raw-manifest.v1",
        "spreadsheet_id": snapshot.get("spreadsheet_id"), "source_name": snapshot.get("source_name"),
        "source_sha256": snapshot.get("source_sha256"),
        "source_binary_sha256": snapshot.get("source_binary_sha256"),
        "imported_at": snapshot.get("imported_at"),
        "sheet_names": [sheet.get("name") for sheet in snapshot.get("sheets", [])],
        "rows_read": sum(max(len(sheet.get("rows") or []) - 1, 0) for sheet in snapshot.get("sheets", [])),
        "native_archive": "source.xlsx",
    })
    if raw_blob is not None:
        (raw_dir / "source.xlsx").write_bytes(raw_blob)
    write_json(raw_dir / "import_report.json", payload["report"])
    write_json(root / "data/registry/entities.json", payload["registry"])
    write_jsonl(root / "data/canonical/facts.jsonl", payload["facts"])
    write_jsonl(root / "data/canonical/events.jsonl", payload["events"])
    write_jsonl(root / "data/canonical/capex_projects.jsonl", payload["projects"])
    write_jsonl(root / "data/canonical/facilities.jsonl", payload["facilities"])
    write_jsonl(root / "data/canonical/customer_commitments.jsonl", payload["commitments"])
    write_jsonl(root / "data/canonical/orders_backlog.jsonl", payload["backlog"])
    write_json(root / "data/derived/imported_sheet_derived_rows.json", payload["derived_source_rows"])
    if payload["conflicts"]:
        write_json(root / "data/conflicts/google_sheets_import_conflicts.json", payload["conflicts"])
    if payload["invalid"]:
        write_json(root / "data/conflicts/google_sheets_invalid_rows.json", payload["invalid"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Google Sheets CapEx DB into canonical Semiconductor Infrastructure Ledger.")
    parser.add_argument("--spreadsheet-id", default=DEFAULT_SPREADSHEET_ID)
    parser.add_argument("--xlsx", type=Path, help="Optional local XLSX source, used for archived workbook imports such as v0.4.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-conflicts", action="store_true", help="Persist non-conflicting records while reporting conflicts. Default is fail-closed.")
    args = parser.parse_args(argv)

    imported_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if args.xlsx:
        blob = args.xlsx.read_bytes()
        source_name = "google_sheets" if args.spreadsheet_id == DEFAULT_SPREADSHEET_ID else "xlsx_import"
    else:
        token = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN") or os.getenv("GOOGLE_SHEETS_BEARER_TOKEN")
        blob = fetch_google_sheet_xlsx(args.spreadsheet_id, token)
        source_name = "google_sheets"
    snapshot = parse_xlsx_bytes(blob, spreadsheet_id=args.spreadsheet_id, imported_at=imported_at, source_name=source_name)
    report, payload = build_import(snapshot, root=args.root)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))

    if report["conflicts"] and not args.allow_conflicts:
        if not args.dry_run:
            write_json(args.root / "data/conflicts/google_sheets_import_conflicts.json", payload["conflicts"])
        return 2
    if report["invalid_rows"]:
        if not args.dry_run:
            write_json(args.root / "data/conflicts/google_sheets_invalid_rows.json", payload["invalid"])
        return 3
    if not args.dry_run:
        persist_import(snapshot, payload, root=args.root, raw_blob=blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
