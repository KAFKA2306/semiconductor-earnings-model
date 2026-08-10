from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "edinetdb_quota_guard.py"
SPEC = importlib.util.spec_from_file_location("edinetdb_quota_guard", MODULE_PATH)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


def load_plan() -> dict:
    return json.loads((ROOT / "config" / "edinetdb_quota_plan.json").read_text(encoding="utf-8"))


def load_registry() -> dict:
    return json.loads((ROOT / "config" / "edinetdb_consumer_registry.json").read_text(encoding="utf-8"))


def test_current_plan_consumers_are_registry_allowed() -> None:
    config = load_plan()
    plan = guard.owner.build_plan(config)
    guard.validate_consumer_registry(config, load_registry(), plan)
    consumers = {spec.consumer for request in plan for spec in request.projections}
    assert consumers == {
        "KAFKA2306/semiconductor-earnings-model",
        "KAFKA2306/factory",
        "KAFKA2306/investor2",
    }


def test_not_applicable_repo_cannot_enter_edinetdb_plan() -> None:
    config = load_plan()
    config["requests"] = [
        *config["requests"],
        {
            "id": "books-must-not-fetch",
            "consumer": "KAFKA2306/books",
            "method": "GET",
            "path": "/v1/companies/E02144/financials",
            "params": {"period": "annual", "years": "6"},
            "projection_fields": ["fiscal_year"],
        },
    ]
    plan = guard.owner.build_plan(config)
    try:
        guard.validate_consumer_registry(config, load_registry(), plan)
    except ValueError as exc:
        assert "not_applicable" in str(exc)
    else:
        raise AssertionError("not_applicable repository must not consume EDINETDB")


def test_monthly_budget_is_fail_closed() -> None:
    config = load_plan()
    usable = config["monthly_limit"] - config["monthly_reserve_requests"]
    usage = {
        "schema_version": "edinetdb.quota-usage.v1",
        "days": {},
        "months": {"2026-08": usable},
        "reservations": [],
    }
    try:
        guard.validate_budget(config, usage, "2026-08-10", 1)
    except ValueError as exc:
        assert "monthly" in str(exc)
    else:
        raise AssertionError("monthly budget overflow must fail before network access")


def test_daily_budget_is_fail_closed() -> None:
    config = load_plan()
    usable = config["daily_limit"] - config["reserve_requests"]
    usage = {
        "schema_version": "edinetdb.quota-usage.v1",
        "days": {"2026-08-10": usable},
        "months": {},
        "reservations": [],
    }
    try:
        guard.validate_budget(config, usage, "2026-08-10", 1)
    except ValueError as exc:
        assert "daily" in str(exc)
    else:
        raise AssertionError("daily budget overflow must fail before network access")


def test_force_reserves_all_unique_requests(tmp_path: Path) -> None:
    config = load_plan()
    plan = guard.owner.build_plan(config)
    assert guard.anticipated_network_attempts(
        plan,
        {"schema_version": "edinetdb.quota-ledger.v1", "days": {}},
        "2026-08-10",
        tmp_path,
        force=True,
    ) == 3


def test_reservation_counts_attempts_even_before_result() -> None:
    usage = {
        "schema_version": "edinetdb.quota-usage.v1",
        "days": {},
        "months": {},
        "reservations": [],
    }
    guard.reserve_usage(usage, "2026-08-10", 3, "r1")
    assert usage["days"]["2026-08-10"] == 3
    assert usage["months"]["2026-08"] == 3
    assert usage["reservations"][0]["status"] == "reserved"
