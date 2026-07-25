#!/usr/bin/env python3
"""Build an ontology-backed semiconductor research workbench API."""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
RESILIENCE_PATH = ROOT / "site/public/api/v1/semiconductor-resilience/index.json"
PROFIT_PATH = ROOT / "site/public/api/v1/semiconductor-profit/index.json"
ONTOLOGY_PATH = ROOT / "data/ontology/financial_research_ontology.json"
BENCHMARK_PATH = ROOT / "data/benchmark/earnings_review_sites.json"
OUTPUT_PATH = ROOT / "site/public/api/v2/semiconductor-research/index.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_divide(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def cagr(latest: float | int | None, oldest: float | int | None, periods: int) -> float | None:
    if latest is None or oldest is None or latest <= 0 or oldest <= 0 or periods <= 0:
        return None
    return (float(latest) / float(oldest)) ** (1 / periods) - 1


def pct_change(latest: float | int | None, previous: float | int | None) -> float | None:
    if latest is None or previous in (None, 0):
        return None
    return float(latest) / float(previous) - 1


def percentile(values: list[float], value: float | None) -> float | None:
    if value is None or not values:
        return None
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return round((below + 0.5 * equal) / len(values), 4)


def median(values: list[float | int | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    return statistics.median(usable) if usable else None


def fact_id(company_id: str, period_end: str, concept: str) -> str:
    return f"fact:{company_id}:{period_end}:{concept}"


def metric_id(company_id: str, metric: str) -> str:
    return f"metric:{company_id}:{metric}"


def evaluation_result(rule_id: str, metric_value: float | int | None, *, self_funding: bool = False) -> str:
    if metric_value is None:
        return "unknown"
    if rule_id == "severe_self_funding":
        return "pass" if metric_value >= 0 else "fail"
    if rule_id == "minimum_two_year_runway":
        return "pass" if self_funding or metric_value >= 2 else "fail"
    if rule_id == "fcf_consistency":
        return "pass" if metric_value >= 0.6 else "fail"
    if rule_id == "net_liquidity_nonnegative":
        return "pass" if metric_value >= 0 else "fail"
    if rule_id == "operating_profitability":
        return "pass" if metric_value > 0 else "fail"
    if rule_id == "minimum_data_quality":
        return "pass" if metric_value >= 0.8 else "fail"
    raise ValueError(f"Unknown rule: {rule_id}")


def prior_year_quarter(company: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any] | None:
    fiscal_year = latest.get("fiscal_year")
    fiscal_period = latest.get("fiscal_period")
    if fiscal_year is None or fiscal_period is None:
        return None
    return next(
        (
            quarter
            for quarter in company.get("quarters", [])
            if quarter.get("fiscal_year") == fiscal_year - 1
            and quarter.get("fiscal_period") == fiscal_period
        ),
        None,
    )


def build_company(company: dict[str, Any], profit_company: dict[str, Any] | None) -> dict[str, Any]:
    years = company["years"]
    latest = years[0]
    oldest = years[-1]
    history_periods = max(len(years) - 1, 0)
    annual_revenue = int(latest["revenue"]["reported_value"])
    latest_fcf = int(latest["free_cash_flow"]["reported_value"])
    liquid_reserve = int(latest["liquid_reserve"]["reported_value"])
    total_debt = latest.get("total_debt", {}).get("reported_value") if latest.get("total_debt") else None
    net_liquidity = latest.get("net_liquidity_usd")
    retained_earnings = latest.get("retained_earnings", {}).get("reported_value") if latest.get("retained_earnings") else None
    capex = abs(int(latest["capital_expenditures"]["reported_value"]))
    annual_fcf_margins = [safe_divide(year["free_cash_flow"]["reported_value"], year["revenue"]["reported_value"]) for year in years]
    annual_fcf_margins = [value for value in annual_fcf_margins if value is not None]
    positive_fcf_years = sum(int(year["free_cash_flow"]["reported_value"]) >= 0 for year in years)
    severe = next(item for item in company["scenarios"] if item["scenario_id"] == "severe")
    self_funding = severe["annual_cash_burn_usd"] == 0

    latest_quarter = profit_company["quarters"][0] if profit_company and profit_company.get("quarters") else None
    prior_quarter = prior_year_quarter(profit_company, latest_quarter) if latest_quarter and profit_company else None
    latest_q_revenue = int(latest_quarter["revenue"]["reported_value"]) if latest_quarter else None
    latest_q_operating_income = int(latest_quarter["operating_income"]["reported_value"]) if latest_quarter else None
    prior_q_revenue = int(prior_quarter["revenue"]["reported_value"]) if prior_quarter else None
    prior_q_operating_income = int(prior_quarter["operating_income"]["reported_value"]) if prior_quarter else None
    operating_margin = safe_divide(latest_q_operating_income, latest_q_revenue)
    prior_operating_margin = safe_divide(prior_q_operating_income, prior_q_revenue)

    required_checks = {
        "annual_revenue": latest.get("revenue") is not None,
        "annual_ocf": latest.get("operating_cash_flow") is not None,
        "annual_capex": latest.get("capital_expenditures") is not None,
        "cash": latest.get("cash") is not None,
        "retained_earnings": latest.get("retained_earnings") is not None,
        "total_debt": latest.get("total_debt") is not None,
        "quarterly_profit": latest_quarter is not None,
        "minimum_four_annual_periods": len(years) >= 4,
    }
    completeness = sum(required_checks.values()) / len(required_checks)
    metrics = {
        "free_cash_flow_usd": latest_fcf,
        "free_cash_flow_margin": safe_divide(latest_fcf, annual_revenue),
        "operating_margin": operating_margin,
        "revenue_yoy": pct_change(latest_q_revenue, prior_q_revenue),
        "operating_income_yoy": pct_change(latest_q_operating_income, prior_q_operating_income),
        "operating_margin_delta_bps": None if operating_margin is None or prior_operating_margin is None else round((operating_margin - prior_operating_margin) * 10000),
        "liquid_reserve_usd": liquid_reserve,
        "retained_earnings_usd": retained_earnings,
        "total_debt_usd": total_debt,
        "net_liquidity_usd": net_liquidity,
        "liquidity_to_revenue": safe_divide(liquid_reserve, annual_revenue),
        "capex_intensity": safe_divide(capex, annual_revenue),
        "positive_fcf_ratio": positive_fcf_years / len(years),
        "revenue_cagr": cagr(annual_revenue, int(oldest["revenue"]["reported_value"]), history_periods),
        "liquidity_cagr": cagr(liquid_reserve, int(oldest["liquid_reserve"]["reported_value"]), history_periods),
        "fcf_margin_volatility": statistics.pstdev(annual_fcf_margins) if len(annual_fcf_margins) >= 2 else None,
        "severe_stressed_fcf_usd": severe["stressed_free_cash_flow_usd"],
        "severe_runway_years": severe["liquid_reserve_runway_years"],
        "severe_runway_band": severe["runway_band"],
        "data_completeness": completeness,
    }
    rule_values = {
        "severe_self_funding": metrics["severe_stressed_fcf_usd"],
        "minimum_two_year_runway": metrics["severe_runway_years"],
        "fcf_consistency": metrics["positive_fcf_ratio"],
        "net_liquidity_nonnegative": metrics["net_liquidity_usd"],
        "operating_profitability": metrics["operating_margin"],
        "minimum_data_quality": metrics["data_completeness"],
    }
    evaluations = [{"rule_id": rule_id, "value": value, "result": evaluation_result(rule_id, value, self_funding=self_funding)} for rule_id, value in rule_values.items()]
    if severe["runway_band"] == "under_two_years":
        classification = "vulnerable"
    elif severe["runway_band"] in {"two_to_five_years", "five_years_plus"} or latest_fcf < 0:
        classification = "watch"
    elif completeness < 0.8:
        classification = "incomplete"
    else:
        classification = "resilient"
    reasons = []
    reasons.append("深い下振れ後もFCF黒字" if self_funding else f"深い下振れ耐久 {severe['liquid_reserve_runway_years']}年")
    reasons.append(f"FCF黒字 {positive_fcf_years}/{len(years)}年")
    reasons.append("純流動性は負債fact不足" if net_liquidity is None else "純流動性は非負" if net_liquidity >= 0 else "純流動性は負")
    if operating_margin is not None:
        reasons.append(f"直近営業利益率 {operating_margin:.1%}")
    reasons.append(f"データ充足率 {completeness:.0%}")
    quality_flags = []
    if len(years) < 5:
        quality_flags.append("annual_history_under_five_years")
    if latest.get("short_term_investments") is None:
        quality_flags.append("short_term_investments_not_separately_reported")
    if total_debt is None:
        quality_flags.append("debt_unavailable")
    if company["selected_tags"]["capital_expenditures"] == "PaymentsToAcquireProductiveAssets":
        quality_flags.append("alternative_capex_concept")
    if latest_quarter is None:
        quality_flags.append("quarterly_profit_unavailable")
    if prior_quarter is None:
        quality_flags.append("prior_year_comparable_quarter_unavailable")
    return {
        "id": company["id"], "name": company["name"], "ticker": company["ticker"], "cik": str(company["cik"]),
        "role": company["role"], "peer_group_id": company["role"], "classification": classification,
        "classification_reasons": reasons, "latest_annual_period": latest["period_end"],
        "latest_quarter_period": latest_quarter["period_end"] if latest_quarter else None,
        "history_years": len(years), "quarter_history": len(profit_company.get("quarters", [])) if profit_company else 0,
        "metrics": metrics, "evaluations": evaluations,
        "quality": {"required_checks": required_checks, "flags": quality_flags, "selected_tags": company["selected_tags"]},
        "annual_history": years, "quarterly_history": profit_company.get("quarters", []) if profit_company else [],
        "scenarios": company["scenarios"],
    }


def attach_peer_context(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metric_names = ["free_cash_flow_margin", "operating_margin", "revenue_yoy", "liquidity_to_revenue", "capex_intensity", "positive_fcf_ratio", "revenue_cagr", "liquidity_cagr", "fcf_margin_volatility", "data_completeness"]
    for company in companies:
        peers = [item for item in companies if item["peer_group_id"] == company["peer_group_id"]]
        context = {}
        for metric in metric_names:
            values = [float(item["metrics"][metric]) for item in peers if item["metrics"].get(metric) is not None]
            value = company["metrics"].get(metric)
            context[metric] = {"peer_median": median(values), "peer_percentile": percentile(values, value), "peer_count": len(values)}
        company["peer_context"] = context
    return companies


def normalize_database(companies: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    reported_facts, derived_metrics, evaluations, evidence_edges = [], [], [], []
    fact_fields = {"revenue":"revenue", "operating_cash_flow":"operating_cash_flow", "capital_expenditures":"capital_expenditures", "cash":"cash", "short_term_investments":"short_term_investments", "retained_earnings":"retained_earnings"}
    for company in companies:
        for year in company["annual_history"]:
            for concept, field in fact_fields.items():
                fact = year.get(field)
                if not fact:
                    continue
                identifier = fact_id(company["id"], year["period_end"], concept)
                reported_facts.append({"id":identifier,"issuer_id":company["id"],"concept_id":concept,"xbrl_tag":fact.get("fact_tag"),"value":fact.get("reported_value"),"unit":fact.get("unit","USD"),"period_start":fact.get("period_start"),"period_end":fact.get("period_end"),"period_type":"instant" if fact.get("period_start") is None else "duration","form":fact.get("form"),"accession":fact.get("accession"),"source_url":fact.get("source_url")})
            if year.get("total_debt"):
                derived_metrics.append({"id":f"metric:{company['id']}:{year['period_end']}:total_debt","issuer_id":company["id"],"metric_id":"total_debt","value":year["total_debt"]["reported_value"],"unit":"USD","period_end":year["period_end"],"formula":year["total_debt"].get("derivation")})
            for metric_name, source_concepts in {"free_cash_flow":["operating_cash_flow","capital_expenditures"],"liquid_reserve":["cash","short_term_investments"]}.items():
                value = year[metric_name]["reported_value"]
                derived_identifier = f"metric:{company['id']}:{year['period_end']}:{metric_name}"
                derived_metrics.append({"id":derived_identifier,"issuer_id":company["id"],"metric_id":metric_name,"value":value,"unit":"USD","period_end":year["period_end"],"formula":year[metric_name].get("derivation")})
                for concept in source_concepts:
                    source = year.get(concept)
                    if source:
                        evidence_edges.append({"from_id":derived_identifier,"relationship":"derived_from","to_id":fact_id(company["id"],year["period_end"],concept)})
        for name, value in company["metrics"].items():
            if isinstance(value, (int, float)) or value is None:
                derived_metrics.append({"id":metric_id(company["id"],name),"issuer_id":company["id"],"metric_id":name,"value":value,"unit":"USD" if name.endswith("_usd") else "basis_points" if name.endswith("_bps") else "ratio","period_end":company["latest_annual_period"]})
        rule_metric = {"severe_self_funding":"severe_stressed_fcf_usd","minimum_two_year_runway":"severe_runway_years","fcf_consistency":"positive_fcf_ratio","net_liquidity_nonnegative":"net_liquidity_usd","operating_profitability":"operating_margin","minimum_data_quality":"data_completeness"}
        for evaluation in company["evaluations"]:
            evaluation_identifier = f"evaluation:{company['id']}:{evaluation['rule_id']}"
            evaluations.append({"id":evaluation_identifier,"issuer_id":company["id"],**evaluation})
            evidence_edges.append({"from_id":evaluation_identifier,"relationship":"uses_metric","to_id":metric_id(company["id"],rule_metric[evaluation["rule_id"]])})
    return reported_facts, derived_metrics, evaluations, evidence_edges


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> None:
    resilience, profit, ontology, benchmark = load(RESILIENCE_PATH), load(PROFIT_PATH), load(ONTOLOGY_PATH), load(BENCHMARK_PATH)
    profit_by_id = {company["id"]: company for company in profit["companies"]}
    companies = [build_company(company, profit_by_id.get(company["id"])) for company in resilience["companies"] if company.get("years")]
    companies = attach_peer_context(companies)
    reported_facts, derived_metrics, evaluations, evidence_edges = normalize_database(companies)
    peer_groups = []
    for peer_group_id in sorted({company["peer_group_id"] for company in companies}):
        members = [company for company in companies if company["peer_group_id"] == peer_group_id]
        peer_groups.append({"id":peer_group_id,"label_ja":"半導体製造装置" if peer_group_id == "semiconductor-equipment" else "半導体","member_ids":[company["id"] for company in members],"medians":{"free_cash_flow_margin":median([company["metrics"]["free_cash_flow_margin"] for company in members]),"operating_margin":median([company["metrics"]["operating_margin"] for company in members]),"revenue_yoy":median([company["metrics"]["revenue_yoy"] for company in members]),"liquidity_to_revenue":median([company["metrics"]["liquidity_to_revenue"] for company in members]),"capex_intensity":median([company["metrics"]["capex_intensity"] for company in members]),"positive_fcf_ratio":median([company["metrics"]["positive_fcf_ratio"] for company in members])}})
    classification_counts = {classification:sum(company["classification"] == classification for company in companies) for classification in ("resilient","watch","vulnerable","incomplete")}
    payload_core = {
        "schema_version":"semiconductor-research-workbench.v2","generated_at":datetime.now(timezone.utc).isoformat(),
        "source_api_hashes":{"resilience":resilience["content_hash"],"profit":profit["content_hash"]},
        "ontology":ontology,"benchmark":benchmark,
        "summary":{"company_count":len(companies),"reported_fact_count":len(reported_facts),"derived_metric_count":len(derived_metrics),"evaluation_count":len(evaluations),"evidence_edge_count":len(evidence_edges),"classification_counts":classification_counts,"benchmark_platform_count":len(benchmark["platforms"]),"implemented_capability_count":len(benchmark["implementation_target"]["implemented"]),"remaining_capability_count":len(benchmark["implementation_target"]["remaining"])},
        "peer_groups":peer_groups,"companies":companies,
        "database":{"entities":[{"id":company["id"],"type":"issuer","name":company["name"],"ticker":company["ticker"],"cik":company["cik"],"role":company["role"],"peer_group_id":company["peer_group_id"]} for company in companies],"reported_facts":reported_facts,"derived_metrics":derived_metrics,"evaluations":evaluations,"evidence_edges":evidence_edges},
    }
    payload = {**payload_core,"content_hash":content_hash(payload_core)}
    OUTPUT_PATH.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(f"semiconductor_research_workbench={len(companies)} facts={len(reported_facts)} metrics={len(derived_metrics)} evaluations={len(evaluations)} edges={len(evidence_edges)}")


if __name__ == "__main__":
    main()
