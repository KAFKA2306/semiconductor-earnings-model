"""Secondary-only research facts must never masquerade as issuer semiconductor volumes."""
import csv
import unittest
from pathlib import Path

DATA = Path(__file__).parents[1] / "data/raw/chemical_demand/japan_hf_monthly_2026apr_jul.csv"

class NationalHFMonthlySnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with DATA.open(encoding="utf-8", newline="") as f:
            cls.rows = list(csv.DictReader(f))
        cls.values = {(r["period_id"], r["metric"]): int(r["tonnes"]) for r in cls.rows}

    def test_grain_source_and_distinct_series(self):
        self.assertEqual(len(self.rows), 12)
        self.assertEqual(len({r["observation_id"] for r in self.rows}), 12)
        self.assertEqual(len(self.values), 12)
        self.assertEqual({r["period_id"] for r in self.rows}, {"2026-04","2026-05","2026-06","2026-07"})
        for r in self.rows:
            self.assertEqual(r["region"], "Japan national")
            self.assertEqual(r["product_scope"], "hydrofluoric_acid_50pct_equivalent_all_uses")
            self.assertEqual(r["measurement_basis"], "monthly_observed_from_secondary_reprint")
            self.assertEqual(r["verification_status"], "SECONDARY_ONLY_NOT_PRIMARY_VERIFIED")
            self.assertEqual(r["source_access_date"], "2026-10-16")
            self.assertTrue(r["primary_source_locator"].startswith("https://www.e-stat.go.jp/"))
            self.assertTrue(r["secondary_source_url"].startswith("https://www.am-consulting.co.jp/"))
            self.assertGreater(int(r["tonnes"]), 0)

    def test_republished_july_values_and_mom(self):
        self.assertEqual(self.values[("2026-07", "sales_tonnes")], 1143)
        self.assertEqual(self.values[("2026-07", "production_tonnes")], 5028)
        self.assertEqual(self.values[("2026-07", "month_end_inventory_tonnes")], 2508)
        self.assertEqual(self.values[("2026-06", "sales_tonnes")], 1559)
        self.assertAlmostEqual(100*(1143/1559-1), -26.683772, places=4)

if __name__ == "__main__": unittest.main()
