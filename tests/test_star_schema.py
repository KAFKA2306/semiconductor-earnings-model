from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parents[1]
FINANCIAL_PATH = ROOT / "site/public/api/v3/financial-database/index.json"
STAR_PATH = ROOT / "site/public/api/v3/financial-database/star-schema.json"
SQLITE_PATH = ROOT / "site/public/api/v3/financial-database/financial.db"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_star_schema_is_lossless_for_core_fact_sets() -> None:
    financial = load(FINANCIAL_PATH)
    star = load(STAR_PATH)

    assert star["schema_version"] == "financial-star-schema.v1"
    assert star["source_schema_version"] == financial["schema_version"]
    assert star["source_content_hash"] == financial["content_hash"]
    assert star["audit"]["status"] == "PASS"

    counts = star["audit"]["counts"]
    assert counts["fact_observations"] == len(financial["observations"])
    assert counts["fact_derived_metrics"] == len(financial["derived_metrics"])
    assert counts["fact_evaluations"] == len(financial["evaluations"])
    assert counts["fact_evidence_edges"] == len(financial["evidence_edges"])


def test_star_schema_dimensions_resolve_every_fact_foreign_key() -> None:
    star = load(STAR_PATH)
    dimensions = star["dimensions"]
    facts = star["facts"]

    companies = {row["company_key"] for row in dimensions["dim_company"]}
    metrics = {row["metric_key"] for row in dimensions["dim_metric"]}
    periods = {row["period_key"] for row in dimensions["dim_period"]}
    sources = {row["source_key"] for row in dimensions["dim_source"]}
    value_types = {row["value_type_key"] for row in dimensions["dim_value_type"]}
    scopes = {row["scope_key"] for row in dimensions["dim_scope"]}
    rules = {row["rule_key"] for row in dimensions["dim_rule"]}

    for row in facts["fact_observation"]:
        assert row["company_key"] in companies
        assert row["metric_key"] in metrics
        assert row["period_key"] in periods
        assert row["source_key"] in sources
        assert row["value_type_key"] in value_types
        assert row["scope_key"] in scopes

    for row in facts["fact_derived_metric"]:
        assert row["company_key"] in companies
        assert row["metric_key"] in metrics
        assert row["period_key"] in periods

    for row in facts["fact_evaluation"]:
        assert row["company_key"] in companies
        assert row["rule_key"] in rules
        assert row["period_key"] in periods


def test_star_schema_preserves_semantic_value_type_boundary() -> None:
    financial = load(FINANCIAL_PATH)
    star = load(STAR_PATH)
    expected = set(financial["catalog"]["value_types"])
    actual = {row["value_type"] for row in star["dimensions"]["dim_value_type"]}
    assert expected <= actual
    by_name = {row["value_type"]: row for row in star["dimensions"]["dim_value_type"]}
    assert by_name["actual"]["is_reported"] is True
    for name in {"company_guidance", "analyst_consensus", "internal_estimate", "scenario"}:
        assert by_name[name]["is_forward_looking"] is True


def test_sqlite_contains_star_schema_with_integrity_and_row_parity() -> None:
    star = load(STAR_PATH)
    connection = sqlite3.connect(SQLITE_PATH)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        for table, rows in {**star["dimensions"], **star["facts"]}.items():
            actual = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert actual == len(rows), (table, actual, len(rows))

        joined = connection.execute(
            """
            SELECT COUNT(*)
            FROM fact_observation f
            JOIN dim_company c ON c.company_key = f.company_key
            JOIN dim_metric m ON m.metric_key = f.metric_key
            JOIN dim_period p ON p.period_key = f.period_key
            JOIN dim_source s ON s.source_key = f.source_key
            JOIN dim_value_type vt ON vt.value_type_key = f.value_type_key
            JOIN dim_scope sc ON sc.scope_key = f.scope_key
            """
        ).fetchone()[0]
        assert joined == len(star["facts"]["fact_observation"])
    finally:
        connection.close()
