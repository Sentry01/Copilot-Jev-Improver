#!/usr/bin/env python3
"""Append one gate decision to the local decision log.

Usage:
    python3 log_decision.py '<json object>'
    echo '<json object>' | python3 log_decision.py

The log is **local-only and gitignored**. It records what the gates actually
did on real sessions, which is the input to scoring them. Because a state
summary can quote real work, nothing here is publishable as-is -- only the
aggregates produced by `score_decisions.py` are.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent / "logs" / "decisions.jsonl"

# A state summary is free text lifted from a real session. Cap it so the log
# cannot silently accumulate whole files, prompts or command output.
MAX_SUMMARY_CHARS = 300

ALLOWED_OUTCOMES = {
    "good_skip", "bad_skip",      # gate blocked: correctly / incorrectly
    "good_hold", "bad_hold",      # gate asked: correctly / incorrectly
    "good_allow", "bad_allow",    # gate allowed: correctly / incorrectly
}


def _truncate(value: object) -> object:
    if isinstance(value, str) and len(value) > MAX_SUMMARY_CHARS:
        return value[:MAX_SUMMARY_CHARS] + "…[truncated]"
    return value


def normalise(obj: dict) -> dict:
    obj.setdefault("ts", datetime.now(timezone.utc).astimezone().isoformat())
    obj.setdefault("agent", "Copilot CLI")
    for key in ("state_summary", "counterfactual", "reason"):
        if key in obj:
            obj[key] = _truncate(obj[key])

    outcome = obj.get("outcome_later")
    if outcome is not None and outcome not in ALLOWED_OUTCOMES:
        raise ValueError(f"outcome_later must be one of {sorted(ALLOWED_OUTCOMES)} or null")

    # `source` is not optional here. A fixture-backed decision is a replayed
    # answer, and scoring it as if it were live evidence would corrupt the
    # whole loop.
    obj.setdefault("source", "unknown")
    return obj


def append(obj: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False) + "\n")


def main() -> int:
    if os.environ.get("COPILOT_JEV_LOG_DECISIONS", "").strip().lower() in {"0", "off", "false"}:
        return 0
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        obj = normalise(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"log_decision: refusing malformed entry: {exc}", file=sys.stderr)
        return 1
    append(obj)
    print(f"logged {obj.get('gate')} {obj.get('action')} source={obj.get('source')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
