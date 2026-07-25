import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
API_PATH = ROOT / "site/public/api/v2/semiconductor-research/index.json"
BUILDER_PATH = ROOT / "scripts/build_semiconductor_research_api.py"
FINALIZER_PATH = ROOT / "scripts/finalize_semiconductor_research_api.py"

builder_spec = importlib.util.spec_from_file_location("research_builder", BUILDER_PATH)
builder = importlib.util.module_from_spec(builder_spec)
assert builder_spec.loader
builder_spec.loader.exec_module(builder)

finalizer_spec = importlib.util.spec_from_file_location("research_finalizer", FINALIZER_PATH)
finalizer = importlib.util.module_from_spec(finalizer_spec)
assert finalizer_spec.loader
finalizer_spec.loader.exec_module(finalizer)


def load_api() -> dict:
    return json.loads(API_PATH.read_text(encoding="utf-8"))


def test_research_api_integrates_facts_metrics_evaluations_and_peers():
    api = load_api()
    assert api["schema_version"] == "semiconductor-research-workbench.v2"
    assert api["content_hash"]
    assert api["summary"]["company_count"] >= 12
    assert api["summary"]["reported_fact_count"] >= 250
    assert api["summary"]["derived_metric_count"] >= 180
    assert api["summary"]["evaluation_count"] >= 72
    assert api["summary"]["evidence_edge_count"] >= 100
    assert api["summary"]["benchmark_platform_count"] >= 12

    companies = api["companies"]
    assert len(companies) == api["summary"]["company_count"]
    assert all(company["latest_annual_period"] >= "2024-01-01" for company in companies)
    assert all(len(company["evaluations"]) == 6 for company in companies)
    assert all(len(company["peer_context"]) >= 10 for company in companies)
    assert all(company["metrics"]["data_completeness"] >= 0.0 for company in companies)
    assert all(company["classification"] in {"resilient", "watch", "vulnerable", "incomplete"} for company in companies)
    assert all(
        next(item for item in company["evaluations"] if item["rule_id"] == "minimum_two_year_runway")["result"] == "pass"
        for company in companies
        if company["metrics"]["severe_runway_band"] == "self_funding"
    )


def test_normalized_database_is_traceable_and_has_unique_ids():
    api = load_api()
    database = api["database"]
    for collection_name in ("entities", "reported_facts", "derived_metrics", "evaluations"):
        identifiers = [record["id"] for record in database[collection_name]]
        assert len(identifiers) == len(set(identifiers)), collection_name
    assert len(database["entities"]) == api["summary"]["company_count"]
    assert all(fact["source_url"].startswith("https://www.sec.gov/") for fact in database["reported_facts"])
    relationships = {edge["relationship"] for edge in database["evidence_edges"]}
    assert {"derived_from", "uses_metric"} <= relationships


def test_ontology_and_benchmark_expose_current_and_missing_capabilities():
    api = load_api()
    ontology = api["ontology"]
    benchmark = api["benchmark"]
    entity_types = {item["id"] for item in ontology["entity_types"]}
    relationship_types = {item["id"] for item in ontology["relationship_types"]}
    unsupported = {item["id"] for item in ontology["unsupported_but_modeled_entity_types"]}
    assert {"reported_fact", "normalized_concept", "derived_metric", "evaluation", "evidence"} <= entity_types
    assert {"maps_to", "derived_from", "uses_metric", "supported_by"} <= relationship_types
    assert {"analyst_estimate", "guidance_revision", "earnings_surprise", "transcript_statement"} <= unsupported
    assert len(benchmark["platforms"]) >= 12
    assert len(benchmark["implementation_target"]["implemented"]) >= 8
    assert len(benchmark["implementation_target"]["remaining"]) >= 5
    assert all(platform["sources"] and all(source.startswith("https://") for source in platform["sources"]) for platform in benchmark["platforms"])


def test_math_helpers_and_rule_boundaries_are_deterministic():
    assert builder.safe_divide(10, 2) == 5
    assert builder.safe_divide(10, 0) is None
    assert round(builder.cagr(121, 100, 2), 6) == 0.1
    assert builder.percentile([1.0, 2.0, 3.0], 2.0) == 0.5
    assert builder.evaluation_result("minimum_two_year_runway", 1.99) == "fail"
    assert builder.evaluation_result("minimum_two_year_runway", 2.0) == "pass"
    assert finalizer.corrected_minimum_runway_result(self_funding=True, runway_years=None) == "pass"
    assert finalizer.corrected_minimum_runway_result(self_funding=False, runway_years=None) == "unknown"
    assert finalizer.corrected_minimum_runway_result(self_funding=False, runway_years=1.99) == "fail"
