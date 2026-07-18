"""Deterministic LangGraph runner for the semiconductor quant audit."""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

logger = logging.getLogger("quant_audit_graph")
GRAPH_VERSION = "2026-07-18.1"


class AuditState(TypedDict, total=False):
    snapshot: dict[str, Any]
    snapshot_hash: str
    normalized: dict[str, Any]
    scenarios: list[dict[str, Any]]
    audit: dict[str, Any]
    events: list[dict[str, Any]]
    status: str


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _event(state: AuditState, node: str, status: str, **fields: Any) -> list[dict[str, Any]]:
    event = {"node": node, "status": status, "event_index": len(state.get("events", [])), **fields}
    logger.info(
        "graph_node_%s",
        status,
        extra={"agent": "QuantAuditGraph", "task_id": state.get("snapshot_hash", "unknown"), "node": node, **fields},
    )
    return [*state.get("events", []), event]


def validate_snapshot(state: AuditState) -> AuditState:
    snapshot = state["snapshot"]
    required = {"schema_version", "as_of", "sources", "consensus", "scenarios", "beta_range", "model_base_ratio"}
    errors = sorted(required - snapshot.keys())
    if not snapshot.get("sources"):
        errors.append("sources must not be empty")
    source_required = {
        "id",
        "period_start",
        "period_end",
        "operating_cash_flow",
        "capital_expenditures",
        "operating_cash_flow_fact_tag",
        "capital_expenditures_fact_tag",
        "source_url",
    }
    for index, source in enumerate(snapshot.get("sources", [])):
        missing = sorted(source_required - source.keys())
        if missing:
            errors.append(f"source[{index}] missing primary fields: {','.join(missing)}")
    periods = {(source.get("period_start"), source.get("period_end")) for source in snapshot.get("sources", [])}
    if len(periods) > 1:
        errors.append("sources must cover one common reported period")
    valid = not errors
    return {
        **state,
        "snapshot_hash": stable_hash(snapshot),
        "audit": {"valid_input": valid, "errors": errors},
        "status": "validated" if valid else "blocked",
        "events": _event(state, "validate_snapshot", "success" if valid else "blocked", errors=errors),
    }


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def normalize_metrics(state: AuditState) -> AuditState:
    snapshot = state["snapshot"]
    ocf_total = sum((_d(row["operating_cash_flow"]) for row in snapshot["sources"]), Decimal("0"))
    capex_total = sum((_d(row["capital_expenditures"]) for row in snapshot["sources"]), Decimal("0"))
    ratio = capex_total / ocf_total
    normalized = {
        "operating_cash_flow_total": float(ocf_total),
        "capital_expenditures_total": float(capex_total),
        "capital_expenditures_to_operating_cash_flow": float(ratio),
        "residual_cash_flow": float(ocf_total - capex_total),
        "residual_margin": float((ocf_total - capex_total) / ocf_total),
        "fact_tag_count": len({row["capital_expenditures_fact_tag"] for row in snapshot["sources"]}),
    }
    return {
        **state,
        "normalized": normalized,
        "events": _event(state, "normalize_metrics", "success", metric_count=len(normalized)),
    }


def _pct(value: Decimal) -> float:
    return round(float(value * 100), 1)


def calculate_scenarios(state: AuditState) -> AuditState:
    base_ratio = _d(state["snapshot"]["model_base_ratio"])
    margin0 = _d(state["snapshot"]["consensus"]["forward_margin"])
    beta_low, beta_high = map(_d, state["snapshot"]["beta_range"])
    results: list[dict[str, Any]] = []
    for scenario in state["snapshot"]["scenarios"]:
        g_i = (1 + _d(scenario["ocf_growth"])) * (1 - _d(scenario["fcf_reserve"]) + _d(scenario["external_financing"])) / base_ratio - 1
        revenue_low = beta_low * g_i
        revenue_high = beta_high * g_i
        margin1 = _d(scenario["forward_margin"])
        earnings_low = (1 + revenue_low) * margin1 / margin0 - 1
        earnings_high = (1 + revenue_high) * margin1 / margin0 - 1
        results.append({
            "name": scenario["name"],
            "effective_investment_growth": _pct(g_i),
            "revenue_growth_range": [_pct(min(revenue_low, revenue_high)), _pct(max(revenue_low, revenue_high))],
            "operating_earnings_growth_range": [_pct(min(earnings_low, earnings_high)), _pct(max(earnings_low, earnings_high))],
        })
    return {
        **state,
        "scenarios": results,
        "events": _event(state, "calculate_scenarios", "success", scenario_count=len(results)),
    }


def audit_model(state: AuditState) -> AuditState:
    snapshot = state["snapshot"]
    findings = [
        {"id": "beta_unestimated", "severity": "critical", "status": "open", "detail": "beta is a scenario assumption, not an estimated coefficient"},
        {"id": "investment_lag_missing", "severity": "major", "status": "open", "detail": "investment-to-revenue lag is not modeled"},
        {"id": "consensus_is_secondary", "severity": "major", "status": "open", "detail": "consensus is not a primary company forecast"},
    ]
    periods = {(row.get("period_start"), row.get("period_end")) for row in snapshot["sources"]}
    tags_present = all(row.get("operating_cash_flow_fact_tag") and row.get("capital_expenditures_fact_tag") for row in snapshot["sources"])
    if len(periods) > 1:
        findings.insert(0, {"id": "reported_period_mismatch", "severity": "critical", "status": "open", "detail": "reported facts do not cover one common period"})
    if not tags_present:
        findings.insert(0, {"id": "primary_fact_tag_missing", "severity": "critical", "status": "open", "detail": "one or more inputs lack a primary XBRL fact tag"})
    if snapshot["consensus"].get("raw_data_hash"):
        findings[-1]["status"] = "tracked"
    return {
        **state,
        "audit": {
            **state["audit"],
            "verdict": "conditional",
            "findings": findings,
            "confidence": 0.60,
        },
        "status": "audited",
        "events": _event(state, "audit_model", "success", finding_count=len(findings)),
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
    graph.add_node("calculate", calculate_scenarios)
    graph.add_node("audit_node", audit_model)
    graph.add_node("finish", finish)
    graph.set_entry_point("validate")
    graph.add_conditional_edges("validate", _route_after_validation, {"normalize": "normalize", "finish": "finish"})
    graph.add_edge("normalize", "calculate")
    graph.add_edge("calculate", "audit_node")
    graph.add_edge("audit_node", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def run_audit(snapshot: dict[str, Any], thread_id: str = "quant-audit") -> AuditState:
    graph = build_graph()
    return graph.invoke({"snapshot": snapshot, "events": []}, {"configurable": {"thread_id": thread_id}})
