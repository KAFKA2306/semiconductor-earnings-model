from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "earnings_ledger"
PUBLIC = ROOT / "site" / "public" / "api" / "v1" / "earnings-ledger" / "index.json"
OUTPUT = LEDGER / "consensus_separation_audit_latest.json"

# These artifacts are actual-only surfaces. Consensus/estimate data must live in a
# separately sourced and audited contract before it can be introduced anywhere here.
ACTUAL_ONLY_ARTIFACTS = (
    LEDGER / "events.ndjson",
    LEDGER / "verified_revenue_latest.json",
    LEDGER / "verified_revenue_growth_latest.json",
    LEDGER / "publication_latest.json",
    PUBLIC,
)

FORBIDDEN_KEY_TOKENS = (
    "consensus",
    "estimate",
    "estimated",
    "expected",
    "forecast",
    "analyst",
    "street",
    "beat",
    "miss",
    "surprise",
)


def load_payload(path: Path) -> object:
    if path.suffix == ".ndjson":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return json.loads(path.read_text(encoding="utf-8"))


def iter_key_paths(value: object, prefix: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            yield path, str(key)
            yield from iter_key_paths(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_key_paths(child, f"{prefix}[{index}]")


def forbidden_token(key: str) -> str | None:
    normalized = key.lower().replace("-", "_")
    for token in FORBIDDEN_KEY_TOKENS:
        if token in normalized:
            return token
    return None


def audit_artifacts(paths: tuple[Path, ...] = ACTUAL_ONLY_ARTIFACTS) -> dict:
    issues: list[dict] = []
    checked_artifacts: list[str] = []
    checked_keys_total = 0

    for path in paths:
        try:
            relative = str(path.relative_to(ROOT))
        except ValueError:
            relative = str(path)

        if not path.exists():
            issues.append(
                {
                    "code": "ACTUAL_ONLY_ARTIFACT_MISSING",
                    "artifact": relative,
                }
            )
            continue

        checked_artifacts.append(relative)
        try:
            payload = load_payload(path)
        except (json.JSONDecodeError, OSError) as exc:
            issues.append(
                {
                    "code": "ACTUAL_ONLY_ARTIFACT_UNREADABLE",
                    "artifact": relative,
                    "detail": str(exc),
                }
            )
            continue

        for key_path, key in iter_key_paths(payload):
            checked_keys_total += 1
            token = forbidden_token(key)
            if token:
                issues.append(
                    {
                        "code": "CONSENSUS_FIELD_IN_ACTUAL_ONLY_ARTIFACT",
                        "artifact": relative,
                        "key_path": key_path,
                        "matched_token": token,
                    }
                )

    return {
        "schema_version": "earnings-consensus-separation-audit.v1",
        "checked_artifacts": checked_artifacts,
        "checked_artifacts_total": len(checked_artifacts),
        "checked_keys_total": checked_keys_total,
        "forbidden_key_tokens": list(FORBIDDEN_KEY_TOKENS),
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "contract": (
            "Actual-only earnings ledger, verified metrics, derived growth and public API "
            "must not contain consensus or estimate fields. Consensus data requires a separate "
            "source contract and audit before publication."
        ),
    }


def main() -> None:
    payload = audit_artifacts()
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"consensus separation audit: status={payload['status']} "
        f"artifacts={payload['checked_artifacts_total']} keys={payload['checked_keys_total']} "
        f"issues={len(payload['issues'])}"
    )
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
