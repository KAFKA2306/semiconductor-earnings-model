#!/usr/bin/env python3
"""Build a deterministic analytical star schema from Financial Database v3."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
INPUT_PATH = ROOT / "site/public/api/v3/financial-database/index.json"
OUTPUT_PATH = ROOT / "site/public/api/v3/financial-database/star-schema.json"
SQLITE_PATH = ROOT / "site/public/api/v3/financial-database/financial.db"
SCHEMA_VERSION = "financial-star-schema.v1"


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def surrogate_key(namespace: str, *parts: Any) -> int:
    raw = namespace + "|" + "|".join("" if part is None else str(part) for part in parts)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:15], 16)


def period_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("period_start"),
        row.get("period_end"),
        row.get("period_type") or "unknown",
        row.get("fiscal_year"),
        row.get("fiscal_period"),
    )


def scope_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("scope") or "unknown",
        row.get("segment"),
        row.get("geography"),
    )


def register(
    table: dict[int, dict[str, Any]],
    key: int,
    row: dict[str, Any],
    natural_identity: Any,
) -> None:
    current = table.get(key)
    if current is not None and current != row:
        raise ValueError(f"surrogate key collision for {natural_identity!r}")
    table[key] = row


def build_star(financial: dict[str, Any]) -> dict[str, Any]:
    if financial.get("schema_version") != "financial-database.v3":
        raise ValueError(f"unsupported source schema: {financial.get('schema_version')!r}")

    dims: dict[str, dict[int, dict[str, Any]]] = {
        "company": {},
        "metric": {},
        "period": {},
        "source": {},
        "value_type": {},
        "scope": {},
        "rule": {},
    }

    for row in financial.get("entities", []):
        key = surrogate_key("company", row["id"])
        register(
            dims["company"],
            key,
            {
                "company_key": key,
                "company_id": row["id"],
                "name": row.get("name"),
                "ticker": row.get("ticker"),
                "cik": row.get("cik"),
                "class": row.get("class"),
                "role": row.get("role"),
                "peer_group_id": row.get("peer_group_id"),
                "availability": row.get("availability"),
            },
            row["id"],
        )

    metric_rows: dict[str, dict[str, Any]] = {
        row["id"]: dict(row) for row in financial.get("catalog", {}).get("concepts", [])
    }
    for row in financial.get("observations", []):
        metric_rows.setdefault(
            row["concept_id"],
            {
                "id": row["concept_id"],
                "statement": "uncatalogued",
                "default_unit": row.get("unit"),
                "aggregation": "unknown",
                "status": "observed_uncatalogued",
                "formula": None,
            },
        )
    for row in financial.get("derived_metrics", []):
        metric_id = row.get("metric_id")
        if metric_id:
            metric_rows.setdefault(
                metric_id,
                {
                    "id": metric_id,
                    "statement": "derived",
                    "default_unit": row.get("unit"),
                    "aggregation": "derived",
                    "status": "derived",
                    "formula": row.get("formula"),
                },
            )
    for metric_id, row in sorted(metric_rows.items()):
        key = surrogate_key("metric", metric_id)
        register(
            dims["metric"],
            key,
            {
                "metric_key": key,
                "metric_id": metric_id,
                "statement": row.get("statement"),
                "default_unit": row.get("default_unit"),
                "aggregation": row.get("aggregation"),
                "status": row.get("status"),
                "formula": row.get("formula"),
            },
            metric_id,
        )

    source_by_id = {row["id"]: row for row in financial.get("sources", [])}
    for source_id, row in sorted(source_by_id.items()):
        key = surrogate_key("source", source_id)
        register(
            dims["source"],
            key,
            {
                "source_key": key,
                "source_id": source_id,
                "name": row.get("name"),
                "tier": row.get("tier"),
                "url": row.get("url"),
                "api_url": row.get("api_url"),
                "document_form": row.get("document_form"),
                "accession": row.get("accession"),
            },
            source_id,
        )

    value_types = set(financial.get("catalog", {}).get("value_types", []))
    value_types.update(
        str(row.get("value_type"))
        for row in financial.get("observations", [])
        if row.get("value_type")
    )
    for value_type in sorted(value_types):
        key = surrogate_key("value_type", value_type)
        register(
            dims["value_type"],
            key,
            {
                "value_type_key": key,
                "value_type": value_type,
                "is_reported": value_type == "actual",
                "is_forward_looking": value_type
                in {"company_guidance", "analyst_consensus", "internal_estimate", "scenario"},
            },
            value_type,
        )

    all_period_rows = [
        *financial.get("observations", []),
        *financial.get("derived_metrics", []),
        *financial.get("evaluations", []),
    ]
    for row in all_period_rows:
        identity = period_identity(row)
        key = surrogate_key("period", *identity)
        register(
            dims["period"],
            key,
            {
                "period_key": key,
                "period_start": identity[0],
                "period_end": identity[1],
                "period_type": identity[2],
                "fiscal_year": identity[3],
                "fiscal_period": identity[4],
            },
            identity,
        )

    for row in financial.get("observations", []):
        identity = scope_identity(row)
        key = surrogate_key("scope", *identity)
        register(
            dims["scope"],
            key,
            {
                "scope_key": key,
                "scope": identity[0],
                "segment": identity[1],
                "geography": identity[2],
            },
            identity,
        )

    for row in financial.get("evaluations", []):
        rule_id = row.get("rule_id")
        if not rule_id:
            continue
        key = surrogate_key("rule", rule_id)
        register(
            dims["rule"],
            key,
            {"rule_key": key, "rule_id": rule_id},
            rule_id,
        )

    company_keys = {row["company_id"]: row["company_key"] for row in dims["company"].values()}
    metric_keys = {row["metric_id"]: row["metric_key"] for row in dims["metric"].values()}
    source_keys = {row["source_id"]: row["source_key"] for row in dims["source"].values()}
    value_type_keys = {
        row["value_type"]: row["value_type_key"] for row in dims["value_type"].values()
    }
    period_keys = {
        (
            row["period_start"],
            row["period_end"],
            row["period_type"],
            row["fiscal_year"],
            row["fiscal_period"],
        ): row["period_key"]
        for row in dims["period"].values()
    }
    scope_keys = {
        (row["scope"], row["segment"], row["geography"]): row["scope_key"]
        for row in dims["scope"].values()
    }
    rule_keys = {row["rule_id"]: row["rule_key"] for row in dims["rule"].values()}

    facts_observation = []
    for row in financial.get("observations", []):
        source_id = row.get("source_id")
        if row["entity_id"] not in company_keys:
            raise ValueError(f"observation references unknown company: {row['id']}")
        if row["concept_id"] not in metric_keys:
            raise ValueError(f"observation references unknown metric: {row['id']}")
        if source_id not in source_keys:
            raise ValueError(f"observation references unknown source: {row['id']}")
        if row["value_type"] not in value_type_keys:
            raise ValueError(f"observation references unknown value type: {row['id']}")
        facts_observation.append(
            {
                "observation_key": surrogate_key("observation", row["id"]),
                "observation_id": row["id"],
                "company_key": company_keys[row["entity_id"]],
                "metric_key": metric_keys[row["concept_id"]],
                "period_key": period_keys[period_identity(row)],
                "source_key": source_keys[source_id],
                "value_type_key": value_type_keys[row["value_type"]],
                "scope_key": scope_keys[scope_identity(row)],
                "value": row.get("value"),
                "value_low": row.get("value_low"),
                "value_high": row.get("value_high"),
                "unit": row.get("unit"),
                "currency": row.get("currency"),
                "as_of": row.get("as_of"),
                "observed_at": row.get("observed_at"),
                "filed_at": row.get("filed_at"),
                "revision": row.get("revision", 0),
            }
        )

    facts_metric = []
    for row in financial.get("derived_metrics", []):
        issuer_id = row.get("issuer_id")
        metric_id = row.get("metric_id")
        if issuer_id not in company_keys or metric_id not in metric_keys:
            raise ValueError(f"derived metric has unresolved dimension: {row.get('id')}")
        facts_metric.append(
            {
                "derived_metric_key": surrogate_key("derived_metric", row["id"]),
                "derived_metric_id": row["id"],
                "company_key": company_keys[issuer_id],
                "metric_key": metric_keys[metric_id],
                "period_key": period_keys[period_identity(row)],
                "value": row.get("value"),
                "unit": row.get("unit"),
                "formula": row.get("formula"),
            }
        )

    facts_evaluation = []
    for row in financial.get("evaluations", []):
        issuer_id = row.get("issuer_id")
        rule_id = row.get("rule_id")
        if issuer_id not in company_keys or rule_id not in rule_keys:
            raise ValueError(f"evaluation has unresolved dimension: {row.get('id')}")
        facts_evaluation.append(
            {
                "evaluation_key": surrogate_key("evaluation", row["id"]),
                "evaluation_id": row["id"],
                "company_key": company_keys[issuer_id],
                "rule_key": rule_keys[rule_id],
                "period_key": period_keys[period_identity(row)],
                "value": row.get("value"),
                "result": row.get("result"),
            }
        )

    facts_evidence = []
    for row in financial.get("evidence_edges", []):
        edge_identity = (
            row.get("from_id"),
            row.get("relationship"),
            row.get("to_id"),
        )
        facts_evidence.append(
            {
                "evidence_edge_key": surrogate_key("evidence_edge", *edge_identity),
                "from_id": edge_identity[0],
                "relationship": edge_identity[1],
                "to_id": edge_identity[2],
            }
        )

    dimensions = {
        "dim_company": sorted(dims["company"].values(), key=lambda row: row["company_key"]),
        "dim_metric": sorted(dims["metric"].values(), key=lambda row: row["metric_key"]),
        "dim_period": sorted(dims["period"].values(), key=lambda row: row["period_key"]),
        "dim_source": sorted(dims["source"].values(), key=lambda row: row["source_key"]),
        "dim_value_type": sorted(
            dims["value_type"].values(), key=lambda row: row["value_type_key"]
        ),
        "dim_scope": sorted(dims["scope"].values(), key=lambda row: row["scope_key"]),
        "dim_rule": sorted(dims["rule"].values(), key=lambda row: row["rule_key"]),
    }
    facts = {
        "fact_observation": sorted(
            facts_observation, key=lambda row: row["observation_key"]
        ),
        "fact_derived_metric": sorted(
            facts_metric, key=lambda row: row["derived_metric_key"]
        ),
        "fact_evaluation": sorted(
            facts_evaluation, key=lambda row: row["evaluation_key"]
        ),
        "fact_evidence_edge": sorted(
            facts_evidence, key=lambda row: row["evidence_edge_key"]
        ),
    }

    core = {
        "schema_version": SCHEMA_VERSION,
        "source_schema_version": financial["schema_version"],
        "source_content_hash": financial.get("content_hash"),
        "grain": {
            "fact_observation": "one source-traceable semantic observation",
            "fact_derived_metric": "one formula-backed derived metric for one issuer and period",
            "fact_evaluation": "one explicit rule evaluation for one issuer",
            "fact_evidence_edge": "one lineage relationship between two natural record identifiers",
        },
        "dimensions": dimensions,
        "facts": facts,
        "audit": {
            "status": "PASS",
            "counts": {
                "source_observations": len(financial.get("observations", [])),
                "fact_observations": len(facts["fact_observation"]),
                "source_derived_metrics": len(financial.get("derived_metrics", [])),
                "fact_derived_metrics": len(facts["fact_derived_metric"]),
                "source_evaluations": len(financial.get("evaluations", [])),
                "fact_evaluations": len(facts["fact_evaluation"]),
                "source_evidence_edges": len(financial.get("evidence_edges", [])),
                "fact_evidence_edges": len(facts["fact_evidence_edge"]),
                **{name: len(rows) for name, rows in dimensions.items()},
            },
        },
    }
    return {**core, "content_hash": canonical_hash(core)}


def write_sqlite(star: dict[str, Any]) -> None:
    connection = sqlite3.connect(SQLITE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        DROP TABLE IF EXISTS fact_evidence_edge;
        DROP TABLE IF EXISTS fact_evaluation;
        DROP TABLE IF EXISTS fact_derived_metric;
        DROP TABLE IF EXISTS fact_observation;
        DROP TABLE IF EXISTS dim_rule;
        DROP TABLE IF EXISTS dim_scope;
        DROP TABLE IF EXISTS dim_value_type;
        DROP TABLE IF EXISTS dim_source;
        DROP TABLE IF EXISTS dim_period;
        DROP TABLE IF EXISTS dim_metric;
        DROP TABLE IF EXISTS dim_company;

        CREATE TABLE dim_company (
          company_key INTEGER PRIMARY KEY,
          company_id TEXT NOT NULL UNIQUE,
          name TEXT, ticker TEXT, cik TEXT, class TEXT, role TEXT,
          peer_group_id TEXT, availability TEXT
        );
        CREATE TABLE dim_metric (
          metric_key INTEGER PRIMARY KEY,
          metric_id TEXT NOT NULL UNIQUE,
          statement TEXT, default_unit TEXT, aggregation TEXT, status TEXT, formula TEXT
        );
        CREATE TABLE dim_period (
          period_key INTEGER PRIMARY KEY,
          period_start TEXT, period_end TEXT, period_type TEXT NOT NULL,
          fiscal_year INTEGER, fiscal_period TEXT,
          UNIQUE(period_start, period_end, period_type, fiscal_year, fiscal_period)
        );
        CREATE TABLE dim_source (
          source_key INTEGER PRIMARY KEY,
          source_id TEXT NOT NULL UNIQUE,
          name TEXT, tier TEXT, url TEXT, api_url TEXT, document_form TEXT, accession TEXT
        );
        CREATE TABLE dim_value_type (
          value_type_key INTEGER PRIMARY KEY,
          value_type TEXT NOT NULL UNIQUE,
          is_reported INTEGER NOT NULL,
          is_forward_looking INTEGER NOT NULL
        );
        CREATE TABLE dim_scope (
          scope_key INTEGER PRIMARY KEY,
          scope TEXT NOT NULL, segment TEXT, geography TEXT,
          UNIQUE(scope, segment, geography)
        );
        CREATE TABLE dim_rule (
          rule_key INTEGER PRIMARY KEY,
          rule_id TEXT NOT NULL UNIQUE
        );

        CREATE TABLE fact_observation (
          observation_key INTEGER PRIMARY KEY,
          observation_id TEXT NOT NULL UNIQUE,
          company_key INTEGER NOT NULL,
          metric_key INTEGER NOT NULL,
          period_key INTEGER NOT NULL,
          source_key INTEGER NOT NULL,
          value_type_key INTEGER NOT NULL,
          scope_key INTEGER NOT NULL,
          value REAL, value_low REAL, value_high REAL,
          unit TEXT, currency TEXT, as_of TEXT, observed_at TEXT, filed_at TEXT,
          revision INTEGER NOT NULL,
          FOREIGN KEY(company_key) REFERENCES dim_company(company_key),
          FOREIGN KEY(metric_key) REFERENCES dim_metric(metric_key),
          FOREIGN KEY(period_key) REFERENCES dim_period(period_key),
          FOREIGN KEY(source_key) REFERENCES dim_source(source_key),
          FOREIGN KEY(value_type_key) REFERENCES dim_value_type(value_type_key),
          FOREIGN KEY(scope_key) REFERENCES dim_scope(scope_key)
        );
        CREATE TABLE fact_derived_metric (
          derived_metric_key INTEGER PRIMARY KEY,
          derived_metric_id TEXT NOT NULL UNIQUE,
          company_key INTEGER NOT NULL,
          metric_key INTEGER NOT NULL,
          period_key INTEGER NOT NULL,
          value REAL, unit TEXT, formula TEXT,
          FOREIGN KEY(company_key) REFERENCES dim_company(company_key),
          FOREIGN KEY(metric_key) REFERENCES dim_metric(metric_key),
          FOREIGN KEY(period_key) REFERENCES dim_period(period_key)
        );
        CREATE TABLE fact_evaluation (
          evaluation_key INTEGER PRIMARY KEY,
          evaluation_id TEXT NOT NULL UNIQUE,
          company_key INTEGER NOT NULL,
          rule_key INTEGER NOT NULL,
          period_key INTEGER NOT NULL,
          value REAL, result TEXT,
          FOREIGN KEY(company_key) REFERENCES dim_company(company_key),
          FOREIGN KEY(rule_key) REFERENCES dim_rule(rule_key),
          FOREIGN KEY(period_key) REFERENCES dim_period(period_key)
        );
        CREATE TABLE fact_evidence_edge (
          evidence_edge_key INTEGER PRIMARY KEY,
          from_id TEXT NOT NULL,
          relationship TEXT NOT NULL,
          to_id TEXT NOT NULL,
          UNIQUE(from_id, relationship, to_id)
        );

        CREATE INDEX fact_observation_company_metric_period
          ON fact_observation(company_key, metric_key, period_key);
        CREATE INDEX fact_observation_source
          ON fact_observation(source_key);
        CREATE INDEX fact_observation_value_type
          ON fact_observation(value_type_key);
        CREATE INDEX fact_derived_metric_company_metric_period
          ON fact_derived_metric(company_key, metric_key, period_key);
        CREATE INDEX fact_evaluation_company_rule
          ON fact_evaluation(company_key, rule_key);
        """
    )

    for table_name, rows in star["dimensions"].items():
        if not rows:
            continue
        columns = list(rows[0])
        placeholders = ",".join("?" for _ in columns)
        sql = f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})"
        connection.executemany(sql, [[row.get(column) for column in columns] for row in rows])

    for table_name, rows in star["facts"].items():
        if not rows:
            continue
        columns = list(rows[0])
        placeholders = ",".join("?" for _ in columns)
        sql = f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})"
        connection.executemany(sql, [[row.get(column) for column in columns] for row in rows])

    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    connection.commit()
    connection.close()
    if violations:
        raise AssertionError(f"star schema foreign key violations: {violations[:5]}")
    if integrity != "ok":
        raise AssertionError(f"SQLite integrity check failed after star projection: {integrity}")


def main() -> None:
    financial = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    star = build_star(financial)

    counts = star["audit"]["counts"]
    parity = (
        counts["source_observations"] == counts["fact_observations"]
        and counts["source_derived_metrics"] == counts["fact_derived_metrics"]
        and counts["source_evaluations"] == counts["fact_evaluations"]
        and counts["source_evidence_edges"] == counts["fact_evidence_edges"]
    )
    if not parity:
        raise AssertionError(f"star schema source/fact parity failed: {counts}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(star, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    write_sqlite(star)
    print(
        "financial_star_schema="
        f"observations={counts['fact_observations']} "
        f"derived_metrics={counts['fact_derived_metrics']} "
        f"evaluations={counts['fact_evaluations']} "
        f"hash={star['content_hash']}"
    )


if __name__ == "__main__":
    main()
