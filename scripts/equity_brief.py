"""Run a point-in-time equity research definition through the existing dbt project."""
import argparse
import fcntl
import hashlib
import io
import json
import math
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DBT = ROOT / "analytics/dbt"


def digest(content):
    return hashlib.sha256(content).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(data)
    try:
        temp.replace(path)
        if path.read_bytes() != data:
            raise ValueError(f"Read-back mismatch: {path.name}")
    finally:
        temp.unlink(missing_ok=True)


def cutoff(value, tz):
    if len(value) == 10:
        return datetime.combine(datetime.fromisoformat(value).date(), time.max, tz)
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Full timestamps need a timezone")
    return result


def active_documents(spec, as_of, corrections):
    docs = {key: {"url": url, "published_at": stamp, "tier": tier}
            for key, (url, stamp, tier) in spec["documents"].items()}
    history = [{"source": key, **doc} for key, doc in docs.items()] + corrections
    active = {}
    for entry in sorted(history, key=lambda row: cutoff(row["published_at"], as_of.tzinfo)):
        source = entry["source"]
        if source not in docs or entry["tier"] != docs[source]["tier"]:
            raise ValueError(f"Invalid source or tier: {source}")
        if cutoff(entry["published_at"], as_of.tzinfo) > as_of:
            continue
        if source in active and cutoff(entry["published_at"], as_of.tzinfo) == cutoff(
            active[source]["published_at"], as_of.tzinfo
        ):
            raise ValueError(f"Ambiguous revision: {source}")
        active[source] = {k: entry[k] for k in ("url", "published_at", "tier")}
    return active


def read_documents(active, state, replay, frozen):
    cache = state / "objects"
    if replay:
        if {key: {k: v for k, v in doc.items() if k != "sha256"}
            for key, doc in frozen.items()} != active:
            raise ValueError("Snapshot sources differ from the selected as-of revisions")
        contents = {}
        for key, doc in frozen.items():
            fingerprint = doc["sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise ValueError(f"Invalid hash: {key}")
            body = (cache / fingerprint).read_bytes()
            if digest(body) != fingerprint:
                raise ValueError(f"Hash mismatch: {key}")
            contents[key] = body
        return frozen, contents

    sources, contents = {}, {}
    for key, doc in active.items():
        if not doc["url"].startswith("https://"):
            raise ValueError(f"HTTPS source required: {key}")
        body = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--location", "--proto", "=https",
             "--retry", "2", "--retry-max-time", "25", "--max-time", "20", doc["url"]],
            capture_output=True, check=True,
        ).stdout
        fingerprint = digest(body)
        save(cache / fingerprint, body)
        sources[key] = {**doc, "sha256": fingerprint}
        contents[key] = body
    return sources, contents


def extract_facts(spec, sources, contents):
    readers, pages, facts, evidence = {}, {}, [], {}
    for field in spec["facts"]:
        key, source, page = field["id"], field["source"], field["page"]
        kind, period, unit = field["kind"], field["period"], field["unit"]
        pattern, scale = field["pattern"], field["scale"]
        if source not in contents:
            raise ValueError(f"Evidence missing as of cutoff: {source} ({key})")
        location = (source, page)
        if location not in pages:
            if page is None:
                pages[location] = contents[source].decode()
            else:
                if source not in readers:
                    readers[source] = PdfReader(io.BytesIO(contents[source]))
                pages[location] = unicodedata.normalize(
                    "NFKC", readers[source].pages[page - 1].extract_text()
                )
        matches = list(re.finditer(pattern, pages[location]))
        if len(matches) != 1:
            raise ValueError(f"Expected one source match for {key}, found {len(matches)}")
        found = matches[0]
        token = found.group(1).replace(",", "")
        leading, separator, trailing = token.partition("兆")
        number = (Decimal(leading) * 10_000 + Decimal(trailing) if separator
                  else Decimal(token)) * scale
        doc = sources[source]
        provenance = {**doc, "page": page, "anchor": found.group(1), "field": key}
        evidence_id = digest(encoded(provenance))[:24]
        evidence[evidence_id] = provenance
        facts.append({
            "id": key, "value": str(number), "kind": kind, "period": period,
            "unit": unit, "evidence_id": evidence_id,
        })
    return facts, evidence


def build_model(spec, facts, tmp):
    scenario = spec["scenario"]
    model = spec["model"]
    if not re.fullmatch(r"gold_[a-z0-9_]+", model):
        raise ValueError("Invalid dbt model name")
    durations = scenario["boom_quarters"]
    numbers = [x for key, x in scenario.items()
               if key != "boom_quarters" and x is not None]
    if (any(type(x) not in (float, int) or not math.isfinite(x) for x in numbers)
        or scenario["discount_rate"] <= max(scenario["terminal_growth"], 0)
        or scenario["claimed_pe"] <= 0
        or not durations or any(type(q) is not int or not 0 <= q <= 120 for q in durations)):
        raise ValueError("Invalid scenario assumptions")
    fact_path = tmp / "facts.json"
    save(fact_path, encoded(facts))
    variables = {"equity_brief_facts": str(fact_path)}
    variables.update({f"equity_brief_{key}": value for key, value in scenario.items()})
    profiles = tmp / "profiles.yml"
    path = tmp / "analysis.duckdb"
    save(profiles, encoded({"semiconductor_medallion": {"target": "local", "outputs": {
        "local": {"type": "duckdb", "path": str(path), "threads": 1},
    }}}))
    result = subprocess.run(
        [sys.executable, "-m", "dbt.cli.main", "build", "--quiet", "--project-dir", str(DBT),
         "--profiles-dir", str(tmp), "--target-path", str(tmp / "target"),
         "--log-path", str(tmp / "logs"), "--vars", json.dumps(variables),
         "--select", f"+{model}"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        raise ValueError(f"dbt build failed: {result.stdout[-2400:]} {result.stderr[-1200:]}")
    with duckdb.connect(str(path), read_only=True) as db:
        output = db.execute(f"select * from main.{model} order by boom_quarters")
        names = [column[0] for column in output.description]
        rows = [dict(zip(names, row, strict=True)) for row in output.fetchall()]
    return json.loads(json.dumps(rows, default=str))


def render(payload):
    row = payload["valuation"][0]
    t = lambda item: f'{float(row[item])/1e12:.2f}兆円'
    consensus_pe = row["consensus_pe"]
    consensus_label = "赤字等で算出対象外" if consensus_pe is None else f"{consensus_pe:.2f}倍"
    lines = [
        f'{payload["ticker"]} ｜ {payload["as_of"]}',
        f'株式価値 {t("equity_value")}（10月末までの公表株数から概算）。今期市場予想でPER {consensus_label}。',
        f'投稿の倍率に必要な今期純利益は{t("implied_fy_profit")}。1〜3月期だけで{t("implied_q4_profit")}。',
        f'半期の設備投資控除後営業CF {t("half_cash_after_capex")}。期末未払法人税 {t("tax_payable")}。',
        f'還元方針は中長期の余剰資金の{float(row["excess_return_percent"]):g}%。初配は分割後{row["dividend"]:.0f}円。',
        f'Cayman 1Aの6月11日分は分割後{row["june11_price"]:,.0f}円。6月4日分は{row["june4_price"]:,.0f}円。',
        '好況残存四半期 → 現在株価を説明する平常時の年間株主向けCF（試算）',
    ]
    lines.extend(f'{v["boom_quarters"]}四半期 → {v["normal_annual_fcfe_required"]/1e12:.2f}兆円'
                 for v in payload["valuation"])
    return "\n".join(lines) + "\n"


def run(args):
    spec = json.loads(args.spec.read_text())
    if args.ticker != spec["ticker"]:
        raise ValueError("Ticker does not match the selected definition")
    local_tz = datetime.fromisoformat(f"2000-01-01T00:00:00{spec['timezone']}").tzinfo
    as_of = cutoff(args.as_of, local_tz)
    corrections = json.loads(args.corrections.read_text()) if args.corrections else []
    active = active_documents(spec, as_of.astimezone(local_tz), corrections)
    state = args.state.resolve()
    revision = digest(encoded(active))
    ledger = state / "snapshots" / f"{revision}.json"
    use_snapshot = args.mode == "replay" or ledger.exists()
    snapshot = json.loads(ledger.read_bytes()) if use_snapshot else {}
    sources, contents = read_documents(active, state, use_snapshot, snapshot)
    facts, evidence = extract_facts(spec, sources, contents)
    with tempfile.TemporaryDirectory() as tmp:
        valuation = build_model(spec, facts, Path(tmp))
    if not valuation:
        raise ValueError("Empty valuation result")
    payload = {
        "ticker": args.ticker, "as_of": args.as_of, "definition_sha256": digest(encoded(spec)),
        "evidence": evidence, "facts": facts, "valuation": valuation, "scenario": spec["scenario"],
        "coverage": "configured_evidence_only",
        "mission": spec["mission"],
        "usage": {"model_calls": 0, "input_tokens": 0, "output_tokens": 0},
    }
    payload["unknowns"] = spec["unknowns"]
    payload["report"] = render(payload)
    report = payload["report"]
    output = encoded(payload)
    changed = []
    evidence_changed = False
    if args.mode == "run":
        with (state / ".publish.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous_file = state / "latest.json"
            previous = json.loads(previous_file.read_bytes()) if previous_file.exists() else {}
            evidence_changed = previous.get("evidence") != evidence
            before = {row["boom_quarters"]: row for row in previous.get("valuation", [])}
            changed = sorted({key for row in valuation for key, value in row.items()
                              if value != before.get(row["boom_quarters"], {}).get(key)})
            if set(before) - {row["boom_quarters"] for row in valuation}:
                changed = sorted({*changed, "boom_quarters"})
            if ledger.exists() and ledger.read_bytes() != encoded(sources):
                raise ValueError("Existing source revision changed bytes; register a separately dated correction")
            save(ledger, encoded(sources))
            save(state / "history" / f"{digest(output)}.json", output)
            previous_as_of = previous.get("as_of")
            if not previous_as_of or cutoff(previous_as_of, local_tz) <= as_of:
                save(previous_file, output)
    if args.json:
        print(output.decode(), end="")
    else:
        print(json.dumps({"status": ("replayed" if args.mode == "replay" else ("changed" if changed or evidence_changed else "unchanged")),
                          "changed_metrics": changed, "evidence_changed": evidence_changed,
                          "usage": payload["usage"], "evidence_ids": sorted(evidence), "report": report}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["run", "replay", "eval"])
    parser.add_argument("--ticker", default="285A")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=ROOT / "config/equity_brief/nand.json")
    parser.add_argument("--corrections", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "eval":
            from equity_brief_eval import evaluate
            if args.ticker != "285A" or args.as_of != "2026-11-15":
                raise ValueError("The benchmark uses ticker 285A at 2026-11-15")
            return evaluate([sys.executable, str(Path(__file__)), "replay",
                             "--ticker", args.ticker, "--as-of", args.as_of,
                             "--state", str(args.state), "--spec", str(args.spec), "--json"], args.state)
        run(args)
    except (ValueError, OSError, subprocess.SubprocessError, IndexError) as error:
        print(json.dumps({"status": "incomplete", "reason": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
