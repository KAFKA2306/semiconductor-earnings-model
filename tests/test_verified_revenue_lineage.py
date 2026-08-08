import json
from pathlib import Path

from scripts.audit_verified_revenue_lineage import audit


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture_files(tmp_path: Path):
    event = {
        "event_id": "evt1", "company_id": "lam-research", "ticker": "LRCX",
        "accession_number": "0000707549-26-000037", "document_type": "10-K",
        "report_date": "2026-06-28", "freshness": "PASS", "source_adapter": "sec_edgar"
    }
    metric = {
        "event_id": "evt1", "company_id": "lam-research", "ticker": "LRCX",
        "accession_number": "0000707549-26-000037", "document_type": "10-K",
        "period_end": "2026-06-28", "metric": "revenue", "unit": "USD",
        "taxonomy": "us-gaap", "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000707549.json"
    }
    evidence = {"event_id": "evt1", "company_id": "lam-research", "document_type": "10-K", "status": "PASS"}
    events = tmp_path / "events.ndjson"
    metrics = tmp_path / "metrics.json"
    proofs = tmp_path / "evidence.json"
    events.write_text(json.dumps(event) + "\n", encoding="utf-8")
    write_json(metrics, {"status": "PASS", "issues": [], "verified_metrics_total": 1, "metrics": [metric]})
    write_json(proofs, {"status": "PASS", "issues": [], "evidence": [evidence]})
    return events, metrics, proofs


def test_valid_lineage_passes(tmp_path):
    result = audit(*fixture_files(tmp_path))
    assert result["status"] == "PASS"
    assert result["checked_metrics_total"] == 1


def test_missing_event_fails_closed(tmp_path):
    events, metrics, proofs = fixture_files(tmp_path)
    events.write_text("", encoding="utf-8")
    result = audit(events, metrics, proofs)
    assert result["status"] == "FAIL"
    assert "METRIC_WITHOUT_ACCEPTED_EVENT:evt1" in result["issues"]


def test_non_primary_metric_source_fails(tmp_path):
    events, metrics, proofs = fixture_files(tmp_path)
    doc = json.loads(metrics.read_text())
    doc["metrics"][0]["source_url"] = "https://example.com/value.json"
    write_json(metrics, doc)
    result = audit(events, metrics, proofs)
    assert "NON_PRIMARY_METRIC_SOURCE:evt1" in result["issues"]


def test_event_identity_mismatch_fails(tmp_path):
    events, metrics, proofs = fixture_files(tmp_path)
    doc = json.loads(metrics.read_text())
    doc["metrics"][0]["accession_number"] = "wrong"
    write_json(metrics, doc)
    result = audit(events, metrics, proofs)
    assert "METRIC_EVENT_MISMATCH:evt1:accession_number" in result["issues"]


def test_missing_evidence_fails(tmp_path):
    events, metrics, proofs = fixture_files(tmp_path)
    write_json(proofs, {"status": "PASS", "issues": [], "evidence": []})
    result = audit(events, metrics, proofs)
    assert "MISSING_PASS_EVIDENCE:evt1" in result["issues"]


def test_non_fresh_event_fails(tmp_path):
    events, metrics, proofs = fixture_files(tmp_path)
    row = json.loads(events.read_text())
    row["freshness"] = "FAIL"
    events.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = audit(events, metrics, proofs)
    assert "METRIC_EVENT_NOT_FRESH:evt1" in result["issues"]
