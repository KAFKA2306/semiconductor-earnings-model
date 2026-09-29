from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.ontology_runtime import (
    ONTOLOGY_SCHEMA_VERSION,
    OntologyContractError,
    OntologyRuntime,
)

ROOT = Path(__file__).resolve().parents[1]


def test_definition_exposes_palantir_style_core_primitives() -> None:
    runtime = OntologyRuntime(ROOT)
    definition = runtime.describe()

    assert definition["schema_version"] == ONTOLOGY_SCHEMA_VERSION
    assert definition["ontology_id"] == "semiconductor-financial-research"
    assert definition["read_only"] is True
    assert definition["counts"]["object_types"] >= 8
    assert definition["counts"]["link_types"] >= 6
    assert definition["counts"]["action_types"] >= 2
    assert definition["counts"]["interfaces"] >= 3

    object_types = {row["api_name"] for row in definition["object_types"]}
    link_types = {row["api_name"] for row in definition["link_types"]}
    action_types = {row["api_name"] for row in definition["action_types"]}

    assert {"Issuer", "Security", "Observation", "Document"} <= object_types
    assert {"issuedBy", "observationSubject", "observationSource"} <= link_types
    assert {"supersedeObservation", "setEvaluationStatus"} <= action_types
    assert all(row["executable"] is False for row in definition["action_types"])


def test_snapshot_projects_real_repository_data_into_objects_and_links() -> None:
    runtime = OntologyRuntime(ROOT)
    snapshot = runtime.build_snapshot()

    assert snapshot["schema_version"] == "kafka-ontology-snapshot.v0.2"
    assert snapshot["definition_hash"]
    assert snapshot["input_hashes"]["data/primary/entities.json"]
    assert snapshot["input_hashes"]["data/financial_db/metric_catalog.json"]

    counts = snapshot["object_type_counts"]
    assert counts["Issuer"] >= 10
    assert counts["Security"] >= 8
    assert counts["NormalizedConcept"] >= 40
    assert snapshot["link_type_counts"]["issuedBy"] == counts["Security"]
    assert counts["Observation"] > 0
    assert counts["Source"] > 0
    assert counts["Document"] > 0
    assert snapshot["link_type_counts"]["observationSubject"] == counts["Observation"]
    assert snapshot["link_type_counts"]["observationConcept"] == counts["Observation"]
    assert snapshot["link_type_counts"]["observationSource"] == counts["Observation"]
    assert snapshot["link_type_counts"]["disclosedIn"] == counts["Observation"]

    identities = {
        (row["object_type"], row["primary_key"])
        for row in snapshot["objects"]
    }
    for link in snapshot["links"]:
        assert (
            link["source"]["object_type"],
            link["source"]["primary_key"],
        ) in identities
        assert (
            link["target"]["object_type"],
            link["target"]["primary_key"],
        ) in identities


def test_read_only_contract_rejects_executable_actions() -> None:
    runtime = OntologyRuntime(ROOT)
    definition = copy.deepcopy(runtime.definition())
    definition["action_types"][0]["executable"] = True

    with pytest.raises(OntologyContractError, match="read-only ontology"):
        runtime.validate_definition(definition)


def test_snapshot_is_deterministic() -> None:
    runtime = OntologyRuntime(ROOT)
    assert runtime.build_snapshot() == runtime.build_snapshot()


def test_micron_observation_traverses_to_subject_concept_source_and_document() -> None:
    runtime = OntologyRuntime(ROOT)
    observation_id = "micron:2026-05-28:revenue:consolidated:actual"

    result = runtime.get_object(
        object_type="Observation",
        primary_key=observation_id,
    )
    assert result["null_reason"] is None
    assert result["record"]["properties"]["entity_id"] == "micron"
    assert result["record"]["properties"]["concept_id"] == "revenue"

    graph = runtime.get_neighbors(
        object_type="Observation",
        primary_key=observation_id,
    )
    assert graph["null_reason"] is None
    link_types = {row["link_type"] for row in graph["links"]}
    assert {
        "observationSubject",
        "observationConcept",
        "observationSource",
        "disclosedIn",
    } <= link_types

    neighbor_types = {row["object_type"] for row in graph["neighbors"]}
    assert {"Issuer", "NormalizedConcept", "Source", "Document"} <= neighbor_types


def test_search_objects_finds_real_issuer_and_observations() -> None:
    runtime = OntologyRuntime(ROOT)

    issuer = runtime.search_objects(
        object_type="Issuer",
        query="Micron",
        limit=10,
    )
    assert any(row["primary_key"] == "micron" for row in issuer["records"])

    observations = runtime.search_objects(
        object_type="Observation",
        query="micron",
        limit=20,
    )
    assert observations["records"]
    assert all(row["object_type"] == "Observation" for row in observations["records"])


def test_missing_object_and_neighbors_remain_explicit() -> None:
    runtime = OntologyRuntime(ROOT)

    missing = runtime.get_object(
        object_type="Issuer",
        primary_key="__missing__",
    )
    assert missing["record"] is None
    assert missing["null_reason"] == "NOT_FOUND"

    graph = runtime.get_neighbors(
        object_type="Issuer",
        primary_key="__missing__",
    )
    assert graph["object"] is None
    assert graph["neighbors"] == []
    assert graph["null_reason"] == "NOT_FOUND"
