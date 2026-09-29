from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "canonical"
OUT = ROOT / "data" / "audit" / "canonical-semantic-diff.json"


def nonempty_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(nonempty_lines(path.read_text(encoding="utf-8")))


def semantic_sha256(text: str) -> str:
    """Hash JSONL records by parsed value, ignoring whitespace-only formatting changes."""
    records = []
    for line in nonempty_lines(text):
        value = json.loads(line)
        records.append(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    payload = "\n".join(records).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def baseline_text(rel: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def collect() -> dict:
    tables = {}
    changed = False
    for path in sorted(CANONICAL.glob("*.jsonl")):
        rel = path.relative_to(ROOT).as_posix()
        current_text = path.read_text(encoding="utf-8")
        current = line_count(path)
        baseline = baseline_text(rel)
        baseline_rows = None if baseline is None else len(nonempty_lines(baseline))
        delta = None if baseline_rows is None else current - baseline_rows
        current_hash = semantic_sha256(current_text)
        baseline_hash = None if baseline is None else semantic_sha256(baseline)
        table_changed = baseline_hash is None or current_hash != baseline_hash
        changed = changed or table_changed
        tables[path.stem] = {
            "baseline_rows": baseline_rows,
            "current_rows": current,
            "delta_rows": delta,
            "baseline_semantic_sha256": baseline_hash,
            "current_semantic_sha256": current_hash,
            "semantic_change": table_changed,
        }
    return {
        "schema_version": 2,
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
