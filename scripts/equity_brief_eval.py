"""Independent benchmark checks for the historical NAND case."""
import argparse
import json
import math
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

RUNNER = Path(__file__).with_name("equity_brief.py")


def validate(payload):
    rows = payload["valuation"]
    first = rows[0]
    checks = {
        "share_value": float(first["equity_value"]) == 14_529_010_506_834,
        "consensus_pe": math.isclose(first["consensus_pe"], 2.65892953445, abs_tol=1e-9),
        "required_q4": math.isclose(first["implied_q4_profit"], 2_253_733_202_733.6, abs_tol=1),
        "interim_dividend": first["dividend"] == 30,
        "excess_capital": float(first["excess_return_percent"]) == 100,
        "bain_last_sale": math.isclose(first["june11_price"], 22_230.14, abs_tol=0.001),
        "bain_last_sale_order": first["june11_price"] < first["june4_price"],
        "cayman2_distinct_holder": float(first["cayman2_holding"]) == 14.53,
        "explicit_unknown": any("非開示" in item or "開示されていない" in item for item in payload["unknowns"]),
        "scenario_direction": all(a["normal_annual_fcfe_required"] > b["normal_annual_fcfe_required"]
                                  for a, b in zip(rows, rows[1:])),
        "provenance": len(payload["evidence"]) == len(payload["facts"]) and all(
            row["evidence_id"] in payload["evidence"] and row["period"] and row["unit"]
            for row in payload["facts"]),
        "zero_tokens": payload["usage"] == {"model_calls": 0, "input_tokens": 0, "output_tokens": 0},
    }
    return checks


def evaluate(command, snapshot_dir):
    first = subprocess.check_output(command)
    second = subprocess.check_output(command)
    payload = json.loads(first)
    checks = validate(payload)
    checks["stable_replay"] = first == second
    with tempfile.TemporaryDirectory() as tmp:
        empty = [*command]
        empty[empty.index("--state") + 1] = tmp
        checks["missing_snapshot_fails_closed"] = subprocess.run(empty, capture_output=True).returncode != 0
        amended = [*command]
        ledger = Path(snapshot_dir)
        evidence = next(v for v in payload["evidence"].values() if v["field"] == "fy_consensus")
        correction = Path(tmp) / "correction.json"
        correction.write_text(json.dumps([{
            "source": "ifis", "tier": "market", "url": evidence["url"] + "&revision=fixture",
            "published_at": "2026-11-16T10:00:00+09:00",
        }]))
        checks["future_amendment_excluded"] = subprocess.check_output(
            [*amended, "--corrections", str(correction)]
        ) == first
        from datetime import datetime
        from equity_brief import active_documents, digest, encoded, save

        spec = json.loads(Path(command[command.index("--spec") + 1]).read_text())
        future = "2026-11-16T10:00:00+09:00"
        corrections = json.loads(correction.read_text())
        updated = active_documents(spec, datetime.fromisoformat(future), corrections)
        checks["amendment_selected_at_publication"] = updated["ifis"]["url"].endswith("&revision=fixture")

        fixture = Path(tmp) / "amended_snapshot"
        shutil.copytree(ledger / "objects", fixture / "objects")
        stamps = {key: next(v["sha256"] for v in payload["evidence"].values()
                            if v["url"] == original[0])
                  for key, original in spec["documents"].items()}
        original_html = (fixture / "objects" / stamps["ifis"]).read_bytes()
        corrected_html = original_html.replace(b"5,464,233", b"5,400,000")
        stamps["ifis"] = digest(corrected_html)
        save(fixture / "objects" / stamps["ifis"], corrected_html)
        snapshot = {key: {**entry, "sha256": stamps[key]} for key, entry in updated.items()}
        save(fixture / "snapshots" / f"{digest(encoded(updated))}.json", encoded(snapshot))
        amended[amended.index("--state") + 1] = str(fixture)
        amended[amended.index("--as-of") + 1] = future
        after = json.loads(subprocess.check_output([*amended, "--corrections", str(correction)]))
        checks["amendment_changes_derived_pe"] = (
            float(after["valuation"][0]["consensus"]) == 5_400_000_000_000
            and after["valuation"][0]["consensus_pe"] > payload["valuation"][0]["consensus_pe"]
        )
        save(fixture / "objects" / stamps["ifis"], b"corruption")
        checks["corrupted_bytes_fail_closed"] = subprocess.run(
            [*amended, "--corrections", str(correction)], capture_output=True
        ).returncode != 0
    result = {"status": "pass" if all(checks.values()) else "fail", "checks": checks,
              "usage": payload["usage"]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("provider_context", nargs="*")
    args = parser.parse_args()
    checks = validate(json.loads(args.snapshot.read_bytes()))
    print(json.dumps(checks))
    sys.exit(0 if all(checks.values()) else 1)
