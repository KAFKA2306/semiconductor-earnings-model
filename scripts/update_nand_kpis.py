#!/usr/bin/env python3
"""Update the NAND KPI evidence ledger from official IR documents."""
from __future__ import annotations

import argparse, json, os, re, subprocess, tempfile, urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from nand_kpi_core import BAND_POLICY_ID, extract_micron_nand_kpis, percentage_interval

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "data/financial_db/nand_kpi_sources.json"
LEDGER = ROOT / "data/financial_db/nand_kpi_observations.json"
STATE = ROOT / "data/financial_db/nand_kpi_collection_state.json"
UA = os.getenv("NAND_KPI_USER_AGENT", "KAFKA2306 NAND KPI collector")
MONTHS = {m.lower(): i for i, m in enumerate("January February March April May June July August September October November December".split(), 1)}

class Links(HTMLParser):
    def __init__(self): super().__init__(); self.items=[]; self.href=None; self.text=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower()=="a": self.href=dict(attrs).get("href"); self.text=[]
    def handle_data(self, data):
        if self.href is not None: self.text.append(data)
    def handle_endtag(self, tag):
        if tag.lower()=="a" and self.href is not None:
            self.items.append((self.href," ".join(self.text).strip())); self.href=None; self.text=[]

def load(path): return json.loads(path.read_text(encoding="utf-8"))
def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html,application/pdf,*/*"})
    with urllib.request.urlopen(req,timeout=45) as r: return r.read(),r.headers.get_content_type()
def allowed(url,domains):
    host=(urlparse(url).hostname or "").lower(); return any(host==d or host.endswith("."+d) for d in domains)
def links(url,body,domains):
    p=Links(); p.feed(body.decode("utf-8",errors="replace")); result={}
    for href,text in p.items:
        absolute=urljoin(url,href); label=f"{text} {absolute}".lower()
        if allowed(absolute,domains) and any(w in label for w in ("earnings","financial","result","presentation","prepared","remarks","script","quarter")):
            result[absolute]={"url":absolute,"text":text}
    return sorted(result.values(),key=lambda x:x["url"])
def pdf_text(content):
    with tempfile.TemporaryDirectory() as d:
        pdf=Path(d)/"a.pdf"; txt=Path(d)/"a.txt"; pdf.write_bytes(content)
        try: subprocess.run(["pdftotext","-layout",str(pdf),str(txt)],check=True,capture_output=True,text=True)
        except FileNotFoundError as e: raise RuntimeError("pdftotext is required; install poppler-utils") from e
        return txt.read_text(encoding="utf-8",errors="replace")
def parse_date(value):
    m=re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})",value.strip())
    if not m or m.group(1).lower() not in MONTHS: raise ValueError(value)
    return date(int(m.group(3)),MONTHS[m.group(1).lower()],int(m.group(2))).isoformat()
def infer(text,fallback):
    result=dict(fallback); flat=re.sub(r"\s+"," ",text)
    if not result.get("period_end"):
        m=re.search(r"(?i)(?:quarter|three months|period)\s+ended\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",flat)
        if m: result["period_end"]=parse_date(m.group(1))
    m=re.search(r"(?i)(?:fiscal\s+)?Q([1-4])\s*(?:FY)?\s*(20\d{2})",flat)
    if m: result.setdefault("fiscal_period","Q"+m.group(1)); result.setdefault("fiscal_year",int(m.group(2)))
    if not result.get("as_of"):
        dates=re.findall(r"([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})",flat[:4000])
        if dates: result["as_of"]=parse_date(dates[0])
    if not result.get("period_end"): return None
    result.setdefault("as_of",result["period_end"]); result.setdefault("document_type","earnings_presentation"); return result

def generic(text):
    flat=re.sub(r"\s+"," ",text)
    for m in re.finditer(r"(?i)NAND.{0,700}",flat):
        window=m.group(0); output={}
        patterns={
          "bit_shipments":r"(?i)(?:bit shipments?|bit output|bit sales)\s+(?:were\s+)?(?P<dir>up|down|increased|declined|decreased)\s+(?:in\s+)?(?:the\s+)?(?P<phrase>(?:low|mid|high)(?:-to-(?:low|mid|high))?[- ]?(?:single[- ]digit|double[- ]digit|teens|\d{2}s)|(?:approximately|about|around)?\s*\d+(?:\.\d+)?\s*%)",
          "asp":r"(?i)(?:ASP|average selling price|prices?)\s+(?:were\s+)?(?P<dir>up|down|increased|declined|decreased)\s+(?:in\s+)?(?:the\s+)?(?P<phrase>(?:low|mid|high)(?:-to-(?:low|mid|high))?[- ]?(?:single[- ]digit|double[- ]digit|teens|\d{2}s)|(?:approximately|about|around)?\s*\d+(?:\.\d+)?\s*%)"}
        for name,pattern in patterns.items():
            hit=re.search(pattern,window)
            if hit:
                direction="decline" if hit.group("dir").lower() in {"down","declined","decreased"} else "increase"
                lo,hi=percentage_interval(hit.group("phrase"),direction=direction)
                output[name]={"value_low":lo,"value_high":hi,"reported_text":hit.group(0),"reported_phrase":hit.group("phrase")}
        if output: return output
    return None

def row(source,period,concept,parsed):
    names={"micron":"Micron Technology, Inc.","kioxia-holdings":"KIOXIA Holdings Corporation","sandisk":"Sandisk Corporation","samsung-electronics":"Samsung Electronics Co., Ltd.","sk-hynix":"SK hynix Inc."}
    return {"id":f"nand-kpi:{source['entity_id']}:{period['period_end']}:{concept}:actual","entity_id":source["entity_id"],"concept_id":concept,"value_type":"actual","value_low":parsed["value_low"],"value_high":parsed["value_high"],"unit":"ratio","period_end":period["period_end"],"period_type":"quarter","fiscal_year":period.get("fiscal_year"),"fiscal_period":period.get("fiscal_period"),"scope":"product","segment":"NAND","as_of":period["as_of"],"source_tier":"primary_company","source_name":names.get(source["entity_id"],source["entity_id"]),"source_url":period["source_url"],"document_form":period.get("document_type"),"source_tag":"reported_qualitative_change","reported_text":parsed["reported_text"],"reported_phrase":parsed.get("reported_phrase"),"normalization_method":BAND_POLICY_ID,"assumptions":["Numeric bounds are a deterministic normalization of the preserved company phrase; the company did not report an exact point value."],"quality_flags":["normalized_qualitative_band"]}
def parse_document(source,document,content,content_type):
    text=pdf_text(content) if content_type=="application/pdf" or content.startswith(b"%PDF") else content.decode("utf-8",errors="replace")
    period=infer(text,document)
    if not period: return []
    period["source_url"]=document["source_url"]
    parsed=extract_micron_nand_kpis(text) if source["adapter"]=="micron_prepared_remarks" else generic(text)
    if not parsed: return []
    out=[]
    if parsed.get("asp"): out.append(row(source,period,"nand_asp_change_qoq",parsed["asp"]))
    if parsed.get("bit_shipments"): out.append(row(source,period,"nand_bit_shipments_change_qoq",parsed["bit_shipments"]))
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--offline",action="store_true"); args=ap.parse_args()
    registry=load(SOURCE); ledger=load(LEDGER); rows={r["id"]:r for r in ledger.get("observations",[])}
    state={"schema_version":"nand-kpi-collection-state.v1","generated_at":datetime.now(timezone.utc).isoformat(),"offline":args.offline,"sources":[],"issues":[]}
    if not args.offline:
        for source in registry["sources"]:
            info={"entity_id":source["entity_id"],"checked_urls":[],"discovered_urls":[],"parsed_documents":[],"new_observations":0}; docs={d["source_url"]:dict(d) for d in source.get("documents",[])}; pages=[]
            for url in source.get("discovery_urls",[]):
                try:
                    body,kind=fetch(url); info["checked_urls"].append(url)
                    if kind=="text/html":
                        for item in links(url,body,source["official_domains"]):
                            info["discovered_urls"].append(item["url"])
                            if item["url"].lower().endswith(".pdf") or "static-files" in item["url"]: docs.setdefault(item["url"],{"source_url":item["url"]})
                            else: pages.append(item["url"])
                except Exception as e: state["issues"].append({"entity_id":source["entity_id"],"url":url,"error":type(e).__name__,"message":str(e)[:300]})
            for url in sorted(set(pages))[:20]:
                try:
                    body,kind=fetch(url); info["checked_urls"].append(url)
                    if kind=="text/html":
                        for item in links(url,body,source["official_domains"]):
                            info["discovered_urls"].append(item["url"])
                            if item["url"].lower().endswith(".pdf") or "static-files" in item["url"]: docs.setdefault(item["url"],{"source_url":item["url"]})
                except Exception as e: state["issues"].append({"entity_id":source["entity_id"],"url":url,"error":type(e).__name__,"message":str(e)[:300]})
            for document in list(docs.values())[:40]:
                try:
                    content,kind=fetch(document["source_url"]); additions=parse_document(source,document,content,kind)
                    for addition in additions: rows[addition["id"]]=addition
                    if additions: info["parsed_documents"].append(document["source_url"]); info["new_observations"]+=len(additions)
                except Exception as e: state["issues"].append({"entity_id":source["entity_id"],"url":document["source_url"],"error":type(e).__name__,"message":str(e)[:300]})
            info["discovered_urls"]=sorted(set(info["discovered_urls"])); state["sources"].append(info)
    ordered=sorted(rows.values(),key=lambda r:(r["entity_id"],r["period_end"],r["concept_id"],r["id"]))
    for r in ordered:
        if not str(r.get("source_url","")).startswith("https://"): raise ValueError(f"Non-HTTPS source: {r.get('id')}")
        if r.get("value_type")=="actual" and r.get("concept_id") in {"nand_asp_change_qoq","nand_bit_shipments_change_qoq"} and (not r.get("reported_text") or r.get("normalization_method")!=BAND_POLICY_ID): raise ValueError(f"Untraceable NAND actual: {r.get('id')}")
    ledger["observations"]=ordered; LEDGER.write_text(json.dumps(ledger,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"); STATE.write_text(json.dumps(state,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(f"nand_kpi_update=observations={len(ordered)} issues={len(state['issues'])} offline={args.offline}")
if __name__=="__main__": main()
