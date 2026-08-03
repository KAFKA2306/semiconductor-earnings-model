#!/usr/bin/env python3
"""Update the NAND KPI evidence ledger from official IR documents."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from nand_collection_state import (
    build_document_state,
    content_sha256,
    freshness_audit,
    previous_document_map,
    select_candidates,
    should_parse_document,
)
from nand_kpi_core import BAND_POLICY_ID, extract_micron_nand_kpis, percentage_interval

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "data/financial_db/nand_kpi_sources.json"
LEDGER = ROOT / "data/financial_db/nand_kpi_observations.json"
STATE = ROOT / "data/financial_db/nand_kpi_collection_state.json"
UA = os.getenv("NAND_KPI_USER_AGENT") or "KAFKA2306 NAND KPI collector"
MONTHS = {
    month.lower(): index
    for index, month in enumerate(
        "January February March April May June July August September October November December".split(),
        1,
    )
}
PAGE_LIMIT = 20
DOCUMENT_LIMIT = 40


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str]] = []
        self.href: str | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_data(self, data: str) -> None:
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self.href is not None:
            self.items.append((self.href, " ".join(self.text).strip()))
            self.href = None
            self.text = []


def load(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read(), response.headers.get_content_type()


def allowed(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def links(url: str, body: bytes, domains: list[str]) -> list[dict[str, Any]]:
    parser = Links()
    parser.feed(body.decode("utf-8", errors="replace"))
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for discovery_rank, (href, text) in enumerate(parser.items):
        absolute = urljoin(url, href)
        label = f"{text} {absolute}".lower()
        if absolute in seen or not allowed(absolute, domains):
            continue
        if not any(
            word in label
            for word in (
                "earnings",
                "financial",
                "result",
                "presentation",
                "prepared",
                "remarks",
                "script",
                "quarter",
            )
        ):
            continue
        seen.add(absolute)
        result.append(
            {
                "url": absolute,
                "text": text,
                "discovery_rank": discovery_rank,
            }
        )
    return result


def pdf_text(content: bytes) -> str:
    with tempfile.TemporaryDirectory() as directory:
        pdf = Path(directory) / "document.pdf"
        text = Path(directory) / "document.txt"
        pdf.write_bytes(content)
        try:
            subprocess.run(
                ["pdftotext", "-layout", str(pdf), str(text)],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("pdftotext is required; install poppler-utils") from exc
        return text.read_text(encoding="utf-8", errors="replace")


def parse_date(value: str) -> str:
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", value.strip())
    if not match or match.group(1).lower() not in MONTHS:
        raise ValueError(value)
    return date(
        int(match.group(3)),
        MONTHS[match.group(1).lower()],
        int(match.group(2)),
    ).isoformat()


def infer(text: str, fallback: dict[str, Any]) -> dict[str, Any] | None:
    result = dict(fallback)
    flat = re.sub(r"\s+", " ", text)
    if not result.get("period_end"):
        match = re.search(
            r"(?i)(?:quarter|three months|period)\s+ended\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
            flat,
        )
        if match:
            result["period_end"] = parse_date(match.group(1))
    match = re.search(r"(?i)(?:fiscal\s+)?Q([1-4])\s*(?:FY)?\s*(20\d{2})", flat)
    if match:
        result.setdefault("fiscal_period", "Q" + match.group(1))
        result.setdefault("fiscal_year", int(match.group(2)))
    if not result.get("as_of"):
        dates = re.findall(r"([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})", flat[:4000])
        if dates:
            result["as_of"] = parse_date(dates[0])
    if not result.get("period_end"):
        return None
    result.setdefault("as_of", result["period_end"])
    result.setdefault("document_type", "earnings_presentation")
    return result


def generic(text: str) -> dict[str, dict[str, Any]] | None:
    flat = re.sub(r"\s+", " ", text.replace("–", "-").replace("—", "-"))
    flat = re.sub(r"(?i)\b(low|mid|high)-\s*to-", r"\1-to-", flat)
    patterns = {
        "bit_shipments": (
            r"(?i)(?:NAND\s+)?(?:bit shipments?|bit output|bit sales)\s+(?:were\s+)?"
            r"(?P<dir>up|down|increased|declined|decreased)\s+(?:in\s+)?(?:the\s+)?"
            r"(?P<phrase>(?:low|mid|high)(?:-to-(?:low|mid|high))?[- ]?"
            r"(?:single[- ]digit|double[- ]digit|teens|\d{2}s)|"
            r"(?:approximately|about|around)?\s*\d+(?:\.\d+)?\s*%)"
        ),
        "asp": (
            r"(?i)(?:NAND\s+)?(?:ASP|average selling price|prices?)\s+(?:were\s+)?"
            r"(?P<dir>up|down|increased|declined|decreased)\s+(?:in\s+)?(?:the\s+)?"
            r"(?P<phrase>(?:low|mid|high)(?:-to-(?:low|mid|high))?[- ]?"
            r"(?:single[- ]digit|double[- ]digit|teens|\d{2}s)|"
            r"(?:approximately|about|around)?\s*\d+(?:\.\d+)?\s*%)"
        ),
    }
    for match in re.finditer(r"(?i)\bNAND\b.{0,700}", flat):
        window = match.group(0)
        output: dict[str, dict[str, Any]] = {}
        hits = {name: re.search(pattern, window) for name, pattern in patterns.items()}
        positions = [hit.start() for hit in hits.values() if hit]
        if positions and re.search(r"(?i)\bDRAM\b", window[: min(positions)]):
            continue
        for name, hit in hits.items():
            if not hit:
                continue
            direction = (
                "decline"
                if hit.group("dir").lower() in {"down", "declined", "decreased"}
                else "increase"
            )
            low, high = percentage_interval(hit.group("phrase"), direction=direction)
            output[name] = {
                "value_low": low,
                "value_high": high,
                "reported_text": hit.group(0),
                "reported_phrase": hit.group("phrase"),
            }
        if output:
            return output
    return None


def row(
    source: dict[str, Any],
    period: dict[str, Any],
    concept: str,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    names = {
        "micron": "Micron Technology, Inc.",
        "kioxia-holdings": "KIOXIA Holdings Corporation",
        "sandisk": "Sandisk Corporation",
        "samsung-electronics": "Samsung Electronics Co., Ltd.",
        "sk-hynix": "SK hynix Inc.",
    }
    return {
        "id": f"nand-kpi:{source['entity_id']}:{period['period_end']}:{concept}:actual",
        "entity_id": source["entity_id"],
        "concept_id": concept,
        "value_type": "actual",
        "value_low": parsed["value_low"],
        "value_high": parsed["value_high"],
        "unit": "ratio",
        "period_end": period["period_end"],
        "period_type": "quarter",
        "fiscal_year": period.get("fiscal_year"),
        "fiscal_period": period.get("fiscal_period"),
        "scope": "product",
        "segment": "NAND",
        "as_of": period["as_of"],
        "source_tier": "primary_company",
        "source_name": names.get(source["entity_id"], source["entity_id"]),
        "source_url": period["source_url"],
        "document_form": period.get("document_type"),
        "source_tag": "reported_qualitative_change",
        "reported_text": parsed["reported_text"],
        "reported_phrase": parsed.get("reported_phrase"),
        "normalization_method": BAND_POLICY_ID,
        "assumptions": [
            "Numeric bounds are a deterministic normalization of the preserved company phrase; "
            "the company did not report an exact point value."
        ],
        "quality_flags": ["normalized_qualitative_band"],
    }


def parse_document(
    source: dict[str, Any],
    document: dict[str, Any],
    content: bytes,
    content_type: str,
) -> list[dict[str, Any]]:
    text = (
        pdf_text(content)
        if content_type == "application/pdf" or content.startswith(b"%PDF")
        else content.decode("utf-8", errors="replace")
    )
    period = infer(text, document)
    if not period:
        return []
    period["source_url"] = document["source_url"]
    parsed = (
        extract_micron_nand_kpis(text)
        if source["adapter"] == "micron_prepared_remarks"
        else generic(text)
    )
    if not parsed:
        return []
    output = []
    if parsed.get("asp"):
        output.append(row(source, period, "nand_asp_change_qoq", parsed["asp"]))
    if parsed.get("bit_shipments"):
        output.append(
            row(
                source,
                period,
                "nand_bit_shipments_change_qoq",
                parsed["bit_shipments"],
            )
        )
    return output


def previous_source_map(previous_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = previous_state.get("sources", []) if isinstance(previous_state, dict) else []
    return {
        str(item.get("entity_id")): dict(item)
        for item in sources
        if isinstance(item, dict) and item.get("entity_id")
    }


def add_issue(
    state: dict[str, Any],
    *,
    entity_id: str,
    url: str | None,
    error: Exception | None = None,
    code: str | None = None,
    fatal: bool = False,
) -> None:
    issue = {
        "entity_id": entity_id,
        "url": url,
        "fatal": fatal,
    }
    if error is not None:
        issue.update(
            {
                "code": code or "fetch_or_parse_error",
                "error": type(error).__name__,
                "message": str(error)[:300],
            }
        )
    else:
        issue["code"] = code or "unknown"
    state["issues"].append(issue)


def collect_source(
    source: dict[str, Any],
    previous_source: dict[str, Any],
    rows: dict[str, dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    entity_id = source["entity_id"]
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    previous_documents = previous_document_map(previous_source)
    previous_pages = previous_document_map({"documents": previous_source.get("pages", [])})
    documents = {
        item["source_url"]: {**item, "registered": True}
        for item in source.get("documents", [])
    }
    page_candidates: list[dict[str, Any]] = []
    information: dict[str, Any] = {
        "entity_id": entity_id,
        "checked_urls": [],
        "discovered_urls": [],
        "parsed_documents": [],
        "new_observations": 0,
        "documents": [],
        "pages": [],
        "skipped_documents": [],
        "skipped_pages": [],
    }

    for discovery_url in source.get("discovery_urls", []):
        try:
            body, content_type = fetch(discovery_url)
            information["checked_urls"].append(discovery_url)
            if content_type != "text/html":
                continue
            for item in links(discovery_url, body, source["official_domains"]):
                information["discovered_urls"].append(item["url"])
                candidate = {
                    "source_url": item["url"],
                    "discovery_rank": item["discovery_rank"],
                    "link_text": item["text"],
                }
                if item["url"].lower().endswith(".pdf") or "static-files" in item["url"]:
                    documents.setdefault(item["url"], candidate)
                else:
                    page_candidates.append(candidate)
        except Exception as exc:
            add_issue(
                state,
                entity_id=entity_id,
                url=discovery_url,
                error=exc,
                code="discovery_fetch_failed",
            )

    selected_pages, skipped_pages = select_candidates(
        page_candidates,
        previous_pages,
        limit=PAGE_LIMIT,
    )
    information["skipped_pages"] = skipped_pages
    for page in selected_pages:
        url = page["source_url"]
        previous = previous_pages.get(url)
        try:
            body, content_type = fetch(url)
            information["checked_urls"].append(url)
            digest = content_sha256(body)
            if content_type == "text/html":
                for item in links(url, body, source["official_domains"]):
                    information["discovered_urls"].append(item["url"])
                    if item["url"].lower().endswith(".pdf") or "static-files" in item["url"]:
                        documents.setdefault(
                            item["url"],
                            {
                                "source_url": item["url"],
                                "discovery_rank": item["discovery_rank"],
                                "link_text": item["text"],
                            },
                        )
            information["pages"].append(
                build_document_state(
                    candidate=page,
                    previous=previous,
                    checked_at=checked_at,
                    content_hash=digest,
                    parse_status="parsed",
                )
            )
        except Exception as exc:
            information["pages"].append(
                build_document_state(
                    candidate=page,
                    previous=previous,
                    checked_at=checked_at,
                    content_hash=None,
                    parse_status="error",
                    error=exc,
                )
            )
            add_issue(
                state,
                entity_id=entity_id,
                url=url,
                error=exc,
                code="intermediate_page_failed",
                fatal=previous is None,
            )

    selected_documents, skipped_documents = select_candidates(
        documents.values(),
        previous_documents,
        limit=DOCUMENT_LIMIT,
    )
    information["candidate_document_count"] = len(documents)
    information["selected_document_count"] = len(selected_documents)
    information["skipped_documents"] = skipped_documents

    for document in selected_documents:
        url = document["source_url"]
        previous = previous_documents.get(url)
        try:
            content, content_type = fetch(url)
            information["checked_urls"].append(url)
            digest = content_sha256(content)
            if should_parse_document(previous, digest):
                additions = parse_document(source, document, content, content_type)
                for addition in additions:
                    rows[addition["id"]] = addition
                parse_status = "parsed" if additions else "no_kpi"
            else:
                additions = []
                parse_status = "unchanged"
            if additions:
                information["parsed_documents"].append(url)
                information["new_observations"] += len(additions)
            information["documents"].append(
                build_document_state(
                    candidate=document,
                    previous=previous,
                    checked_at=checked_at,
                    content_hash=digest,
                    parse_status=parse_status,
                    observation_count=len(additions),
                )
            )
        except Exception as exc:
            information["documents"].append(
                build_document_state(
                    candidate=document,
                    previous=previous,
                    checked_at=checked_at,
                    content_hash=None,
                    parse_status="error",
                    error=exc,
                )
            )
            add_issue(
                state,
                entity_id=entity_id,
                url=url,
                error=exc,
                code="document_fetch_or_parse_failed",
                fatal=previous is None,
            )

    selected_urls = {item["source_url"] for item in selected_documents}
    for url, previous in previous_documents.items():
        if url not in selected_urls and url not in documents:
            information["documents"].append(previous)
    information["documents"].sort(key=lambda item: item["source_url"])
    information["pages"].sort(key=lambda item: item["source_url"])
    information["discovered_urls"] = list(dict.fromkeys(information["discovered_urls"]))
    information["checked_urls"] = list(dict.fromkeys(information["checked_urls"]))
    return information


def validate_rows(rows: list[dict[str, Any]]) -> None:
    for item in rows:
        if not str(item.get("source_url", "")).startswith("https://"):
            raise ValueError(f"Non-HTTPS source: {item.get('id')}")
        if (
            item.get("value_type") == "actual"
            and item.get("concept_id")
            in {"nand_asp_change_qoq", "nand_bit_shipments_change_qoq"}
            and (
                not item.get("reported_text")
                or item.get("normalization_method") != BAND_POLICY_ID
            )
        ):
            raise ValueError(f"Untraceable NAND actual: {item.get('id')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    registry = load(SOURCE)
    ledger = load(LEDGER, {"observations": []})
    previous_state = load(STATE, {})
    rows = {item["id"]: item for item in ledger.get("observations", [])}
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    state: dict[str, Any] = {
        "schema_version": "nand-kpi-collection-state.v2",
        "generated_at": generated_at,
        "offline": args.offline,
        "limits": {"pages_per_source": PAGE_LIMIT, "documents_per_source": DOCUMENT_LIMIT},
        "sources": [],
        "freshness": [],
        "issues": [],
    }

    if not args.offline:
        previous_sources = previous_source_map(previous_state)
        for source in registry["sources"]:
            state["sources"].append(
                collect_source(
                    source,
                    previous_sources.get(source["entity_id"], {}),
                    rows,
                    state,
                )
            )

    ordered = sorted(
        rows.values(),
        key=lambda item: (
            item["entity_id"],
            item["period_end"],
            item["concept_id"],
            item["id"],
        ),
    )
    validate_rows(ordered)

    for source in registry["sources"]:
        audit = freshness_audit(ordered, source, today=date.today())
        state["freshness"].append(audit)
        if audit["status"] in {"missing", "stale"}:
            add_issue(
                state,
                entity_id=source["entity_id"],
                url=None,
                code=f"freshness_{audit['status']}",
                fatal=True,
            )

    ledger["observations"] = ordered
    LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    STATE.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    fatal_issues = [item for item in state["issues"] if item.get("fatal")]
    print(
        "nand_kpi_update="
        f"observations={len(ordered)} issues={len(state['issues'])} "
        f"fatal_issues={len(fatal_issues)} offline={args.offline}"
    )
    if fatal_issues:
        raise RuntimeError(
            f"NAND collection failed closed with {len(fatal_issues)} fatal issue(s); see {STATE}"
        )


if __name__ == "__main__":
    main()
