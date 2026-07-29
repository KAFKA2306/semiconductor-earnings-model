#!/usr/bin/env python3
"""Build a source-traceable financial database as JSON and SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).parents[1]
PRIMARY_PATH = ROOT / "site/public/api/v1/index.json"
RESEARCH_PATH = ROOT / "site/public/api/v2/semiconductor-research/index.json"
CATALOG_PATH = ROOT / "data/financial_db/metric_catalog.json"
MANUAL_PATH = ROOT / "data/financial_db/manual_observations.json"
OUTPUT_DIR = ROOT / "site/public/api/v3/financial-database"
JSON_PATH = OUTPUT_DIR / "index.json"
SQLITE_PATH = OUTPUT_DIR / "financial.db"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    key = "|".join("" if part is None else str(part) for part in parts)
    return f"{prefix}:{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}"


def normalize_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date: {value}") from exc


def period_type(period_start: str | None, period_end: str | None, fiscal_period: str | None) -> str:
    if period_start is None:
        return "instant" if period_end else "unknown"
    if fiscal_period == "FY":
        return "annual"
    if fiscal_period and fiscal_period.startswith("Q"):
        return "quarter"
    return "duration"


def build_entities(primary: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for company in primary.get("companies", []):
        entities[company["id"]] = {
            "id": company["id"],
            "type": "issuer",
            "name": company.get("name"),
            "ticker": company.get("ticker"),
            "cik": company.get("cik"),
            "class": company.get("class"),
            "role": company.get("role"),
            "peer_group_id": None,
            "availability": company.get("availability"),
        }
    for entity in research.get("database", {}).get("entities", []):
        current = entities.setdefault(entity["id"], {"id": entity["id"], "type": "issuer"})
        current.update({key: value for key, value in entity.items() if value is not None})
    return sorted(entities.values(), key=lambda item: item["id"])


def blank_observation() -> dict[str, Any]:
    return {
        "value": None,
        "value_low": None,
        "value_high": None,
        "currency": None,
        "period_start": None,
        "period_end": None,
        "period_type": "unknown",
        "fiscal_year": None,
        "fiscal_period": None,
        "scope": "consolidated",
        "segment": None,
        "geography": None,
        "as_of": None,
        "observed_at": None,
        "filed_at": None,
        "revision": 0,
        "source_name": None,
        "source_api_url": None,
        "document_form": None,
        "accession": None,
        "source_tag": None,
        "model_id": None,
        "formula": None,
        "assumptions": [],
        "evidence_ids": [],
        "supersedes_id": None,
        "quality_flags": [],
    }


def research_observations(research: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fact in research.get("database", {}).get("reported_facts", []):
        start = normalize_date(fact.get("period_start"))
        end = normalize_date(fact.get("period_end"))
        rows.append(
            {
                **blank_observation(),
                "id": fact["id"],
                "entity_id": fact["issuer_id"],
                "concept_id": fact["concept_id"],
                "value_type": "actual",
                "value": fact.get("value"),
                "unit": fact.get("unit"),
                "currency": fact.get("unit") if fact.get("unit") in {"USD", "JPY", "EUR", "KRW", "TWD"} else None,
                "period_start": start,
                "period_end": end,
                "period_type": fact.get("period_type") or period_type(start, end, None),
                "as_of": end,
                "source_tier": "primary_regulatory",
                "source_name": "SEC EDGAR",
                "source_url": fact.get("source_url"),
                "document_form": fact.get("form"),
                "accession": fact.get("accession"),
                "source_tag": fact.get("xbrl_tag"),
            }
        )
    return rows


def primary_observations(primary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for company in primary.get("companies", []):
        for fact in company.get("facts", []):
            start = normalize_date(fact.get("period_start"))
            end = normalize_date(fact.get("period_end"))
            fiscal_period = fact.get("fiscal_period")
            source_url = fact.get("source_url")
            rows.append(
                {
                    **blank_observation(),
                    "id": stable_id(
                        "observation",
                        [
                            company["id"],
                            fact.get("kind"),
                            start,
                            end,
                            fiscal_period,
                            fact.get("unit"),
                            source_url,
                            fact.get("accession"),
                        ],
                    ),
                    "entity_id": company["id"],
                    "concept_id": fact.get("kind"),
                    "value_type": "actual",
                    "value": fact.get("reported_value"),
                    "unit": fact.get("unit"),
                    "currency": fact.get("unit") if fact.get("unit") in {"USD", "JPY", "EUR", "KRW", "TWD"} else None,
                    "period_start": start,
                    "period_end": end,
                    "period_type": period_type(start, end, fiscal_period),
                    "fiscal_year": fact.get("fiscal_year"),
                    "fiscal_period": fiscal_period,
                    "as_of": end,
                    "observed_at": fact.get("retrieved_at"),
                    "filed_at": normalize_date(fact.get("filed")),
                    "source_tier": "primary_regulatory",
                    "source_name": "SEC EDGAR",
                    "source_url": source_url,
                    "source_api_url": fact.get("source_api_url"),
                    "document_form": fact.get("form"),
                    "accession": fact.get("accession"),
                    "source_tag": fact.get("fact_tag"),
                }
            )
    return rows


def manual_observations(
    manual: dict[str, Any], catalog: dict[str, Any], entity_ids: set[str]
) -> list[dict[str, Any]]:
    required = set(manual["policy"]["required_fields"])
    allowed_types = set(catalog["value_types"])
    allowed_tiers = set(catalog["source_tiers"])
    concept_ids = {item["id"] for item in catalog["concepts"]}
    rows: list[dict[str, Any]] = []
    for raw in manual.get("observations", []):
        missing = sorted(field for field in required if raw.get(field) in (None, ""))
        if missing:
            raise ValueError(f"Manual observation {raw.get('id')} missing {missing}")
        if raw["entity_id"] not in entity_ids:
            raise ValueError(f"Unknown entity_id: {raw['entity_id']}")
        if raw["concept_id"] not in concept_ids:
            raise ValueError(f"Unknown concept_id: {raw['concept_id']}")
        if raw["value_type"] not in allowed_types:
            raise ValueError(f"Invalid value_type: {raw['value_type']}")
        if raw["source_tier"] not in allowed_tiers:
            raise ValueError(f"Invalid source_tier: {raw['source_tier']}")
        if not str(raw["source_url"]).startswith("https://"):
            raise ValueError(f"source_url must be HTTPS: {raw['source_url']}")
        row = {**blank_observation(), **raw}
        row["period_start"] = normalize_date(row.get("period_start"))
        row["period_end"] = normalize_date(row.get("period_end"))
        row["as_of"] = normalize_date(row.get("as_of"))
        if row["period_type"] == "unknown":
            row["period_type"] = period_type(
                row["period_start"], row["period_end"], row.get("fiscal_period")
            )
        has_value = any(row.get(field) is not None for field in ("value", "value_low", "value_high"))
        if not has_value:
            raise ValueError(f"Manual observation requires a point or range: {row['id']}")
        if row["value_type"] in {"internal_estimate", "scenario"} and not row.get("model_id"):
            raise ValueError(f"{row['value_type']} requires model_id: {row['id']}")
        if row["value_type"] == "analyst_consensus" and not row.get("source_name"):
            raise ValueError(f"analyst_consensus requires source_name: {row['id']}")
        rows.append(row)
    return rows


def semantic_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("entity_id"),
        row.get("concept_id"),
        row.get("value_type"),
        row.get("period_start"),
        row.get("period_end"),
        row.get("fiscal_period"),
        row.get("scope"),
        row.get("segment"),
        row.get("geography"),
        row.get("unit"),
        row.get("source_url"),
        row.get("accession"),
        row.get("revision", 0),
    )


def deduplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = semantic_key(row)
        current = selected.get(key)
        if current is None:
            selected[key] = row
            continue
        row_score = sum(value not in (None, "", [], {}) for value in row.values())
        current_score = sum(value not in (None, "", [], {}) for value in current.values())
        if row_score > current_score:
            selected[key] = row
    result = sorted(
        selected.values(),
        key=lambda item: (
            item["entity_id"],
            item.get("period_end") or "",
            item["concept_id"],
            item["id"],
        ),
    )
    ids = [row["id"] for row in result]
    if len(ids) != len(set(ids)):
        raise ValueError("Observation IDs are not unique")
    return result


def build_sources(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for row in observations:
        url = row.get("source_url")
        if not url:
            continue
        source_id = stable_id("source", [url])
        sources.setdefault(
            source_id,
            {
                "id": source_id,
                "name": row.get("source_name"),
                "tier": row.get("source_tier"),
                "url": url,
                "api_url": row.get("source_api_url"),
                "document_form": row.get("document_form"),
                "accession": row.get("accession"),
            },
        )
        row["source_id"] = source_id
    return sorted(sources.values(), key=lambda item: item["id"])


def build_audit(
    entities: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    entity_ids = {item["id"] for item in entities}
    concept_ids = {item["id"] for item in catalog["concepts"]}
    issues: list[dict[str, Any]] = []
    latest: dict[str, str] = {}
    for row in observations:
        if row["entity_id"] not in entity_ids:
            issues.append({"severity": "error", "code": "unknown_entity", "record_id": row["id"]})
        if row["concept_id"] not in concept_ids:
            issues.append(
                {
                    "severity": "warning",
                    "code": "uncatalogued_concept",
                    "record_id": row["id"],
                    "concept_id": row["concept_id"],
                }
            )
        if not row.get("source_url"):
            issues.append({"severity": "error", "code": "missing_source_url", "record_id": row["id"]})
        end = row.get("period_end")
        if end and (row["entity_id"] not in latest or end > latest[row["entity_id"]]):
            latest[row["entity_id"]] = end

    counts = Counter(row["entity_id"] for row in observations)
    actual_counts = Counter(
        row["entity_id"] for row in observations if row["value_type"] == "actual"
    )
    coverage: list[dict[str, Any]] = []
    for entity in entities:
        latest_period = latest.get(entity["id"])
        age_days = (today - date.fromisoformat(latest_period)).days if latest_period else None
        stale = age_days is None or age_days > 550
        if stale and entity.get("class") == "public":
            issues.append(
                {
                    "severity": "warning",
                    "code": "stale_or_missing_public_entity",
                    "entity_id": entity["id"],
                    "age_days": age_days,
                }
            )
        coverage.append(
            {
                "entity_id": entity["id"],
                "observation_count": counts[entity["id"]],
                "actual_count": actual_counts[entity["id"]],
                "latest_period_end": latest_period,
                "age_days": age_days,
                "status": "stale" if stale else "current",
            }
        )

    error_count = sum(item["severity"] == "error" for item in issues)
    return {
        "status": "PASS" if error_count == 0 else "FAIL",
        "generated_date": today.isoformat(),
        "entity_coverage": coverage,
        "issues": issues,
        "counts": {
            "entities": len(entities),
            "observations": len(observations),
            "metrics": len(metrics),
            "actual_observations": sum(row["value_type"] == "actual" for row in observations),
            "manual_observations": sum(
                row.get("source_tier") != "primary_regulatory" for row in observations
            ),
            "concepts_populated": len({row["concept_id"] for row in observations}),
            "concepts_catalogued": len(concept_ids),
            "errors": error_count,
            "warnings": sum(item["severity"] == "warning" for item in issues),
        },
    }


def build_views(
    entities: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_actuals: dict[tuple[str, str], dict[str, Any]] = {}
    for row in observations:
        if row["value_type"] != "actual":
            continue
        key = (row["entity_id"], row["concept_id"])
        current = latest_actuals.get(key)
        ordering = (
            row.get("period_end") or "",
            row.get("filed_at") or "",
            row.get("revision", 0),
        )
        current_ordering = (
            current.get("period_end") or "",
            current.get("filed_at") or "",
            current.get("revision", 0),
        ) if current else None
        if current is None or ordering > current_ordering:
            latest_actuals[key] = row

    latest_metrics: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    for row in metrics:
        key = (row.get("issuer_id"), row.get("metric_id"))
        current = latest_metrics.get(key)
        if current is None or (row.get("period_end") or "") > (current.get("period_end") or ""):
            latest_metrics[key] = row

    return {
        "latest_actuals": sorted(
            latest_actuals.values(), key=lambda item: (item["entity_id"], item["concept_id"])
        ),
        "latest_metrics": sorted(
            latest_metrics.values(),
            key=lambda item: (item.get("issuer_id") or "", item.get("metric_id") or ""),
        ),
        "entity_lookup": {
            item["id"]: {
                "name": item.get("name"),
                "ticker": item.get("ticker"),
                "role": item.get("role"),
            }
            for item in entities
        },
        "recipes": [
            {
                "id": "latest_company_snapshot",
                "inputs": ["entity_id"],
                "uses": ["latest_actuals", "latest_metrics", "evaluations"],
            },
            {
                "id": "earnings_comparison",
                "inputs": ["entity_id", "period_end"],
                "comparisons": [
                    "yoy",
                    "qoq",
                    "vs_company_guidance",
                    "vs_analyst_consensus",
                ],
            },
            {
                "id": "capex_roi_review",
                "inputs": ["entity_id"],
                "uses": [
                    "capital_expenditures",
                    "operating_cash_flow",
                    "free_cash_flow",
                    "revenue",
                    "depreciation_amortization",
                    "remaining_performance_obligations",
                ],
            },
            {
                "id": "semiconductor_cycle_review",
                "inputs": ["entity_id"],
                "uses": [
                    "revenue",
                    "operating_margin",
                    "inventory",
                    "memory_asp_change",
                    "bit_shipments_change",
                    "fab_utilization",
                    "backlog",
                ],
            },
            {
                "id": "downside_resilience",
                "inputs": ["entity_id", "scenario_id"],
                "uses": ["liquid_reserve", "total_debt", "free_cash_flow", "evaluations"],
            },
        ],
    }


def write_sqlite(payload: dict[str, Any]) -> None:
    if SQLITE_PATH.exists():
        SQLITE_PATH.unlink()
    connection = sqlite3.connect(SQLITE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE entities (
          id TEXT PRIMARY KEY, name TEXT, ticker TEXT, cik TEXT, class TEXT,
          role TEXT, peer_group_id TEXT, availability TEXT, raw_json TEXT NOT NULL
        );
        CREATE TABLE concepts (
          id TEXT PRIMARY KEY, statement TEXT, default_unit TEXT, aggregation TEXT,
          status TEXT, formula TEXT, raw_json TEXT NOT NULL
        );
        CREATE TABLE sources (
          id TEXT PRIMARY KEY, name TEXT, tier TEXT, url TEXT NOT NULL, api_url TEXT,
          document_form TEXT, accession TEXT, raw_json TEXT NOT NULL
        );
        CREATE TABLE observations (
          id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, concept_id TEXT NOT NULL,
          value_type TEXT NOT NULL, value REAL, value_low REAL, value_high REAL,
          unit TEXT, currency TEXT, period_start TEXT, period_end TEXT, period_type TEXT,
          fiscal_year INTEGER, fiscal_period TEXT, scope TEXT, segment TEXT, geography TEXT,
          as_of TEXT, observed_at TEXT, filed_at TEXT, revision INTEGER NOT NULL,
          source_id TEXT, source_url TEXT NOT NULL, raw_json TEXT NOT NULL,
          FOREIGN KEY(entity_id) REFERENCES entities(id),
          FOREIGN KEY(source_id) REFERENCES sources(id)
        );
        CREATE TABLE metrics (
          id TEXT PRIMARY KEY, entity_id TEXT, metric_id TEXT, value REAL, unit TEXT,
          period_end TEXT, formula TEXT, raw_json TEXT NOT NULL
        );
        CREATE TABLE evaluations (
          id TEXT PRIMARY KEY, entity_id TEXT, rule_id TEXT, value REAL, result TEXT,
          raw_json TEXT NOT NULL
        );
        CREATE TABLE evidence_edges (
          from_id TEXT NOT NULL, relationship TEXT NOT NULL, to_id TEXT NOT NULL,
          raw_json TEXT NOT NULL
        );
        CREATE TABLE audit_issues (
          sequence INTEGER PRIMARY KEY, severity TEXT, code TEXT, entity_id TEXT,
          record_id TEXT, raw_json TEXT NOT NULL
        );
        CREATE INDEX observations_entity_concept_period
          ON observations(entity_id, concept_id, period_end);
        CREATE INDEX observations_value_type ON observations(value_type);
        CREATE INDEX metrics_entity_metric ON metrics(entity_id, metric_id);
        CREATE INDEX evaluations_entity_rule ON evaluations(entity_id, rule_id);
        """
    )
    for row in payload["entities"]:
        connection.execute(
            "INSERT INTO entities VALUES (?,?,?,?,?,?,?,?,?)",
            (
                row["id"], row.get("name"), row.get("ticker"), row.get("cik"),
                row.get("class"), row.get("role"), row.get("peer_group_id"),
                row.get("availability"), json.dumps(row, ensure_ascii=False, sort_keys=True),
            ),
        )
    for row in payload["catalog"]["concepts"]:
        connection.execute(
            "INSERT INTO concepts VALUES (?,?,?,?,?,?,?)",
            (
                row["id"], row.get("statement"), row.get("default_unit"),
                row.get("aggregation"), row.get("status"), row.get("formula"),
                json.dumps(row, ensure_ascii=False, sort_keys=True),
            ),
        )
    for row in payload["sources"]:
        connection.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
            (
                row["id"], row.get("name"), row.get("tier"), row["url"],
                row.get("api_url"), row.get("document_form"), row.get("accession"),
                json.dumps(row, ensure_ascii=False, sort_keys=True),
            ),
        )
    for row in payload["observations"]:
        connection.execute(
            "INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["id"], row["entity_id"], row["concept_id"], row["value_type"],
                row.get("value"), row.get("value_low"), row.get("value_high"),
                row.get("unit"), row.get("currency"), row.get("period_start"),
                row.get("period_end"), row.get("period_type"), row.get("fiscal_year"),
                row.get("fiscal_period"), row.get("scope"), row.get("segment"),
                row.get("geography"), row.get("as_of"), row.get("observed_at"),
                row.get("filed_at"), row.get("revision", 0), row.get("source_id"),
                row.get("source_url"), json.dumps(row, ensure_ascii=False, sort_keys=True),
            ),
        )
    for row in payload["derived_metrics"]:
        connection.execute(
            "INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?)",
            (
                row["id"], row.get("issuer_id"), row.get("metric_id"), row.get("value"),
                row.get("unit"), row.get("period_end"), row.get("formula"),
                json.dumps(row, ensure_ascii=False, sort_keys=True),
            ),
        )
    for row in payload["evaluations"]:
        connection.execute(
            "INSERT INTO evaluations VALUES (?,?,?,?,?,?)",
            (
                row["id"], row.get("issuer_id"), row.get("rule_id"), row.get("value"),
                row.get("result"), json.dumps(row, ensure_ascii=False, sort_keys=True),
            ),
        )
    for row in payload["evidence_edges"]:
        connection.execute(
            "INSERT INTO evidence_edges VALUES (?,?,?,?)",
            (
                row.get("from_id"), row.get("relationship"), row.get("to_id"),
                json.dumps(row, ensure_ascii=False, sort_keys=True),
            ),
        )
    for sequence, row in enumerate(payload["audit"]["issues"], start=1):
        connection.execute(
            "INSERT INTO audit_issues VALUES (?,?,?,?,?,?)",
            (
                sequence, row.get("severity"), row.get("code"), row.get("entity_id"),
                row.get("record_id"), json.dumps(row, ensure_ascii=False, sort_keys=True),
            ),
        )
    connection.commit()
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    connection.close()
    if integrity != "ok":
        raise AssertionError(f"SQLite integrity check failed: {integrity}")


def main() -> None:
    primary = load(PRIMARY_PATH)
    research = load(RESEARCH_PATH)
    catalog = load(CATALOG_PATH)
    manual = load(MANUAL_PATH)
    entities = build_entities(primary, research)
    entity_ids = {item["id"] for item in entities}
    observations = deduplicate(
        research_observations(research)
        + primary_observations(primary)
        + manual_observations(manual, catalog, entity_ids)
    )
    sources = build_sources(observations)
    metrics = research.get("database", {}).get("derived_metrics", [])
    evaluations = research.get("database", {}).get("evaluations", [])
    evidence_edges = research.get("database", {}).get("evidence_edges", [])
    audit = build_audit(entities, observations, metrics, catalog)
    core = {
        "schema_version": "financial-database.v3",
        "source_api_hashes": {
            "primary": primary.get("snapshot_hash") or primary.get("content_hash"),
            "semiconductor_research": research.get("content_hash"),
            "metric_catalog": canonical_hash(catalog),
            "manual_observations": canonical_hash(manual),
        },
        "catalog": catalog,
        "entities": entities,
        "sources": sources,
        "observations": observations,
        "derived_metrics": metrics,
        "evaluations": evaluations,
        "evidence_edges": evidence_edges,
        "views": build_views(entities, observations, metrics),
        "audit": audit,
    }
    payload = {
        **core,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": canonical_hash(core),
        "sqlite_path": "financial.db",
    }
    if audit["status"] != "PASS":
        raise AssertionError(f"Financial database audit failed: {audit['issues']}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    write_sqlite(payload)
    print(
        "financial_database_v3="
        f"entities={len(entities)} observations={len(observations)} "
        f"metrics={len(metrics)} sources={len(sources)} "
        f"warnings={audit['counts']['warnings']} hash={payload['content_hash']}"
    )


if __name__ == "__main__":
    main()
