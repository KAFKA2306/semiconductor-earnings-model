"""Deterministic audit of the semiconductor high-purity HF quarterly quantity snapshot."""

import csv
import unittest
from datetime import date
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "data/raw/chemical_demand/stella_hf_quantity_20261016.csv"


class StellaHFQuantityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with FILE.open(encoding="utf-8", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))
        cls.by_id = {r["observation_id"]: r for r in cls.rows}

    def test_unique_scope_sources_and_periods(self):
        self.assertEqual(len(self.rows), 10)
        self.assertEqual(len(self.by_id), len(self.rows))
        keys = set()
        for row in self.rows:
            self.assertEqual(row["company_id"], "4109")
            self.assertEqual(row["product_scope"], "semiconductor_high_purity_hydrofluoric_acid")
            self.assertIn(row["grain"], {"quarter", "fiscal_year"})
            self.assertIn(row["value_type"], {"issuer_actual", "derived_difference"})
            self.assertTrue(row["source_url"].startswith("https://www.stella-chemifa.co.jp/"))
            self.assertGreater(int(row["value_t"]), 0)
            self.assertLessEqual(date.fromisoformat(row["period_start"]), date.fromisoformat(row["period_end"]))
            key = (row["product_scope"], row["grain"], row["period_start"], row["period_end"])
            self.assertNotIn(key, keys)
            keys.add(key)

    def test_quarter_grain_reconciliation(self):
        value = lambda x: int(self.by_id[x]["value_t"])
        qs = [value(f"STELLA_HF_FY2026_Q{q}") for q in (1, 2, 3, 4)]
        self.assertEqual(qs, [18500, 18400, 18300, 18600])
        self.assertEqual(sum(qs), value("STELLA_HF_FY2026"))
        self.assertEqual(qs[0] + qs[1], 36900)
        self.assertEqual(sum(qs[:3]), 55200)
        self.assertEqual(value("STELLA_HF_FY2026_Q2"), 36900 - qs[0])
        self.assertEqual(value("STELLA_HF_FY2026_Q4"), 73800 - sum(qs[:3]))

    def test_year_over_year_quantity(self):
        before = int(self.by_id["STELLA_HF_FY2026_Q1"]["value_t"])
        after = int(self.by_id["STELLA_HF_FY2027_Q1"]["value_t"])
        self.assertAlmostEqual((after / before - 1) * 100, 1.081081081, places=5)

    def test_derived_and_observed_distinct(self):
        for key in ["STELLA_HF_FY2026_Q2", "STELLA_HF_FY2026_Q4"]:
            self.assertEqual(self.by_id[key]["value_type"], "derived_difference")
        for key in ["STELLA_HF_FY2026_Q1", "STELLA_HF_FY2026_Q3", "STELLA_HF_FY2027_Q1"]:
            self.assertEqual(self.by_id[key]["value_type"], "issuer_actual")


if __name__ == "__main__":
    unittest.main()
