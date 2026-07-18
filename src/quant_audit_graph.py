"""Small deterministic LangGraph for validating and summarizing primary facts."""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

logger = logging.getLogger("primary_facts_graph")
GRAPH_VERSION = "primary-facts-graph.v1"


class AuditState(TypedDict, total=False):
    snapshot: dict[str, Any]
    snapshot_hash: str
    normalized: dict[str, Any]
    audit: dict[str, Any]
    events: list[dict[str, Any]]
    status: str


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _event(state: AuditState, node: str, status: str, **fields: Any) -> list[dict[str, Any]]:
    event = {"node": node, "status": status, "event_index": len(state.get("events", [])), **fields}
    logger.info("graph_node_%s", status, extra={"node": node, **fields})
    return [*state.get("events", []), event]


def validate_snapshot(state: AuditState) -> AuditState:
    snapshot = state["snapshot"]
    required = {"schema_version", "as_of", "primary_api_generated_at", "primary_api_content_hash", "primary_period", "sources", "selection_rule"}
    errors = sorted(required - snapshot.keys())
    sources = snapshot.get("sources", [])
    if not sources:
        errors.append("sources must not be empty")
    source_required = {
        "id",
        "period_start",
        "period_end",
        "operating_cash_flow_usd",
        "capital_expenditures_usd",
        "operating_cash_flow_fact_tag",
        "capital_expenditures_fact_tag",
        "operating_cash_flow_accession",
        "capital_expenditures_accession",
        "operating_cash_flow_source_url",
        "capital_expenditures_source_url",
        "source_api_url",
        "source_kind",
    }
    ids: set[str] = set()
    periods: set[tuple[str, str]] = set()
    for index, source in enumerate(sources):
        missing = sorted(source_required - source.keys())
        if missing:
            errors.append(f"source[{index}] missing primary fields: {','.join(missing)}")
            continue
        if source["id"] in ids:
            errors.append(f"duplicate source id: {source['id']}")
        ids.add(source["id"])
        periods.add((source["period_start"], source["period_end"]))
        for key in ("operating_cash_flow_usd", "capital_expenditures_usd"):
            if isinstance(source[key], bool) or not isinstance(source[key], int):
                errors.append(f"source[{index}] {key} must be an integer USD fact")
    if len(periods) > 1:
        errors.append("sources must cover one common reported period")
    if any(source.get("operating_cash_flow_usd", 0) == 0 for source in sources):
        errors.append("operating cash flow must not be zero")
    valid = not errors
    return {
        **state,
        "snapshot_hash": stable_hash(snapshot),
        "audit": {"valid_input": valid, "errors": errors, "graph_version": GRAPH_VERSION},
        "status": "validated" if valid else "blocked",
        "events": _event(state, "validate_snapshot", "success" if valid else "blocked", errors=errors),
    }


def normalize_metrics(state: AuditState) -> AuditState:
    sources = state["snapshot"]["sources"]
    ocf_total = sum((Decimal(source["operating_cash_flow_usd"]) for source in sources), Decimal(0))
    capex_by_tag: dict[str, Decimal] = {}
    for source in sources:
        tag = source["capital_expenditures_fact_tag"]
        capex_by_tag[tag] = capex_by_tag.get(tag, Decimal(0)) + Decimal(source["capital_expenditures_usd"])
    normalized: dict[str, Any] = {
        "operating_cash_flow_total_usd": int(ocf_total),
        "capital_expenditures_by_fact_tag_usd": {tag: int(value) for tag, value in sorted(capex_by_tag.items())},
        "capital_expenditures_fact_tag_count": len(capex_by_tag),
    }
    if len(capex_by_tag) == 1:
        capex_total = next(iter(capex_by_tag.values()))
        normalized["capital_expenditures_total_usd"] = int(capex_total)
        normalized["capital_expenditures_to_operating_cash_flow"] = str(capex_total / ocf_total)
        normalized["residual_cash_flow_usd"] = int(ocf_total - capex_total)
    return {
        **state,
        "normalized": normalized,
        "events": _event(state, "normalize_metrics", "success", metric_count=len(normalized)),
    }


def audit_facts(state: AuditState) -> AuditState:
    normalized = state["normalized"]
    findings: list[dict[str, Any]] = []
    if normalized["capital_expenditures_fact_tag_count"] > 1:
        findings.append({
            "id": "capital_expenditure_concepts_not_comparable",
            "severity": "major",
            "status": "open",
            "detail": "capital expenditures use multiple reported XBRL concepts; no combined capex or residual is published",
        })
    verdict = "observed" if not findings else "observed_with_limits"
    return {
        **state,
        "audit": {**state["audit"], "verdict": verdict, "findings": findings},
        "status": "audited",
        "events": _event(state, "audit_facts", "success", finding_count=len(findings)),
    }


def finish(state: AuditState) -> AuditState:
    return {
        **state,
        "status": state.get("status", "blocked"),
        "events": _event(state, "finish", "success", final_status=state.get("status", "blocked")),
    }


def _route_after_validation(state: AuditState) -> str:
    return "normalize" if state["audit"]["valid_input"] else "finish"


def build_graph(checkpointer: Any = None):
    graph = StateGraph(AuditState)
    graph.add_node("validate", validate_snapshot)
    graph.add_node("normalize", normalize_metrics)
    graph.add_node("audit_node", audit_facts)
    graph.add_node("finish", finish)
    graph.set_entry_point("validate")
    graph.add_conditional_edges("validate", _route_after_validation, {"normalize": "normalize", "finish": "finish"})
    graph.add_edge("normalize", "audit_node")
    graph.add_edge("audit_node", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def run_audit(snapshot: dict[str, Any], thread_id: str = "primary-facts") -> AuditState:
    return build_graph().invoke({"snapshot": snapshot, "events": []}, {"configurable": {"thread_id": thread_id}})
