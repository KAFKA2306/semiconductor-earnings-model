from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OWNER_PATH = ROOT / "scripts" / "edinetdb_quota_owner.py"
DEFAULT_USAGE = ROOT / "data" / "edinetdb_quota" / "usage.json"
DEFAULT_REGISTRY = ROOT / "config" / "edinetdb_consumer_registry.json"

SPEC = importlib.util.spec_from_file_location("edinetdb_quota_owner", OWNER_PATH)
assert SPEC and SPEC.loader
owner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = owner
SPEC.loader.exec_module(owner)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_usage(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": "edinetdb.quota-usage.v1",
            "days": {},
            "months": {},
            "reservations": [],
        }
    payload = load_json(path)
    if payload.get("schema_version") != "edinetdb.quota-usage.v1":
        raise ValueError("unsupported EDINETDB quota usage schema")
    payload.setdefault("days", {})
    payload.setdefault("months", {})
    payload.setdefault("reservations", [])
    return payload


def write_usage(path: Path, usage: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(usage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_consumer_registry(
    config: dict[str, Any],
    registry: dict[str, Any],
    plan: list[Any],
) -> None:
    if registry.get("schema_version") != "edinetdb.consumer-registry.v1":
        raise ValueError("unsupported EDINETDB consumer registry schema")
    quota_owner = config.get("policy", {}).get("quota_owner")
    if registry.get("quota_owner") != quota_owner:
        raise ValueError("quota owner differs between plan and consumer registry")

    repositories = registry.get("repositories", {})
    if repositories.get(quota_owner, {}).get("edinetdb_mode") != "quota_owner":
        raise ValueError("quota owner must be registered with edinetdb_mode=quota_owner")

    allowed_modes = {"quota_owner", "projection_only"}
    for request in plan:
        for projection in request.projections:
            entry = repositories.get(projection.consumer)
            if entry is None:
                raise ValueError(f"unregistered EDINETDB consumer: {projection.consumer}")
            mode = entry.get("edinetdb_mode")
            if mode not in allowed_modes:
                raise ValueError(
                    f"EDINETDB consumer {projection.consumer} is {mode}; "
                    "only quota_owner/projection_only repositories may enter the fetch plan"
                )
            if mode == "quota_owner" and projection.consumer != quota_owner:
                raise ValueError("only the configured quota owner may use quota_owner mode")


def anticipated_network_attempts(
    plan: list[Any],
    ledger: dict[str, Any],
    day: str,
    projections_root: Path,
    *,
    force: bool,
) -> int:
    if force:
        return len(plan)
    return sum(
        1
        for request in plan
        if not owner.already_materialized(ledger, day, request, projections_root)
    )


def validate_budget(
    config: dict[str, Any],
    usage: dict[str, Any],
    day: str,
    anticipated_attempts: int,
) -> None:
    if anticipated_attempts < 0:
        raise ValueError("anticipated_attempts cannot be negative")

    daily_limit = int(config["daily_limit"])
    daily_reserve = int(config["reserve_requests"])
    monthly_limit = int(config["monthly_limit"])
    monthly_reserve = int(config.get("monthly_reserve_requests", 0))
    daily_usable = daily_limit - daily_reserve
    monthly_usable = monthly_limit - monthly_reserve
    if daily_usable <= 0 or monthly_usable <= 0:
        raise ValueError("invalid EDINETDB quota limits/reserves")

    month = day[:7]
    day_used = int(usage.get("days", {}).get(day, 0))
    month_used = int(usage.get("months", {}).get(month, 0))
    if day_used + anticipated_attempts > daily_usable:
        raise ValueError(
            f"daily self-managed EDINETDB budget exceeded: used={day_used}, "
            f"anticipated={anticipated_attempts}, usable={daily_usable}"
        )
    if month_used + anticipated_attempts > monthly_usable:
        raise ValueError(
            f"monthly self-managed EDINETDB budget exceeded: used={month_used}, "
            f"anticipated={anticipated_attempts}, usable={monthly_usable}"
        )


def reserve_usage(
    usage: dict[str, Any],
    day: str,
    attempts: int,
    reservation_id: str,
) -> None:
    month = day[:7]
    usage.setdefault("days", {})[day] = int(usage.get("days", {}).get(day, 0)) + attempts
    usage.setdefault("months", {})[month] = int(usage.get("months", {}).get(month, 0)) + attempts
    usage.setdefault("reservations", []).append(
        {
            "id": reservation_id,
            "day": day,
            "month": month,
            "attempts_reserved": attempts,
            "status": "reserved",
            "created_at": now_utc(),
        }
    )


def set_reservation_status(
    usage: dict[str, Any], reservation_id: str, status: str
) -> None:
    for reservation in reversed(usage.get("reservations", [])):
        if reservation.get("id") == reservation_id:
            reservation["status"] = status
            reservation["updated_at"] = now_utc()
            return
    raise ValueError(f"quota reservation not found: {reservation_id}")


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    ledger_path = Path(args.ledger)
    projections_root = Path(args.projections)
    usage_path = Path(args.usage)
    registry_path = Path(args.registry)

    config = owner.load_json(plan_path)
    plan = owner.build_plan(config)
    owner.validate_plan(config, plan)
    registry = load_json(registry_path)
    validate_consumer_registry(config, registry, plan)

    day = args.day or owner.today_utc()
    ledger = owner.load_ledger(ledger_path)
    attempts = anticipated_network_attempts(
        plan,
        ledger,
        day,
        projections_root,
        force=args.force,
    )
    usage = load_usage(usage_path)
    validate_budget(config, usage, day, attempts)

    owner.print_plan(config, plan, day=day)
    month = day[:7]
    print(f"anticipated_network_attempts={attempts}")
    print(f"self_managed_day_used={usage['days'].get(day, 0)}")
    print(f"self_managed_month_used={usage['months'].get(month, 0)}")

    if args.plan_only:
        return 0
    if attempts == 0:
        print("No EDINETDB network attempt required; projections are already materialized.")
        return 0

    reservation_id = f"{day}:{now_utc()}:{attempts}"
    reserve_usage(usage, day, attempts, reservation_id)
    write_usage(usage_path, usage)

    try:
        result = owner.run(args)
    except Exception:
        usage = load_usage(usage_path)
        set_reservation_status(usage, reservation_id, "failed_or_partial")
        write_usage(usage_path, usage)
        raise

    usage = load_usage(usage_path)
    set_reservation_status(usage, reservation_id, "completed")
    write_usage(usage_path, usage)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail-close quota guard for the shared EDINETDB quota owner."
    )
    parser.add_argument("--plan", default=str(owner.DEFAULT_PLAN))
    parser.add_argument("--ledger", default=str(owner.DEFAULT_LEDGER))
    parser.add_argument("--projections", default=str(owner.DEFAULT_PROJECTIONS))
    parser.add_argument("--usage", default=str(DEFAULT_USAGE))
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--day")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        sys.exit(run(parse_args()))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
