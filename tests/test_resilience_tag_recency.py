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
