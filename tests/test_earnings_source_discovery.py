from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "earnings_source_discovery.py"
spec = importlib.util.spec_from_file_location("earnings_source_discovery", MODULE_PATH)
assert spec and spec.loader
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)


def row(accession: str, accepted: str, form: str = "10-Q", items: str | None = None) -> dict:
    return {
        "accessionNumber": accession,
        "filingDate": accepted[:4] + "-" + accepted[4:6] + "-" + accepted[6:8],
        "acceptanceDateTime": accepted,
        "form": form,
        "primaryDocument": "document.htm",
        "primaryDocDescription": "Quarterly report",
        "items": items,
    }


def test_last_seen_stops_history_and_non_earnings_8k_is_filtered():
    rows = [
        row("new-10q", "20260808100000"),
        row("noise-8k", "20260808090000", form="8-K", items="1.01"),
        row("last-seen", "20260807090000"),
        row("older", "20260806090000"),
    ]
    selected = discovery.select_new_sec_rows(
        rows,
        last_seen_id="last-seen",
        now=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
    )
    assert [x["accessionNumber"] for x in selected] == ["new-10q"]


def test_bootstrap_is_bounded_instead_of_treating_full_history_as_new():
    rows = [
        row("recent", "20260808100000"),
        row("too-old", "20260801090000"),
    ]
    selected = discovery.select_new_sec_rows(
        rows,
        last_seen_id=None,
        now=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
        bootstrap_hours=72,
    )
    assert [x["accessionNumber"] for x in selected] == ["recent"]


def test_sec_archive_url_is_deterministic():
    assert discovery.sec_archive_url("0001045810", "0001045810-26-000001", "nvda.htm") == (
        "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/nvda.htm"
    )
