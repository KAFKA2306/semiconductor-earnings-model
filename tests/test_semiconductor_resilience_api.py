import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts/build_semiconductor_resilience_api.py"
spec = importlib.util.spec_from_file_location("resilience_builder", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def test_scenario_result_preserves_formula_and_runway_bands():
    self_funding = module.scenario_result(1_000, 1_000, 400, module.SCENARIOS[0])
    assert self_funding["stressed_free_cash_flow_usd"] == 360
    assert self_funding["annual_cash_burn_usd"] == 0
    assert self_funding["liquid_reserve_runway_years"] is None
    assert self_funding["runway_band"] == "self_funding"

    burn = module.scenario_result(1_000, 500, 900, module.SCENARIOS[1])
    assert burn["stressed_operating_cash_flow_usd"] == 200
    assert burn["stressed_capital_expenditures_usd"] == 585
    assert burn["annual_cash_burn_usd"] == 385
    assert burn["liquid_reserve_runway_years"] == 2.6
    assert burn["runway_band"] == "two_to_five_years"


def test_choose_tag_rows_prefers_declared_priority_and_latest_filing():
    facts = {
        "Preferred": {
            "units": {
                "USD": [
                    {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "accn": "a", "val": 10},
                    {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "filed": "2025-03-01", "accn": "b", "val": 11},
                ]
            }
        },
        "Fallback": {
            "units": {
                "USD": [
                    {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "filed": "2025-04-01", "accn": "c", "val": 12},
                ]
            }
        },
    }
    tag, rows = module.choose_tag_rows(facts, ("Preferred", "Fallback"), annual=True)
    assert tag == "Preferred"
    assert rows[("2024-01-01", "2024-12-31")]["val"] == 11
