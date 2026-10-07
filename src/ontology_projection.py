from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REGISTRY_PATHS = (
    "data/primary/entities.json",
    "data/primary/semiconductor_entities.json",
    "data/financial_db/industry_entities.json",
    "data/earnings_ledger/source_registry.json",
)

OBSERVATION_PATHS = (
    "data/financial_db/manual_observations.json",
    "data/financial_db/nand_kpi_observations.json",
    "data/financial_db/ai_infrastructure_observations.json",
    "data/financial_db/micron_business_unit_revenue_fy2026.json",
    "data/financial_db/micron_business_unit_operating_margin_fy2026.json",
)

CONCEPT_PATH = "data/financial_db/metric_catalog.json"


class ProjectionError(RuntimeError):
    pass


def _read_json(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    if not path.is_file():
        raise ProjectionError(f"required projection input missing: {relative_path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProjectionError(f"expected JSON object: {relative_path}")
    return payload


def _hash_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _collection(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key, [])
    if not isinstance(rows, list):
        raise ProjectionError(f"{key} must be an array")
    return [row for row in rows if isinstance(row, dict)]


def _issuer_id_from_row(row: dict[str, Any]) -> str | None:
    value = row.get("id") or row.get("entity_id") or row.get("company_id")
    if value in (None, ""):
        return None
    return str(value)


def _merge_issuer(
    issuers: dict[str, dict[str, Any]],
    row: dict[str, Any],
    source_path: str,
) -> None:
    issuer_id = _issuer_id_from_row(row)
    if not issuer_id:
        return
    current = issuers.setdefault(
        issuer_id,
        {
            "id": issuer_id,
            "name": None,
            "ticker": None,
            "cik": None,
            "issuer_class": None,
            "role": None,
            "source_label": source_path,
        },
    )
    candidates = {
        "name": row.get("name") or row.get("company_name"),
        "ticker": row.get("ticker"),
        "cik": row.get("cik"),
        "issuer_class": row.get("class"),
        "role": row.get("role"),
    }
    for key, value in candidates.items():
        if current.get(key) in (None, "") and value not in (None, ""):
            current[key] = value
    if current.get("issuer_class") in (None, ""):
        current["issuer_class"] = "public" if current.get("ticker") else "unknown"
    if current.get("role") in (None, ""):
        current["role"] = "unknown"


def _load_issuers(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    issuers: dict[str, dict[str, Any]] = {}
    for relative_path in REGISTRY_PATHS:
        payload = _read_json(root, relative_path)
        rows = payload.get("entities")
        if not isinstance(rows, list):
            rows = payload.get("sources")
        if not isinstance(rows, list):
            raise ProjectionError(f"issuer registry has no entities/sources: {relative_path}")
        for row in rows:
            if isinstance(row, dict):
                _merge_issuer(issuers, row, relative_path)

    ticker_to_issuer: dict[str, str] = {}
    for issuer_id, row in issuers.items():
        ticker = row.get("ticker")
        if ticker:
            ticker_key = str(ticker).upper()
            existing = ticker_to_issuer.get(ticker_key)
            if existing and existing != issuer_id:
                raise ProjectionError(
                    f"ticker maps to multiple issuers: {ticker_key}: {existing}, {issuer_id}"
                )
            ticker_to_issuer[ticker_key] = issuer_id
    return issuers, ticker_to_issuer


def _load_observations(
    root: Path,
    ticker_to_issuer: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    inputs: list[str] = []
    seen_ids: set[str] = set()
    for relative_path in OBSERVATION_PATHS:
        payload = _read_json(root, relative_path)
        inputs.append(relative_path)
        for raw in _collection(payload, "observations"):
            row = dict(raw)
            observation_id = str(row.get("id") or "").strip()
            if not observation_id:
                raise ProjectionError(f"observation missing id: {relative_path}")
            if observation_id in seen_ids:
                continue

            entity_id = row.get("entity_id")
            if not entity_id:
                ticker = row.get("ticker")
                if ticker:
                    entity_id = ticker_to_issuer.get(str(ticker).upper())
            if not entity_id:
                raise ProjectionError(
                    f"cannot resolve observation issuer: {observation_id}"
                )
            row["entity_id"] = str(entity_id)
            seen_ids.add(observation_id)
            rows.append(row)
    return rows, inputs


def _concepts(
    root: Path,
    observations: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    catalog = _read_json(root, CONCEPT_PATH)
    concepts: dict[str, dict[str, Any]] = {}
    for row in _collection(catalog, "concepts"):
        concept_id = str(row.get("id") or "").strip()
        if not concept_id:
            raise ProjectionError("metric catalog concept missing id")
        concepts[concept_id] = {
            "id": concept_id,
            "statement": row.get("statement") or "unknown",
            "default_unit": row.get("default_unit") or "unknown",
            "aggregation": row.get("aggregation") or "unknown",
            "status": row.get("status") or "catalogued",
            "formula": row.get("formula"),
        }

    inferred_units: dict[str, set[str]] = {}
    for row in observations:
        concept_id = str(row.get("concept_id") or "").strip()
        if not concept_id:
            raise ProjectionError(f"observation missing concept_id: {row.get('id')}")
        unit = row.get("unit")
        if unit:
            inferred_units.setdefault(concept_id, set()).add(str(unit))

    for concept_id, units in inferred_units.items():
        if concept_id in concepts:
            continue
        default_unit = next(iter(units)) if len(units) == 1 else "mixed"
        concepts[concept_id] = {
            "id": concept_id,
            "statement": "uncatalogued",
            "default_unit": default_unit,
            "aggregation": "unknown",
            "status": "observed_uncatalogued",
            "formula": None,
        }
    return concepts


def project_repository(
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    issuers, ticker_to_issuer = _load_issuers(root)
    observations, observation_inputs = _load_observations(root, ticker_to_issuer)
    concepts = _concepts(root, observations)

    missing_issuers = sorted(
        {str(row["entity_id"]) for row in observations} - set(issuers)
    )
    if missing_issuers:
        raise ProjectionError(
            f"observations reference unknown issuers: {missing_issuers}"
        )

    objects: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []

    for issuer_id, row in sorted(issuers.items()):
        objects.append(
            {
                "object_type": "Issuer",
                "primary_key": issuer_id,
                "properties": {
                    "id": issuer_id,
                    "name": row.get("name") or issuer_id,
                    "cik": str(row["cik"]) if row.get("cik") not in (None, "") else None,
                    "issuer_class": row.get("issuer_class") or "unknown",
                    "role": row.get("role") or "unknown",
                    "source_label": row.get("source_label") or "repository_registry",
                },
            }
        )
        ticker = row.get("ticker")
        if ticker:
            security_id = f"{issuer_id}:{ticker}"
            objects.append(
                {
                    "object_type": "Security",
                    "primary_key": security_id,
                    "properties": {
                        "id": security_id,
                        "ticker": str(ticker),
                    },
                }
            )
            links.append(
                {
                    "link_type": "issuedBy",
                    "source": {
                        "object_type": "Security",
                        "primary_key": security_id,
                    },
                    "target": {
                        "object_type": "Issuer",
                        "primary_key": issuer_id,
                    },
                }
            )

    for concept_id, row in sorted(concepts.items()):
        objects.append(
            {
                "object_type": "NormalizedConcept",
                "primary_key": concept_id,
                "properties": row,
            }
        )

    superseded_ids = {
        str(row["supersedes_id"])
        for row in observations
        if row.get("supersedes_id")
    }

    source_objects: dict[str, dict[str, Any]] = {}
    document_objects: dict[str, dict[str, Any]] = {}

    for row in observations:
        observation_id = str(row["id"])
        issuer_id = str(row["entity_id"])
        concept_id = str(row["concept_id"])
        source_url = str(row.get("source_url") or "").strip()
        if not source_url:
            raise ProjectionError(f"observation missing source_url: {observation_id}")
        source_id = _hash_id("source", source_url)
        document_id = _hash_id("document", source_url)
        source_tier = str(row.get("source_tier") or "unknown")
        source_name = str(
            row.get("source_name")
            or row.get("entity")
            or row.get("ticker")
            or source_url
        )

        source_objects.setdefault(
            source_id,
            {
                "object_type": "Source",
                "primary_key": source_id,
                "properties": {
                    "id": source_id,
                    "name": source_name,
                    "source_tier": source_tier,
                    "url": source_url,
                },
            },
        )
        document_objects.setdefault(
            document_id,
            {
                "object_type": "Document",
                "primary_key": document_id,
                "properties": {
                    "id": document_id,
                    "document_type": str(row.get("document_form") or "web_document"),
                    "source_id": source_id,
                    "source_url": source_url,
                    "as_of": str(row.get("as_of")) if row.get("as_of") else None,
                },
            },
        )

        objects.append(
            {
                "object_type": "Observation",
                "primary_key": observation_id,
                "properties": {
                    "id": observation_id,
                    "entity_id": issuer_id,
                    "concept_id": concept_id,
                    "value": row.get("value"),
                    "value_low": row.get("value_low"),
                    "value_high": row.get("value_high"),
                    "unit": str(row.get("unit") or "unknown"),
                    "value_type": str(row.get("value_type") or "unknown"),
                    "period_start": row.get("period_start"),
                    "period_end": row.get("period_end"),
                    "as_of": str(row.get("as_of")) if row.get("as_of") else None,
                    "source_id": source_id,
                    "source_url": source_url,
                    "status": "superseded" if observation_id in superseded_ids else "active",
                },
            }
        )
        links.extend(
            [
                {
                    "link_type": "observationSubject",
                    "source": {
                        "object_type": "Observation",
                        "primary_key": observation_id,
                    },
                    "target": {
                        "object_type": "Issuer",
                        "primary_key": issuer_id,
                    },
                },
                {
                    "link_type": "observationConcept",
                    "source": {
                        "object_type": "Observation",
                        "primary_key": observation_id,
                    },
                    "target": {
                        "object_type": "NormalizedConcept",
                        "primary_key": concept_id,
                    },
                },
                {
                    "link_type": "observationSource",
                    "source": {
                        "object_type": "Observation",
                        "primary_key": observation_id,
                    },
                    "target": {
                        "object_type": "Source",
                        "primary_key": source_id,
                    },
                },
                {
                    "link_type": "disclosedIn",
                    "source": {
                        "object_type": "Observation",
                        "primary_key": observation_id,
                    },
                    "target": {
                        "object_type": "Document",
                        "primary_key": document_id,
                    },
                },
            ]
        )

    objects.extend(source_objects.values())
    objects.extend(document_objects.values())

    input_paths = [
        *REGISTRY_PATHS,
        CONCEPT_PATH,
        *observation_inputs,
    ]
    return objects, links, input_paths
