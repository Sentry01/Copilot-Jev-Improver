#!/usr/bin/env python3
"""Score the decision log and emit publishable aggregates.

This is the half of the loop that can be shared. `decisions.jsonl` is local
and may quote real work; this script reads it and emits only counts and rates,
suppressing any gate with too few samples to say anything honest about.

Usage:
    python3 score_decisions.py                 # human-readable table
    python3 score_decisions.py --json          # machine-readable aggregate
    python3 score_decisions.py --min-sample 20
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

LOG = Path(__file__).resolve().parent / "logs" / "decisions.jsonl"

# Below this, a rate is noise. The telemetry baseline uses the same floor.
DEFAULT_MIN_SAMPLE = 10

GOOD = {"good_skip", "good_hold", "good_allow"}
BAD = {"bad_skip", "bad_hold", "bad_allow"}


def load(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a corrupt line must not take down the report
    return rows


def aggregate(rows: list[dict], min_sample: int) -> dict:
    by_gate: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "blocked": 0, "allowed": 0,
        "judged": 0, "good": 0, "bad": 0,
        "by_source": defaultdict(int),
    })

    for row in rows:
        gate = row.get("gate") or "unknown"
        bucket = by_gate[gate]
        bucket["total"] += 1
        bucket["by_source"][row.get("source", "unknown")] += 1
        if row.get("proceed"):
            bucket["allowed"] += 1
        else:
            bucket["blocked"] += 1
        outcome = row.get("outcome_later")
        if outcome in GOOD:
            bucket["judged"] += 1
            bucket["good"] += 1
        elif outcome in BAD:
            bucket["judged"] += 1
            bucket["bad"] += 1

    report = {}
    for gate, bucket in sorted(by_gate.items()):
        judged = bucket["judged"]
        entry = {
            "total": bucket["total"],
            "blocked": bucket["blocked"],
            "allowed": bucket["allowed"],
            "judged": judged,
            "by_source": dict(bucket["by_source"]),
            # A precision figure computed from 3 judgements is not a figure.
            "precision": round(bucket["good"] / judged, 3) if judged >= min_sample else None,
            "suppressed": judged < min_sample,
        }
        report[gate] = entry
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--min-sample", type=int, default=DEFAULT_MIN_SAMPLE)
    args = parser.parse_args()

    rows = load(LOG)
    report = aggregate(rows, args.min_sample)

    if args.json:
        print(json.dumps({
            "decisions": len(rows),
            "min_sample": args.min_sample,
            "gates": report,
        }, indent=2))
        return 0

    if not rows:
        print("No decisions logged yet.")
        print(f"Enable logging with COPILOT_JEV_LOG_DECISIONS=1, then run a gated session.")
        return 0

    print(f"{len(rows)} decisions logged; precision suppressed below {args.min_sample} judgements\n")
    header = f"{'gate':<26} {'total':>6} {'blocked':>8} {'allowed':>8} {'judged':>7} {'precision':>10}"
    print(header)
    print("-" * len(header))
    for gate, entry in report.items():
        precision = "insufficient" if entry["suppressed"] else f"{entry['precision']:.1%}"
        print(f"{gate:<26} {entry['total']:>6} {entry['blocked']:>8} "
              f"{entry['allowed']:>8} {entry['judged']:>7} {precision:>10}")

    live = sum(e["by_source"].get("live", 0) for e in report.values())
    if live == 0:
        print("\nNote: no live-sourced decisions. Every row is a replayed or policy decision, "
              "which proves plumbing but not live gate quality.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
