import importlib.util
import math
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "publish_investor2_jquants_private.py"
SPEC = importlib.util.spec_from_file_location("publish_investor2_jquants_private", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PrivateJQuantsTests(unittest.TestCase):
    def test_normalize_prefers_adjusted_values(self):
        bar = MODULE.normalize_bar({
            "Date": "2026-01-05",
            "Code": "72030",
            "O": 100,
            "H": 120,
            "L": 90,
            "C": 110,
            "Vo": 1000,
            "AdjO": 50,
            "AdjH": 60,
            "AdjL": 45,
            "AdjC": 55,
            "AdjVo": 2000,
        })
        self.assertEqual(bar["close"], 55.0)
        self.assertEqual(bar["open"], 50.0)
        self.assertEqual(bar["volume"], 2000.0)

    def test_analyze_known_series(self):
        bars = [
            {"date": "2026-01-01", "close": 100.0},
            {"date": "2026-01-02", "close": 120.0},
            {"date": "2026-01-03", "close": 90.0},
            {"date": "2026-01-04", "close": 108.0},
        ]
        result = MODULE.analyze_bars(bars)
        self.assertEqual(result["row_count"], 4)
        self.assertAlmostEqual(result["period_return_pct"], 8.0)
        self.assertAlmostEqual(result["max_drawdown_pct"], -25.0)
        self.assertTrue(math.isfinite(result["annualized_volatility_pct"]))

    def test_hash_is_order_stable_for_objects(self):
        self.assertEqual(
            MODULE.canonical_hash({"b": 2, "a": 1}),
            MODULE.canonical_hash({"a": 1, "b": 2}),
        )


if __name__ == "__main__":
    unittest.main()
