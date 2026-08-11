from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

STANDARD_SCHEMA_VERSION = "data-platform-standard.v1"
REPOSITORY = "KAFKA2306/semiconductor-earnings-model"
MAX_QUERY_LENGTH = 128


class DataContractError(RuntimeError):
    """Raised when canonical data violates a fail-closed contract."""


class DataPlatformService:
    """Read-only deterministic projection of the canonical earnings ledger."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
        self.root = self.root.resolve()
        self.ledger = self.root / "data" / "earnings_ledger"

    def _safe_path(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if self.root != path and self.root not in path.parents:
            raise DataContractError(f"path escapes repository root: {relative_path}")
        return path

    def _read_json(self, relative_path: str) -> dict[str, Any]:
        path = self._safe_path(relative_path)
        if not path.is_file():
            raise DataContractError(f"required artifact missing: {relative_path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise DataContractError(f"expected JSON object: {relative_path}")
        return payload

    def _read_ndjson(self, relative_path: str) -> list[dict[str, Any]]:
        path = self._safe_path(relative_path)
        if not path.is_file():
            raise DataContractError(f"required artifact missing: {relative_path}")
        records: list[dict[str, Any]] = []
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise DataContractError(f"expected object at {relative_path}:{line_number}")
            records.append(record)
        return records

    def _sha256(self, relative_path: str) -> str:
        path = self._safe_path(relative_path)
        if not path.is_file():
            raise DataContractError(f"required artifact missing: {relative_path}")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _timestamp(record: dict[str, Any]) -> str | None:
        for field in (
            "generated_at",
            "run_at",
            "generated_from_run_at",
            "verified_at",
            "retrieved_at",
            "published_at",
            "report_date",
        ):
            value = record.get(field)
            if value is not None:
                return str(value)
        return None

    @staticmethod
    def _source_url(record: dict[str, Any]) -> str | None:
        value = record.get("source_url")
        return str(value) if value else None

    def _envelope(
        self,
        *,
        canonical_id: str,
        data_layer: str,
        source_path: str,
        record: dict[str, Any],
        source_type: str,
        source_id: str,
        source_doc_id: str | None = None,
        source_url: str | None = None,
        source_observed_at: str | None = None,
        data_as_of: str | None = None,
        generated_at: str | None = None,
        freshness: str | None = None,
        stale: bool | None = None,
        null_reason: str | None = None,
        derivation_method: str = "deterministic_projection",
        basis: str = "canonical_ledger",
        provenance_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if data_layer not in {"raw/bronze", "normalized/silver", "public/gold"}:
            raise DataContractError(f"unknown data layer: {data_layer}")
        source_hash = self._sha256(source_path)
        observed = source_observed_at if source_observed_at is not None else self._timestamp(record)
        as_of = data_as_of if data_as_of is not None else observed
        generated = generated_at if generated_at is not None else observed
        provenance = {
            "repository": REPOSITORY,
            "source_path": source_path,
            "source_hash": source_hash,
            "projection": derivation_method,
        }
        if provenance_extra:
            provenance.update(provenance_extra)
        return {
            "canonical_id": canonical_id,
            "schema_version": STANDARD_SCHEMA_VERSION,
            "data_layer": data_layer,
            "data_as_of": as_of,
            "generated_at": generated,
            "source_type": source_type,
            "source_id": source_id,
            "source_doc_id": source_doc_id,
            "source_url": source_url,
            "source_observed_at": observed,
            "source_hash": source_hash,
            "freshness": freshness,
            "stale": stale,
            "null_reason": null_reason,
            "derivation_method": derivation_method,
            "basis": basis,
            "provenance": provenance,
            "record": record,
        }

    def _events(self) -> list[dict[str, Any]]:
        return self._read_ndjson("data/earnings_ledger/events.ndjson")

    def _validate_query(self, query: str) -> str:
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise ValueError(f"query exceeds {MAX_QUERY_LENGTH} characters")
        return query.casefold()

    def _company_records(self) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for event in self._events():
            company_id = str(event.get("company_id") or "").strip()
            if not company_id:
                raise DataContractError("canonical earnings event missing company_id")
            candidate = {
                "company_id": company_id,
                "company_name": event.get("company_name"),
                "ticker": event.get("ticker"),
                "data_as_of": event.get("published_at") or event.get("report_date"),
                "freshness": event.get("freshness"),
                "schema_version": event.get("schema_version"),
            }
            current = by_id.get(company_id)
            if current is None or str(candidate.get("data_as_of") or "") > str(current.get("data_as_of") or ""):
                by_id[company_id] = candidate
        return sorted(by_id.values(), key=lambda row: (str(row.get("company_name") or "").casefold(), row["company_id"]))

    def search_companies(self, query: str = "") -> dict[str, Any]:
        needle = self._validate_query(query)
        records = []
        for row in self._company_records():
            haystack = " ".join(
                str(row.get(key) or "")
                for key in ("company_id", "company_name", "ticker")
            ).casefold()
            if needle and needle not in haystack:
                continue
            company_id = str(row["company_id"])
            records.append(
                self._envelope(
                    canonical_id=f"company:{company_id}",
                    data_layer="normalized/silver",
                    source_path="data/earnings_ledger/events.ndjson",
                    record=row,
                    source_type="canonical_ledger",
                    source_id=company_id,
                    data_as_of=str(row.get("data_as_of") or "") or None,
                    freshness=str(row.get("freshness") or "") or None,
                    stale=(str(row.get("freshness") or "").upper() != "PASS") if row.get("freshness") is not None else None,
                    derivation_method="deduplicate_company_identity",
                    basis="accepted_earnings_events",
                )
            )
        return {"schema_version": STANDARD_SCHEMA_VERSION, "query": query, "count": len(records), "records": records}

    def _event_envelope(self, event: dict[str, Any]) -> dict[str, Any]:
        event_id = str(event.get("event_id") or "").strip()
        company_id = str(event.get("company_id") or "").strip()
        if not event_id or not company_id:
            raise DataContractError("canonical earnings event missing event_id/company_id")
        freshness = str(event.get("freshness") or "") or None
        return self._envelope(
            canonical_id=f"earnings-event:{event_id}",
            data_layer="normalized/silver",
            source_path="data/earnings_ledger/events.ndjson",
            record=event,
            source_type=str(event.get("source_adapter") or "canonical_ledger"),
            source_id=company_id,
            source_doc_id=str(event.get("accession_number") or event_id),
            source_url=self._source_url(event),
            source_observed_at=str(event.get("retrieved_at") or event.get("published_at") or "") or None,
            data_as_of=str(event.get("published_at") or event.get("report_date") or "") or None,
            generated_at=str(event.get("retrieved_at") or event.get("published_at") or "") or None,
            freshness=freshness,
            stale=(freshness.upper() != "PASS") if freshness is not None else None,
            derivation_method="identity_projection",
            basis=str(event.get("document_type") or "accepted_primary_source_event"),
            provenance_extra={"event_id": event_id},
        )

    def get_company_earnings(self, company_id: str) -> dict[str, Any]:
        company_id = self._validate_query(company_id)
        matches = [event for event in self._events() if str(event.get("company_id") or "").casefold() == company_id]
        matches.sort(key=lambda row: (str(row.get("report_date") or ""), str(row.get("published_at") or "")), reverse=True)
        if not matches:
            return {
                "schema_version": STANDARD_SCHEMA_VERSION,
                "company_id": company_id,
                "count": 0,
                "records": [],
                "null_reason": "NOT_FOUND",
            }
        record = self._event_envelope(matches[0])
        return {"schema_version": STANDARD_SCHEMA_VERSION, "company_id": company_id, "count": 1, "records": [record], "null_reason": None}

    def get_earnings_history(self, company_id: str) -> dict[str, Any]:
        company_id = self._validate_query(company_id)
        matches = [event for event in self._events() if str(event.get("company_id") or "").casefold() == company_id]
        matches.sort(key=lambda row: (str(row.get("report_date") or ""), str(row.get("published_at") or "")))
        records = [self._event_envelope(event) for event in matches]
        return {
            "schema_version": STANDARD_SCHEMA_VERSION,
            "company_id": company_id,
            "count": len(records),
            "records": records,
            "null_reason": None if records else "NOT_FOUND",
        }

    def get_evidence(self, event_id: str = "") -> dict[str, Any]:
        event_id = self._validate_query(event_id)
        events = self._events()
        if event_id:
            events = [event for event in events if str(event.get("event_id") or "").casefold() == event_id]
        records = []
        for event in events:
            event_identifier = str(event.get("event_id") or "")
            records.append(
                self._envelope(
                    canonical_id=f"evidence:{event_identifier}",
                    data_layer="normalized/silver",
                    source_path="data/earnings_ledger/events.ndjson",
                    record={
                        "event_id": event_identifier,
                        "company_id": event.get("company_id"),
                        "document_type": event.get("document_type"),
                        "report_date": event.get("report_date"),
                        "source_url": event.get("source_url"),
                        "accession_number": event.get("accession_number"),
                    },
                    source_type=str(event.get("source_adapter") or "canonical_ledger"),
                    source_id=str(event.get("company_id") or ""),
                    source_doc_id=str(event.get("accession_number") or event_identifier),
                    source_url=self._source_url(event),
                    source_observed_at=str(event.get("retrieved_at") or event.get("published_at") or "") or None,
                    data_as_of=str(event.get("published_at") or event.get("report_date") or "") or None,
                    generated_at=str(event.get("retrieved_at") or event.get("published_at") or "") or None,
                    freshness=str(event.get("freshness") or "") or None,
                    stale=(str(event.get("freshness") or "").upper() != "PASS") if event.get("freshness") is not None else None,
                    derivation_method="evidence_projection",
                    basis="accepted_primary_source_event",
                    provenance_extra={"event_id": event_identifier},
                )
            )
        audit = self._read_json("data/earnings_ledger/evidence_latest.json")
        records.append(
            self._envelope(
                canonical_id="evidence-audit:latest",
                data_layer="normalized/silver",
                source_path="data/earnings_ledger/evidence_latest.json",
                record=audit,
                source_type="deterministic_audit",
                source_id="earnings-evidence-audit",
                data_as_of=self._timestamp(audit),
                generated_at=self._timestamp(audit),
                freshness="PASS" if audit.get("status") == "PASS" else "FAIL",
                stale=False if audit.get("status") == "PASS" else None,
                null_reason="NO_VERIFIED_EVIDENCE_IN_WINDOW" if not audit.get("evidence") else None,
                derivation_method="audit_passthrough",
                basis="earnings_evidence_audit",
            )
        )
        return {
            "schema_version": STANDARD_SCHEMA_VERSION,
            "event_id": event_id or None,
            "count": len(records),
            "records": records,
            "null_reason": "NOT_FOUND" if event_id and len(records) == 1 else None,
        }

    def get_lineage(self) -> dict[str, Any]:
        lineage = self._read_json("data/earnings_ledger/lineage_latest.json")
        record = self._envelope(
            canonical_id="lineage:latest",
            data_layer="normalized/silver",
            source_path="data/earnings_ledger/lineage_latest.json",
            record=lineage,
            source_type="deterministic_lineage",
            source_id="earnings-ledger-lineage",
            data_as_of=self._timestamp(lineage),
            generated_at=self._timestamp(lineage),
            freshness="PASS" if lineage.get("status") == "PASS" else "FAIL",
            stale=False if lineage.get("status") == "PASS" else None,
            derivation_method="lineage_passthrough",
            basis="sha256_bound_artifact_manifest",
        )
        return {"schema_version": STANDARD_SCHEMA_VERSION, "records": [record]}

    def get_audit_status(self) -> dict[str, Any]:
        paths = sorted(
            str(path.relative_to(self.root)).replace("\\", "/")
            for path in self.ledger.glob("*audit_latest.json")
        )
        if not paths:
            raise DataContractError("no canonical audit artifacts found")
        records = []
        status = "PASS"
        for relative_path in paths:
            audit = self._read_json(relative_path)
            audit_status = str(audit.get("status") or "UNKNOWN").upper()
            if audit_status not in {"PASS", "SUCCESS"}:
                status = "BLOCKED"
            records.append(
                self._envelope(
                    canonical_id=f"audit:{Path(relative_path).stem}",
                    data_layer="normalized/silver",
                    source_path=relative_path,
                    record=audit,
                    source_type="deterministic_audit",
                    source_id=Path(relative_path).stem,
                    data_as_of=self._timestamp(audit),
                    generated_at=self._timestamp(audit),
                    freshness="PASS" if audit_status in {"PASS", "SUCCESS"} else audit_status,
                    stale=False if audit_status in {"PASS", "SUCCESS"} else None,
                    null_reason=None if audit_status != "UNKNOWN" else "AUDIT_STATUS_UNKNOWN",
                    derivation_method="audit_passthrough",
                    basis="canonical_ledger_audit",
                )
            )
        return {"schema_version": STANDARD_SCHEMA_VERSION, "status": status, "count": len(records), "records": records}

    def get_publication_snapshot(self) -> dict[str, Any]:
        publication = self._read_json("data/earnings_ledger/publication_latest.json")
        audit_status = str(publication.get("audit_status") or "UNKNOWN").upper()
        record = self._envelope(
            canonical_id="publication:latest",
            data_layer="public/gold",
            source_path="data/earnings_ledger/publication_latest.json",
            record=publication,
            source_type="deterministic_publication",
            source_id="earnings-ledger-publication",
            data_as_of=self._timestamp(publication),
            generated_at=self._timestamp(publication),
            freshness="PASS" if audit_status == "PASS" else audit_status,
            stale=False if audit_status == "PASS" else None,
            null_reason="NO_FRESH_PUBLISHABLE_EVENTS" if not publication.get("events") else None,
            derivation_method="publication_projection",
            basis="audit_pass_and_freshness_gate",
        )
        return {"schema_version": STANDARD_SCHEMA_VERSION, "records": [record]}

    def get_data_quality(self) -> dict[str, Any]:
        audit = self.get_audit_status()
        publication = self.get_publication_snapshot()["records"][0]
        lineage = self.get_lineage()["records"][0]
        lineage_record = lineage["record"]
        artifact_checks = []
        revision_changed = False
        missing_artifact = False
        for artifact in lineage_record.get("artifacts", []):
            relative_path = artifact.get("path")
            expected_hash = artifact.get("sha256")
            if not relative_path or not expected_hash:
                continue
            path = self._safe_path(str(relative_path))
            if not path.is_file():
                state = "MISSING"
                actual_hash = None
                revision_changed = True
                missing_artifact = True
            else:
                actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                state = "MATCH" if actual_hash == expected_hash else "REVISION_CHANGED"
                revision_changed = revision_changed or state != "MATCH"
            artifact_checks.append(
                {
                    "path": relative_path,
                    "expected_sha256": expected_hash,
                    "current_sha256": actual_hash,
                    "state": state,
                }
            )
        publication_status = str(publication["record"].get("audit_status") or "UNKNOWN").upper()
        reasons = []
        if audit["status"] != "PASS":
            reasons.append("CANONICAL_AUDIT_NOT_PASS")
        if publication_status != "PASS":
            reasons.append("PUBLICATION_AUDIT_NOT_PASS")
        if revision_changed:
            reasons.append("LINEAGE_REVISION_CHANGED")
        if missing_artifact:
            reasons.append("LINEAGE_ARTIFACT_MISSING")
        blocking_reasons = {"CANONICAL_AUDIT_NOT_PASS", "PUBLICATION_AUDIT_NOT_PASS", "LINEAGE_ARTIFACT_MISSING"}
        status = "BLOCKED" if blocking_reasons.intersection(reasons) else "PASS"
        quality_record = {
            "status": status,
            "reasons": reasons,
            "audit_record_count": audit["count"],
            "publication_audit_status": publication_status,
            "lineage_status": lineage_record.get("status"),
            "lineage_artifacts": artifact_checks,
            "lineage_revision_changed": revision_changed,
            "fail_closed": True,
        }
        record = self._envelope(
            canonical_id="data-quality:latest",
            data_layer="public/gold",
            source_path="data/earnings_ledger/lineage_latest.json",
            record=quality_record,
            source_type="deterministic_quality_gate",
            source_id="data-quality",
            data_as_of=self._timestamp(lineage_record),
            generated_at=self._timestamp(lineage_record),
            freshness=status,
            stale=None,
            null_reason=None,
            derivation_method="deterministic_quality_projection",
            basis="audit_publication_and_sha256_lineage",
            provenance_extra={
                "audit_status": audit["status"],
                "publication_source_hash": publication["source_hash"],
            },
        )
        return {"schema_version": STANDARD_SCHEMA_VERSION, "status": status, "records": [record]}


_SERVICE: DataPlatformService | None = None


def service() -> DataPlatformService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = DataPlatformService()
    return _SERVICE
