from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_earnings_cross_ledger_identity.py"
SPEC = importlib.util.spec_from_file_location("audit_earnings_cross_ledger_identity", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def sec_event(event_id: str, accession: str, url: str) -> dict[str, object]:
    return {
        "event_id": event_id,
        "source_adapter": "sec_edgar",
        "accession_number": accession,
        "source_url": url,
    }


def test_distinct_ledgers_pass():
    accepted = [sec_event("accepted-a", "0000707549-26-000037", "https://www.sec.gov/a")]
    rejected = [sec_event("rejected-b", "0001193125-26-340226", "https://www.sec.gov/b")]
    result = mod.audit(accepted, rejected)
    assert result["status"] == "PASS"
    assert result["collision_count"] == 0


def test_same_event_id_across_ledgers_fails():
    accepted = [sec_event("same", "0000707549-26-000037", "https://www.sec.gov/a")]
    rejected = [sec_event("same", "0001193125-26-340226", "https://www.sec.gov/b")]
    result = mod.audit(accepted, rejected)
    assert result["status"] == "FAIL"
    assert any(issue["identity"] == "event_id:same" for issue in result["issues"] if issue["code"] == "ACCEPTED_REJECTED_IDENTITY_COLLISION")


def test_same_sec_accession_across_ledgers_fails_even_if_hyphenation_differs():
    accepted = [sec_event("accepted-a", "0000707549-26-000037", "https://www.sec.gov/a")]
    rejected = [sec_event("rejected-b", "000070754926000037", "https://www.sec.gov/b")]
    result = mod.audit(accepted, rejected)
    assert result["status"] == "FAIL"
    assert any(issue["identity"] == "sec_accession:000070754926000037" for issue in result["issues"] if issue["code"] == "ACCEPTED_REJECTED_IDENTITY_COLLISION")


def test_same_primary_url_ignores_fragment_and_host_case():
    accepted = [{"event_id": "accepted-a", "source_adapter": "tdnet_public", "source_url": "https://WWW.RELEASE.TDNET.INFO/inbs/a.pdf#page=1"}]
    rejected = [{"event_id": "rejected-b", "source_adapter": "tdnet_public", "source_url": "https://www.release.tdnet.info/inbs/a.pdf"}]
    result = mod.audit(accepted, rejected)
    assert result["status"] == "FAIL"
    assert any(issue["identity"] == "source_url:https://www.release.tdnet.info/inbs/a.pdf" for issue in result["issues"] if issue["code"] == "ACCEPTED_REJECTED_IDENTITY_COLLISION")


def test_missing_event_id_fails_closed():
    result = mod.audit([{"source_adapter": "sec_edgar", "source_url": "https://www.sec.gov/a"}], [])
    assert result["status"] == "FAIL"
    assert result["issues"][0]["code"] == "MISSING_EVENT_ID"


def test_invalid_url_is_not_invented_but_event_id_still_provides_identity():
    row = {"event_id": "a", "source_adapter": "tdnet_public", "source_url": "not-a-url"}
    assert mod.identity_keys(row) == {"event_id:a"}
