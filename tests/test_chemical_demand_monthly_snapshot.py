"""Contract tests for the source-traceable monthly demand research snapshot."""

import csv
import unittest
from collections import Counter
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "data/raw/chemical_demand/monthly_20261015.csv"
IDENTITY = ("company_id", "scope_id", "metric_code", "unit_id", "observation_basis", "period_id")


class MonthlyChemicalDemandSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with FILE.open(encoding="utf-8", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))
        cls.by_key = {(r["company_id"], r["period_id"]): r for r in cls.rows}

    def test_complete_monthly_snapshot_without_duplicate_observations(self):
        self.assertEqual(len(self.rows), 66)
        self.assertEqual(len(set(r["observation_id"] for r in self.rows)), 66)
        self.assertEqual(len({tuple(r[k] for k in IDENTITY) for r in self.rows}), 66)
        counts = Counter(r["company_id"] for r in self.rows)
        self.assertEqual(counts, {"TSMC": 21, "UMC": 21, "SANFU": 21, "SIA": 3})
        for company in ("TSMC", "UMC", "SANFU"):
            periods = {r["period_id"] for r in self.rows if r["company_id"] == company}
            self.assertEqual(len({p for p in periods if p.startswith("2025M")}), 12)
            self.assertEqual(len({p for p in periods if p.startswith("2026M")}), 9)

    def test_provenance_and_signal_type_are_not_conflated(self):
        for r in self.rows:
            self.assertTrue(r["source_id"] and r["source_url"].startswith("https://"))
            self.assertEqual(r["metric_code"], "revenue")
            self.assertTrue(r["period_id"][:4].isdigit() and r["period_id"][4] == "M")
            self.assertIn(r["observation_basis"], {"month_actual", "trailing_3m_mean"})
            self.assertNotIn(r["signal_tier"], {"chemical_shipment_quantity", "semiconductor_chemical_volume"})
        self.assertEqual({r["observation_basis"] for r in self.rows if r["company_id"] == "SIA"}, {"trailing_3m_mean"})
        self.assertEqual({r["observation_basis"] for r in self.rows if r["company_id"] != "SIA"}, {"month_actual"})
        self.assertEqual(self.by_key[("SANFU", "2026M09")]["source_type"], "secondary_company_disclosure")
        self.assertEqual(self.by_key[("UMC", "2026M09")]["source_type"], "secondary_company_disclosure")

    def test_september_revenue_yoy_has_matching_basis_and_units(self):
        for company, expected in (("TSMC", 54.65), ("UMC", 27.22), ("SANFU", 16.22)):
            older = self.by_key[(company, "2025M09")]
            newer = self.by_key[(company, "2026M09")]
            for field in ("scope_id", "metric_code", "unit_id", "observation_basis"):
                self.assertEqual(older[field], newer[field])
            yoy = (float(newer["value"]) / float(older["value"]) - 1) * 100
            self.assertAlmostEqual(yoy, expected, delta=0.02)


if __name__ == "__main__":
    unittest.main()
