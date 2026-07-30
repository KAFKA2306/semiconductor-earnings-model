#!/usr/bin/env python3
"""Merge source-traceable NAND KPIs into Financial Database v3."""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import build_financial_database as base
from nand_kpi_core import compare_intervals, compound_intervals

ROOT=Path(__file__).parents[1]
INDUSTRY=ROOT/"data/financial_db/industry_entities.json"
NAND=ROOT/"data/financial_db/nand_kpi_observations.json"
STATE=ROOT/"data/financial_db/nand_kpi_collection_state.json"
Q2Y={"nand_asp_change_qoq":"nand_asp_change_yoy","nand_bit_shipments_change_qoq":"nand_bit_shipments_change_yoy"}
Q2G={"nand_asp_change_qoq":"nand_asp_vs_company_guidance","nand_bit_shipments_change_qoq":"nand_bit_shipments_vs_company_guidance"}

def extend_entities(entities,industry):
    by={x["id"]:dict(x) for x in entities}
    for item in industry.get("entities",[]): by.setdefault(item["id"],{"id":item["id"],"type":"issuer"}).update({k:v for k,v in item.items() if v is not None})
    if "micron" in by: by["micron"]["industry_peer_group_ids"]=["nand-manufacturers"]
    return sorted(by.values(),key=lambda x:x["id"])
def interval(row):
    if row.get("value_low") is not None and row.get("value_high") is not None: return float(row["value_low"]),float(row["value_high"])
    if row.get("value") is not None: return float(row["value"]),float(row["value"])
    return None
def consecutive(rows):
    dates=[date.fromisoformat(x["period_end"]) for x in rows]; return all(70<=(b-a).days<=120 for a,b in zip(dates,dates[1:]))
def derive_yoy(rows):
    groups=defaultdict(list)
    for r in rows:
        if r.get("value_type")=="actual" and r.get("concept_id") in Q2Y and interval(r): groups[(r["entity_id"],r["concept_id"])].append(r)
    output=[]
    for (entity,concept),values in groups.items():
        ordered=sorted(values,key=lambda x:x["period_end"])
        for i in range(3,len(ordered)):
            window=ordered[i-3:i+1]
            if not consecutive(window): continue
            low,high=compound_intervals(interval(x) for x in window); latest=window[-1]; target=Q2Y[concept]
            output.append({**base.blank_observation(),"id":f"nand-kpi:{entity}:{latest['period_end']}:{target}:derived","entity_id":entity,"concept_id":target,"value_type":"internal_estimate","value_low":low,"value_high":high,"unit":"ratio","period_end":latest["period_end"],"period_type":"quarter","fiscal_year":latest.get("fiscal_year"),"fiscal_period":latest.get("fiscal_period"),"scope":"product","segment":"NAND","as_of":latest.get("as_of") or latest["period_end"],"source_tier":"model","source_name":"NAND KPI deterministic comparison model","source_url":latest["source_url"],"document_form":"derived_from_company_disclosures","model_id":"nand-kpi-compound-yoy.v1","formula":"product(1 + four sequential QoQ changes) - 1","assumptions":["Four source quarters are consecutive.","Bounds are compounded independently."],"evidence_ids":[x["id"] for x in window],"quality_flags":["derived_from_qualitative_intervals"]})
    return output
def derive_guidance(rows):
    actual={}; guidance={}
    for r in rows:
        if r.get("concept_id") not in Q2G or not r.get("period_end") or not interval(r): continue
        key=(r["entity_id"],r["concept_id"],r["period_end"])
        if r.get("value_type")=="actual": actual[key]=r
        elif r.get("value_type")=="company_guidance": guidance[key]=r
    output=[]
    for key,a in actual.items():
        g=guidance.get(key)
        if not g: continue
        comparison=compare_intervals(interval(a),interval(g)); target=Q2G[a["concept_id"]]
        output.append({**base.blank_observation(),"id":f"nand-kpi:{a['entity_id']}:{a['period_end']}:{target}:derived","entity_id":a["entity_id"],"concept_id":target,"value_type":"internal_estimate","value_low":comparison["difference_low"],"value_high":comparison["difference_high"],"unit":"percentage_points","period_end":a["period_end"],"period_type":"quarter","fiscal_year":a.get("fiscal_year"),"fiscal_period":a.get("fiscal_period"),"scope":a.get("scope","product"),"segment":"NAND","as_of":a.get("as_of") or a["period_end"],"source_tier":"model","source_name":"NAND KPI deterministic comparison model","source_url":a["source_url"],"document_form":"derived_from_company_disclosures","model_id":"nand-kpi-vs-company-guidance.v1","formula":"actual interval minus comparable company-guidance interval","assumptions":["Actual and guidance match issuer, KPI, scope and period."],"evidence_ids":[a["id"],g["id"]],"quality_flags":[f"comparison_result:{comparison['result']}"],"comparison_result":comparison["result"]})
    return output
def compact(r):
    if not r:return None
    return {k:r.get(k) for k in ("id","value","value_low","value_high","unit","value_type","reported_text","source_url","as_of","quality_flags","comparison_result")}
def nand_view(rows):
    by={}; periods=set()
    for r in rows:
        if str(r.get("concept_id","")).startswith("nand_") and r.get("period_end"):
            periods.add((r["entity_id"],r["period_end"])); by[(r["entity_id"],r["period_end"],r["concept_id"],r["value_type"])]=r
    output=[]
    for entity,period in sorted(periods):
        item={"entity_id":entity,"period_end":period}
        for label,prefix in (("asp","nand_asp"),("bit_shipments","nand_bit_shipments")):
            a=by.get((entity,period,prefix+"_change_qoq","actual")); g=by.get((entity,period,prefix+"_change_qoq","company_guidance")); y=by.get((entity,period,prefix+"_change_yoy","internal_estimate")); c=by.get((entity,period,prefix+"_vs_company_guidance","internal_estimate"))
            item[label]={"qoq_actual":compact(a),"yoy_derived":compact(y),"company_guidance":compact(g),"vs_company_guidance":compact(c),"guidance_status":"comparable" if g and c else "not_disclosed_or_not_comparable"}
        if item["asp"]["qoq_actual"] or item["bit_shipments"]["qoq_actual"]: output.append(item)
    return output
def extra_audit(rows,view):
    issues=[]; actual=[r for r in rows if r.get("value_type")=="actual" and r.get("concept_id") in Q2Y]
    if not actual: issues.append({"severity":"error","code":"nand_kpi_actuals_missing"})
    for r in actual:
        if not r.get("reported_text"): issues.append({"severity":"error","code":"nand_reported_text_missing","record_id":r["id"]})
        if "normalized_qualitative_band" in r.get("quality_flags",[]) and not r.get("normalization_method"): issues.append({"severity":"error","code":"nand_normalization_policy_missing","record_id":r["id"]})
    for item in view:
        if item["asp"]["qoq_actual"] and not item["asp"]["company_guidance"]: issues.append({"severity":"warning","code":"nand_asp_guidance_not_disclosed","entity_id":item["entity_id"],"period_end":item["period_end"]})
        if item["bit_shipments"]["qoq_actual"] and not item["bit_shipments"]["company_guidance"]: issues.append({"severity":"warning","code":"nand_bit_guidance_not_disclosed","entity_id":item["entity_id"],"period_end":item["period_end"]})
    return issues

def main():
    primary=base.load(base.PRIMARY_PATH); research=base.load(base.RESEARCH_PATH); catalog=base.load(base.CATALOG_PATH); manual=base.load(base.MANUAL_PATH); industry=base.load(INDUSTRY); ledger=base.load(NAND); state=base.load(STATE) if STATE.exists() else {"schema_version":"nand-kpi-collection-state.v1","generated_at":None,"issues":[]}
    entities=extend_entities(base.build_entities(primary,research),industry); ids={x["id"] for x in entities}
    raw=base.research_observations(research)+base.primary_observations(primary)+base.manual_observations(manual,catalog,ids)+base.manual_observations(ledger,catalog,ids)
    actual=base.deduplicate(raw); derived=derive_yoy(actual)+derive_guidance(actual); observations=base.deduplicate(actual+derived); sources=base.build_sources(observations)
    metrics=research.get("database",{}).get("derived_metrics",[]); evaluations=research.get("database",{}).get("evaluations",[]); edges=list(research.get("database",{}).get("evidence_edges",[]))
    for r in derived: edges.extend({"from_id":r["id"],"relationship":"derived_from","to_id":e} for e in r.get("evidence_ids",[]))
    views=base.build_views(entities,observations,metrics); views["nand_kpi_comparisons"]=nand_view(observations); audit=base.build_audit(entities,observations,metrics,catalog); audit["issues"].extend(extra_audit(observations,views["nand_kpi_comparisons"]))
    audit["counts"].update({"nand_actual_observations":sum(r.get("value_type")=="actual" and r.get("concept_id") in Q2Y for r in observations),"nand_derived_observations":len(derived),"nand_comparison_periods":len(views["nand_kpi_comparisons"])}); audit["counts"]["errors"]=sum(x["severity"]=="error" for x in audit["issues"]); audit["counts"]["warnings"]=sum(x["severity"]=="warning" for x in audit["issues"]); audit["status"]="PASS" if audit["counts"]["errors"]==0 else "FAIL"
    core={"schema_version":"financial-database.v3","extensions":["nand-operating-kpis.v1"],"source_api_hashes":{"primary":primary.get("snapshot_hash") or primary.get("content_hash"),"semiconductor_research":research.get("content_hash"),"metric_catalog":base.canonical_hash(catalog),"manual_observations":base.canonical_hash(manual),"industry_entities":base.canonical_hash(industry),"nand_kpi_observations":base.canonical_hash(ledger),"nand_kpi_collection_state":base.canonical_hash(state)},"catalog":catalog,"entities":entities,"sources":sources,"observations":observations,"derived_metrics":metrics,"evaluations":evaluations,"evidence_edges":edges,"views":views,"collection_state":{"nand_kpi":state},"audit":audit}
    payload={**core,"generated_at":datetime.now(timezone.utc).isoformat(),"content_hash":base.canonical_hash(core),"sqlite_path":"financial.db"}
    if audit["status"]!="PASS": raise AssertionError(f"Financial database NAND audit failed: {audit['issues']}")
    base.OUTPUT_DIR.mkdir(parents=True,exist_ok=True); base.JSON_PATH.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"); base.write_sqlite(payload)
    print(f"financial_database_v3_nand=entities={len(entities)} observations={len(observations)} nand_actuals={audit['counts']['nand_actual_observations']} nand_derived={len(derived)} periods={len(views['nand_kpi_comparisons'])} hash={payload['content_hash']}")
if __name__=="__main__": main()
