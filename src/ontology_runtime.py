from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ONTOLOGY_SCHEMA_VERSION = "kafka-ontology.v0.1"
ALLOWED_PROPERTY_TYPES = {
    "boolean",
    "date",
    "datetime",
    "integer",
    "number",
    "string",
    "vector",
}


class OntologyContractError(RuntimeError):
    """Raised when the ontology definition or a projection violates the contract."""


class OntologyRuntime:
    """Deterministic read-only ontology compiler and projection runtime."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
        self.root = self.root.resolve()
        self.definition_path = self.root / "ontology" / "semiconductor.ontology.json"

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise OntologyContractError(f"required JSON artifact missing: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise OntologyContractError(f"expected JSON object: {path}")
        return payload

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _unique_by_api_name(
        rows: list[dict[str, Any]],
        label: str,
    ) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            api_name = str(row.get("api_name") or "").strip()
            if not api_name:
                raise OntologyContractError(f"{label} missing api_name")
            if api_name in index:
                raise OntologyContractError(f"duplicate {label} api_name: {api_name}")
            index[api_name] = row
        return index

    def definition(self) -> dict[str, Any]:
        payload = self._read_json(self.definition_path)
        self.validate_definition(payload)
        return payload

    @staticmethod
    def _validate_property(prop: dict[str, Any], owner: str) -> None:
        if prop.get("type") not in ALLOWED_PROPERTY_TYPES:
            raise OntologyContractError(
                f"{owner} property {prop.get('api_name')!r} has unsupported type "
                f"{prop.get('type')!r}"
            )
        if not isinstance(prop.get("nullable"), bool):
            raise OntologyContractError(
                f"{owner} property {prop.get('api_name')!r} must declare nullable"
            )

    def validate_definition(self, payload: dict[str, Any]) -> None:
        if payload.get("schema_version") != ONTOLOGY_SCHEMA_VERSION:
            raise OntologyContractError(
                f"unsupported ontology schema: {payload.get('schema_version')!r}"
            )

        interfaces = self._unique_by_api_name(
            payload.get("interfaces", []),
            "interface",
        )
        objects = self._unique_by_api_name(
            payload.get("object_types", []),
            "object type",
        )
        links = self._unique_by_api_name(
            payload.get("link_types", []),
            "link type",
        )
        actions = self._unique_by_api_name(
            payload.get("action_types", []),
            "action type",
        )

        interface_properties: dict[str, dict[str, dict[str, Any]]] = {}
        for api_name, interface in interfaces.items():
            props = self._unique_by_api_name(
                interface.get("properties", []),
                f"interface {api_name} property",
            )
            for prop in props.values():
                self._validate_property(prop, f"interface {api_name}")
            interface_properties[api_name] = props

        object_properties: dict[str, dict[str, dict[str, Any]]] = {}
        for api_name, object_type in objects.items():
            props = self._unique_by_api_name(
                object_type.get("properties", []),
                f"object {api_name} property",
            )
            for prop in props.values():
                self._validate_property(prop, f"object {api_name}")

            primary_key = str(object_type.get("primary_key") or "")
            if primary_key not in props:
                raise OntologyContractError(
                    f"object {api_name} primary_key {primary_key!r} "
                    "is not a declared property"
                )

            for interface_name in object_type.get("implements", []):
                if interface_name not in interfaces:
                    raise OntologyContractError(
                        f"object {api_name} implements unknown interface "
                        f"{interface_name}"
                    )
                for prop_name, contract in interface_properties[interface_name].items():
                    current = props.get(prop_name)
                    if current is None:
                        raise OntologyContractError(
                            f"object {api_name} misses interface property "
                            f"{interface_name}.{prop_name}"
                        )
                    if current.get("type") != contract.get("type"):
                        raise OntologyContractError(
                            f"object {api_name} property {prop_name} type "
                            f"disagrees with {interface_name}"
                        )
            object_properties[api_name] = props

        for api_name, link in links.items():
            source = link.get("source_object_type")
            target = link.get("target_object_type")
            if source not in objects or target not in objects:
                raise OntologyContractError(
                    f"link {api_name} references unknown endpoint: "
                    f"{source!r} -> {target!r}"
                )
            if link.get("source_cardinality") not in {"one", "many"}:
                raise OntologyContractError(
                    f"link {api_name} has invalid source_cardinality"
                )
            if link.get("target_cardinality") not in {"one", "many"}:
                raise OntologyContractError(
                    f"link {api_name} has invalid target_cardinality"
                )

        for api_name, action in actions.items():
            target = action.get("target_object_type")
            if target not in objects:
                raise OntologyContractError(
                    f"action {api_name} references unknown target object type "
                    f"{target!r}"
                )
            parameters = self._unique_by_api_name(
                action.get("parameters", []),
                f"action {api_name} parameter",
            )
            for parameter in parameters.values():
                if parameter.get("type") not in ALLOWED_PROPERTY_TYPES:
                    raise OntologyContractError(
                        f"action {api_name} parameter "
                        f"{parameter['api_name']} has unsupported type"
                    )
            for mutation in action.get("mutations", []):
                prop = mutation.get("property")
                if prop not in object_properties[target]:
                    raise OntologyContractError(
                        f"action {api_name} mutates unknown property "
                        f"{target}.{prop}"
                    )
                parameter = mutation.get("parameter")
                if parameter and parameter not in parameters:
                    raise OntologyContractError(
                        f"action {api_name} references unknown parameter "
                        f"{parameter}"
                    )
            if payload.get("read_only") and action.get("executable"):
                raise OntologyContractError(
                    f"read-only ontology cannot expose executable action "
                    f"{api_name}"
                )

    def describe(self) -> dict[str, Any]:
        payload = self.definition()
        return {
            "schema_version": payload["schema_version"],
            "ontology_id": payload["ontology_id"],
            "display_name": payload["display_name"],
            "read_only": payload["read_only"],
            "counts": {
                "object_types": len(payload["object_types"]),
                "link_types": len(payload["link_types"]),
                "action_types": len(payload["action_types"]),
                "interfaces": len(payload["interfaces"]),
            },
            "object_types": payload["object_types"],
            "link_types": payload["link_types"],
            "action_types": payload["action_types"],
            "interfaces": payload["interfaces"],
        }

    def build_snapshot(self) -> dict[str, Any]:
        definition = self.definition()
        entities_path = self.root / "data" / "primary" / "entities.json"
        concepts_path = (
            self.root / "data" / "financial_db" / "metric_catalog.json"
        )
        entities = self._read_json(entities_path)
        concepts = self._read_json(concepts_path)

        objects: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []

        for row in entities.get("entities", []):
            issuer_id = str(row.get("id") or "").strip()
            if not issuer_id:
                raise OntologyContractError("primary entity missing id")

            objects.append(
                {
                    "object_type": "Issuer",
                    "primary_key": issuer_id,
                    "properties": {
                        "id": issuer_id,
                        "name": row.get("name"),
                        "cik": row.get("cik"),
                        "issuer_class": row.get("class"),
                        "role": row.get("role"),
                        "source_label": row.get("source"),
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
                            "ticker": ticker,
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

        for row in concepts.get("concepts", []):
            concept_id = str(row.get("id") or "").strip()
            if not concept_id:
                raise OntologyContractError("metric catalog concept missing id")
            objects.append(
                {
                    "object_type": "NormalizedConcept",
                    "primary_key": concept_id,
                    "properties": {
                        "id": concept_id,
                        "statement": row.get("statement"),
                        "default_unit": row.get("default_unit"),
                        "aggregation": row.get("aggregation"),
                        "status": row.get("status"),
                        "formula": row.get("formula"),
                    },
                }
            )

        self._validate_instances(definition, objects, links)
        objects.sort(
            key=lambda row: (row["object_type"], row["primary_key"])
        )
        links.sort(
            key=lambda row: (
                row["link_type"],
                row["source"]["object_type"],
                row["source"]["primary_key"],
                row["target"]["object_type"],
                row["target"]["primary_key"],
            )
        )

        object_type_counts: dict[str, int] = {}
        for row in objects:
            object_type_counts[row["object_type"]] = (
                object_type_counts.get(row["object_type"], 0) + 1
            )
        link_type_counts: dict[str, int] = {}
        for row in links:
            link_type_counts[row["link_type"]] = (
                link_type_counts.get(row["link_type"], 0) + 1
            )

        return {
            "schema_version": "kafka-ontology-snapshot.v0.1",
            "ontology_id": definition["ontology_id"],
            "definition_hash": self._sha256(self.definition_path),
            "input_hashes": {
                "data/primary/entities.json": self._sha256(entities_path),
                "data/financial_db/metric_catalog.json": self._sha256(
                    concepts_path
                ),
            },
            "object_type_counts": object_type_counts,
            "link_type_counts": link_type_counts,
            "objects": objects,
            "links": links,
        }

    def _validate_instances(
        self,
        definition: dict[str, Any],
        objects: list[dict[str, Any]],
        links: list[dict[str, Any]],
    ) -> None:
        object_types = {
            row["api_name"]: row for row in definition["object_types"]
        }
        link_types = {
            row["api_name"]: row for row in definition["link_types"]
        }
        identities: set[tuple[str, str]] = set()

        for row in objects:
            object_type_name = row.get("object_type")
            object_type = object_types.get(object_type_name)
            if object_type is None:
                raise OntologyContractError(
                    f"instance uses unknown object type "
                    f"{object_type_name!r}"
                )

            primary_key = str(row.get("primary_key") or "")
            identity = (object_type_name, primary_key)
            if not primary_key:
                raise OntologyContractError(
                    f"{object_type_name} instance missing primary_key"
                )
            if identity in identities:
                raise OntologyContractError(
                    f"duplicate object identity: {identity}"
                )
            identities.add(identity)

            properties = row.get("properties")
            if not isinstance(properties, dict):
                raise OntologyContractError(
                    f"{identity} properties must be an object"
                )
            property_contracts = {
                prop["api_name"]: prop
                for prop in object_type["properties"]
            }
            undeclared = set(properties) - set(property_contracts)
            if undeclared:
                raise OntologyContractError(
                    f"{identity} has undeclared properties: "
                    f"{sorted(undeclared)}"
                )

            for prop_name, contract in property_contracts.items():
                if prop_name not in properties:
                    raise OntologyContractError(
                        f"{identity} missing property {prop_name}"
                    )
                if (
                    properties[prop_name] is None
                    and not contract["nullable"]
                ):
                    raise OntologyContractError(
                        f"{identity} has null for non-nullable property "
                        f"{prop_name}"
                    )

        for row in links:
            link_type_name = row.get("link_type")
            contract = link_types.get(link_type_name)
            if contract is None:
                raise OntologyContractError(
                    f"instance uses unknown link type "
                    f"{link_type_name!r}"
                )

            source = row.get("source") or {}
            target = row.get("target") or {}
            source_identity = (
                source.get("object_type"),
                str(source.get("primary_key") or ""),
            )
            target_identity = (
                target.get("object_type"),
                str(target.get("primary_key") or ""),
            )

            if source_identity[0] != contract["source_object_type"]:
                raise OntologyContractError(
                    f"link {link_type_name} source type mismatch: "
                    f"{source_identity[0]!r}"
                )
            if target_identity[0] != contract["target_object_type"]:
                raise OntologyContractError(
                    f"link {link_type_name} target type mismatch: "
                    f"{target_identity[0]!r}"
                )
            if source_identity not in identities:
                raise OntologyContractError(
                    f"link {link_type_name} source does not exist: "
                    f"{source_identity}"
                )
            if target_identity not in identities:
                raise OntologyContractError(
                    f"link {link_type_name} target does not exist: "
                    f"{target_identity}"
                )
