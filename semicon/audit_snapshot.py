from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCH = [
    "data/raw/google_sheets_import",
    "data/raw/company_ir",
    "data/canonical",
    "data/derived",
    "data/conflicts",
]
OUT = ROOT / "data" / "audit" / "canonical-ledger-status.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect() -> dict:
    files = []
    for rel in WATCH:
        base = ROOT / rel
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            stat = path.stat()
            files.append({
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256(path),
                "bytes": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
    digest = hashlib.sha256(
        "\n".join(f"{f['path']}\t{f['sha256']}" for f in files).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tree_sha256": digest,
        "file_count": len(files),
        "files": files,
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(collect(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
