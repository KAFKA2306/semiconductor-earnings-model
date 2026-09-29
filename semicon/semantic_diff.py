from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "canonical"
OUT = ROOT / "data" / "audit" / "canonical-semantic-diff.json"


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def baseline_count(rel: str) -> int | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def collect() -> dict:
    tables = {}
    changed = False
    for path in sorted(CANONICAL.glob("*.jsonl")):
        rel = path.relative_to(ROOT).as_posix()
        current = line_count(path)
        baseline = baseline_count(rel)
        delta = None if baseline is None else current - baseline
        if delta not in (None, 0):
            changed = True
        tables[path.stem] = {
            "baseline_rows": baseline,
            "current_rows": current,
            "delta_rows": delta,
        }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantic_change": changed,
        "tables": tables,
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(collect(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
