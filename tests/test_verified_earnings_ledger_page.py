from pathlib import Path


PAGE = Path("site/src/pages/ledger.astro")


def source() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_page_requires_verified_revenue_and_lineage_pass():
    text = source()
    assert "revenue.status !== 'PASS'" in text
    assert "lineage.status !== 'PASS'" in text
    assert "revenue.issues?.length" in text
    assert "lineage.issues?.length" in text


def test_page_fails_closed_on_metric_lineage_count_mismatch():
    text = source()
    assert "lineage.checked_metrics_total !== revenue.verified_metrics_total" in text
    assert "throw new Error('Verified revenue and lineage counts differ')" in text


def test_page_exposes_primary_source_and_provenance_fields():
    text = source()
    for field in (
        "metric.source_url",
        "metric.accession_number",
        "metric.period_end",
        "metric.taxonomy",
        "metric.concept",
        "buildSha",
        "revenue.run_at",
    ):
        assert field in text


def test_page_does_not_compute_unverified_growth_or_consensus():
    text = source()
    assert "QoQ" not in text
    assert "YoY" not in text
    assert "consensus_value" not in text
    assert "estimate_value" not in text
    assert "未確認値、推測値、監査失敗値は表示しません" in text
