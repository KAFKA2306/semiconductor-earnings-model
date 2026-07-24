import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "build_semiconductor_resilience_api_v2.py"
spec = importlib.util.spec_from_file_location("resilience_v2", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def instant(value, end, filed, accession):
    return {"form": "10-K", "end": end, "filed": filed, "accn": accession, "val": value}


def annual(value, start, end, filed, accession):
    return {"form": "10-K", "start": start, "end": end, "filed": filed, "accn": accession, "val": value}


def test_newer_fallback_tag_beats_stale_preferred_tag():
    facts = {
        "Preferred": {"units": {"USD": [instant(10, "2012-01-29", "2012-03-01", "old")]}},
        "Fallback": {"units": {"USD": [
            instant(20, "2024-01-28", "2024-03-01", "new-1"),
            instant(30, "2025-01-26", "2025-03-01", "new-2"),
        ]}},
    }
    tag, rows = module.choose_recency_aware_tag_rows(facts, ("Preferred", "Fallback"), annual=False)
    assert tag == "Fallback"
    assert max(rows) == "2025-01-26"


def test_declared_priority_breaks_equal_recency_and_history_ties():
    facts = {
        "Preferred": {"units": {"USD": [instant(10, "2025-01-26", "2025-03-01", "a")]}},
        "Fallback": {"units": {"USD": [instant(20, "2025-01-26", "2025-03-02", "b")]}},
    }
    tag, rows = module.choose_recency_aware_tag_rows(facts, ("Preferred", "Fallback"), annual=False)
    assert tag == "Preferred"
    assert rows["2025-01-26"]["val"] == 10


def test_legacy_revenues_request_expands_to_newer_standard_revenue_tag():
    facts = {
        "Revenues": {"units": {"USD": [annual(10, "2011-01-31", "2012-01-29", "2012-03-01", "old")]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            annual(20, "2024-01-29", "2025-01-26", "2025-03-01", "new")
        ]}},
    }
    tag, rows = module.choose_recency_aware_tag_rows(facts, ("Revenues",), annual=True)
    assert tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert max(period[1] for period in rows) == "2025-01-26"


def test_property_plant_equipment_request_expands_to_productive_assets():
    facts = {
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
            annual(10, "2011-01-31", "2012-01-29", "2012-03-01", "old")
        ]}},
        "PaymentsToAcquireProductiveAssets": {"units": {"USD": [
            annual(20, "2024-01-29", "2025-01-26", "2025-03-01", "new-1"),
            annual(30, "2025-01-27", "2026-01-25", "2026-03-01", "new-2"),
        ]}},
    }
    tag, rows = module.choose_recency_aware_tag_rows(
        facts,
        ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForAdditionsToPropertyPlantAndEquipment"),
        annual=True,
    )
    assert tag == "PaymentsToAcquireProductiveAssets"
    assert max(period[1] for period in rows) == "2026-01-25"
