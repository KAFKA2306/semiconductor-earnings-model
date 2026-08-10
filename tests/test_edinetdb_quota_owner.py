from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "edinetdb_quota_owner.py"
SPEC = importlib.util.spec_from_file_location("edinetdb_quota_owner", MODULE_PATH)
assert SPEC and SPEC.loader
quota_owner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quota_owner)


def load_plan() -> dict:
    return json.loads((ROOT / "config" / "edinetdb_quota_plan.json").read_text(encoding="utf-8"))


def test_initial_plan_uses_only_three_authenticated_requests() -> None:
    config = load_plan()
    plan = quota_owner.build_plan(config)
    quota_owner.validate_plan(config, plan)
    assert len(plan) == 3
    assert len(plan) <= config["daily_limit"] - config["reserve_requests"]


def test_company_master_batches_multiple_companies_into_one_request() -> None:
    plan = quota_owner.build_plan(load_plan())
    master = next(item for item in plan if item.path == "/v1/companies")
    codes = [value for key, value in master.params if key == "edinet_code"]
    assert codes == ["E02144", "E35948"]
    assert len(codes) <= quota_owner.MAX_MASTER_CODES_PER_REQUEST


def test_company_master_projection_does_not_cross_leak_consumers() -> None:
    plan = quota_owner.build_plan(load_plan())
    master = next(item for item in plan if item.path == "/v1/companies")
    specs = {item.consumer: item for item in master.projections}
    assert specs["KAFKA2306/factory"].edinet_codes == ("E02144",)
    assert specs["KAFKA2306/semiconductor-earnings-model"].edinet_codes == ("E35948",)


def test_duplicate_identical_requests_are_coalesced() -> None:
    config = load_plan()
    duplicate = dict(config["requests"][0])
    duplicate["id"] = "same-request-other-consumer"
    duplicate["consumer"] = "KAFKA2306/investor2"
    config["requests"] = [*config["requests"], duplicate]
    plan = quota_owner.build_plan(config)
    assert len(plan) == 3
    toyota = next(item for item in plan if item.path.endswith("E02144/financials"))
    assert {spec.consumer for spec in toyota.projections} == {
        "KAFKA2306/factory",
        "KAFKA2306/investor2",
    }


def test_projection_keeps_only_declared_fields() -> None:
    spec = quota_owner.ProjectionSpec(
        consumer="KAFKA2306/factory",
        projection_id="example",
        fields=("edinet_code", "name"),
        edinet_codes=("E02144",),
    )
    payload = {
        "data": {
            "companies": [
                {"edinet_code": "E02144", "name": "Toyota", "secret_extra": "drop"},
                {"edinet_code": "E35948", "name": "Kioxia", "secret_extra": "drop"},
            ]
        }
    }
    assert quota_owner.build_projection(payload, spec) == [
        {"edinet_code": "E02144", "name": "Toyota"}
    ]


def test_same_day_success_reuses_existing_projection(tmp_path: Path) -> None:
    config = load_plan()
    request = quota_owner.build_plan(config)[0]
    projection_root = tmp_path / "projections"
    for spec in request.projections:
        path = quota_owner.projection_path(projection_root, spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    ledger = {
        "schema_version": "edinetdb.quota-ledger.v1",
        "days": {
            "2026-08-10": {
                "requests": {
                    request.fingerprint: {"status": "success"}
                }
            }
        },
    }
    assert quota_owner.already_materialized(
        ledger, "2026-08-10", request, projection_root
    )
