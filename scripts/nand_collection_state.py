from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Iterable

_DATE_PATTERNS = (
    re.compile(r"(?P<year>20\d{2})[-_/](?P<month>0?[1-9]|1[0-2])[-_/](?P<day>0?[1-9]|[12]\d|3[01])"),
    re.compile(r"(?<!\d)(?P<year>20\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])(?!\d)"),
)


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def date_from_url(url: str) -> date | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(url)
        if not match:
            continue
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
    return None


def candidate_date(candidate: dict[str, Any]) -> date | None:
    return (
        parse_date(candidate.get("period_end"))
        or parse_date(candidate.get("as_of"))
        or date_from_url(str(candidate.get("source_url") or ""))
    )


def previous_document_map(previous_source_state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(previous_source_state, dict):
        return {}
    documents = previous_source_state.get("documents", [])
    if not isinstance(documents, list):
        return {}
    return {
        str(item.get("source_url")): dict(item)
        for item in documents
        if isinstance(item, dict) and item.get("source_url")
    }


def _discovery_rank(candidate: dict[str, Any]) -> int:
    value = candidate.get("discovery_rank")
    return value if isinstance(value, int) and value >= 0 else 10**9


def _prefer_candidate(
    candidate: dict[str, Any],
    existing: dict[str, Any],
) -> bool:
    candidate_observed = candidate_date(candidate)
    existing_observed = candidate_date(existing)
    if candidate_observed is not None and existing_observed is None:
        return True
    if candidate_observed is None and existing_observed is not None:
        return False
    if candidate_observed is not None and existing_observed is not None:
        if candidate_observed != existing_observed:
            return candidate_observed > existing_observed
    return _discovery_rank(candidate) < _discovery_rank(existing)


def prioritize_candidates(
    candidates: Iterable[dict[str, Any]],
    previous_documents: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return unique candidates with unprocessed and recent documents first.

    Ordering never depends on dictionary insertion order or URL lexical order.
    A document absent from the persisted collection state is always considered
    before a previously checked document. Within each group, explicit reporting
    dates and dates embedded in URLs are sorted newest first. If dates are not
    available, the source page's discovery order is used.
    """
    unique: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        url = str(raw.get("source_url") or "")
        if not url:
            continue
        candidate = dict(raw)
        candidate["source_url"] = url
        existing = unique.get(url)
        if existing is None or _prefer_candidate(candidate, existing):
            unique[url] = candidate

    def key(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
        url = candidate["source_url"]
        previous = previous_documents.get(url)
        processed = bool(
            previous
            and previous.get("parse_status") in {"parsed", "no_kpi", "unchanged"}
        )
        observed_date = candidate_date(candidate)
        ordinal = observed_date.toordinal() if observed_date else 0
        return (
            1 if processed else 0,
            -ordinal,
            _discovery_rank(candidate),
            url,
        )

    return sorted(unique.values(), key=key)


def select_candidates(
    candidates: Iterable[dict[str, Any]],
    previous_documents: dict[str, dict[str, Any]],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if limit < 1:
        raise ValueError("candidate limit must be positive")
    ordered = prioritize_candidates(candidates, previous_documents)
    selected = ordered[:limit]
    skipped = [
        {
            "source_url": item["source_url"],
            "reason": "candidate_limit",
            "candidate_date": (
                candidate_date(item).isoformat() if candidate_date(item) else None
            ),
            "previously_processed": item["source_url"] in previous_documents,
        }
        for item in ordered[limit:]
    ]
    return selected, skipped


def should_parse_document(
    previous: dict[str, Any] | None,
    current_content_sha256: str,
) -> bool:
    if not previous:
        return True
    if previous.get("content_sha256") != current_content_sha256:
        return True
    return previous.get("parse_status") not in {"parsed", "no_kpi", "unchanged"}


def build_document_state(
    *,
    candidate: dict[str, Any],
    previous: dict[str, Any] | None,
    checked_at: str,
    content_hash: str | None,
    parse_status: str,
    observation_count: int = 0,
    error: Exception | None = None,
) -> dict[str, Any]:
    discovered_at = (
        previous.get("first_discovered_at")
        if previous and previous.get("first_discovered_at")
        else checked_at
    )
    result = {
        "source_url": candidate["source_url"],
        "first_discovered_at": discovered_at,
        "last_checked_at": checked_at,
        "content_sha256": content_hash,
        "parse_status": parse_status,
        "period_end": candidate.get("period_end"),
        "as_of": candidate.get("as_of"),
        "observation_count": observation_count,
        "retry_count": int(previous.get("retry_count", 0)) if previous else 0,
    }
    if error is not None:
        result["retry_count"] += 1
        result["error_type"] = type(error).__name__
        result["error_message"] = str(error)[:300]
    return result


def freshness_audit(
    observations: Iterable[dict[str, Any]],
    source: dict[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    entity_id = str(source["entity_id"])
    relevant_dates = [
        parsed
        for row in observations
        if row.get("entity_id") == entity_id
        for parsed in [parse_date(row.get("period_end"))]
        if parsed is not None
    ]
    latest = max(relevant_dates) if relevant_dates else None
    max_age_days = source.get("max_observation_age_days")
    required = bool(source.get("require_current_observation", False))
    age_days = (today - latest).days if latest else None
    status = "not_enforced"
    if required and latest is None:
        status = "missing"
    elif (
        required
        and isinstance(max_age_days, int)
        and age_days is not None
        and age_days > max_age_days
    ):
        status = "stale"
    elif required:
        status = "fresh"
    return {
        "entity_id": entity_id,
        "required": required,
        "max_observation_age_days": max_age_days,
        "latest_period_end": latest.isoformat() if latest else None,
        "age_days": age_days,
        "status": status,
    }
