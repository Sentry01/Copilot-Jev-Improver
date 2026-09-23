#!/usr/bin/env python3
"""Run Copilot × Jev traps through the real gate implementations.

This runner is read-only: it prints results and never writes outside this file's
existing trap tree. Use `python3 -B` to avoid `__pycache__` writes during proof
runs.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

TRAPS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TRAPS_DIR.parents[1]
GATES_DIR = REPO_ROOT / "gates"

if str(GATES_DIR) not in sys.path:
    sys.path.insert(0, str(GATES_DIR))

from common import jev_client  # noqa: E402
from common.runner import decide as runner_decide  # noqa: E402

_JEV_CALLS = 0
_ORIGINAL_CALL_JEV = jev_client.call_jev


def _counting_call_jev(*args: Any, **kwargs: Any) -> dict[str, Any]:
    global _JEV_CALLS
    _JEV_CALLS += 1
    return _ORIGINAL_CALL_JEV(*args, **kwargs)


jev_client.call_jev = _counting_call_jev


def load_gate(slug: str):
    gate_py = GATES_DIR / slug / "gate.py"
    if not gate_py.exists():
        raise FileNotFoundError(f"gate not found: {gate_py}")
    module_name = f"trap_gate_{slug.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, gate_py)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {gate_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_traps() -> list[tuple[Path, dict[str, Any]]]:
    traps: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(TRAPS_DIR.glob("*/trap.json")):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        traps.append((path, data))
    return traps


def run_trap(path: Path, trap: dict[str, Any]) -> dict[str, Any]:
    slug = trap["slug"]
    gate_slug = trap["gate"]
    module = load_gate(gate_slug)
    before_calls = _JEV_CALLS

    if trap.get("requires_policy_short_circuit"):
        outcome = module.decide(trap["state"])
    else:
        outcome = runner_decide(module.GATE_DIR, trap["state"], module.evaluate, fixture=path)

    after_calls = _JEV_CALLS
    decision = outcome.get("decision") or {}
    actual_action = decision.get("action")
    actual_proceed = bool(decision.get("proceed"))
    expected_action = trap["expected_action"]
    expected_proceed = bool(trap["expected_proceed"])
    expected_source = trap.get("expected_source")
    source = outcome.get("source")

    ok = actual_action == expected_action and actual_proceed == expected_proceed
    source_ok = expected_source is None or source == expected_source
    policy_calls_ok = True
    policy_note = ""
    if slug == "slack-send-under-read-only":
        policy_calls_ok = source == "policy" and after_calls == before_calls
        policy_note = f"; policy_jev_calls={after_calls - before_calls}"

    return {
        "slug": slug,
        "gate": gate_slug,
        "source": source,
        "jev_calls": after_calls - before_calls,
        "actual_action": actual_action,
        "actual_proceed": actual_proceed,
        "expected_action": expected_action,
        "expected_proceed": expected_proceed,
        "expected_source": expected_source,
        "result": "PASS" if ok and source_ok and policy_calls_ok else "FAIL",
        "reason": decision.get("reason", ""),
        "policy_note": policy_note,
        "falsifier": trap.get("falsifier", ""),
    }


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = ["trap", "gate", "source", "jev", "action", "proceed", "expected", "result"]
    table = []
    for r in rows:
        table.append([
            r["slug"],
            r["gate"],
            str(r["source"]),
            str(r["jev_calls"]),
            str(r["actual_action"]),
            str(r["actual_proceed"]),
            f"{r['expected_action']}/{r['expected_proceed']}",
            r["result"],
        ])
    widths = [len(h) for h in headers]
    for row in table:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = " | ".join("{:<" + str(w) + "}" for w in widths)
    sep = "-+-".join("-" * w for w in widths)
    print(fmt.format(*headers))
    print(sep)
    for row in table:
        print(fmt.format(*row))


def main() -> int:
    traps = load_traps()
    if not traps:
        print("No traps found", file=sys.stderr)
        return 2

    rows = []
    for path, trap in traps:
        rows.append(run_trap(path, trap))

    print(f"JEV_MODE={os.environ.get('JEV_MODE') or '(auto)'} TYPESAFE_API_KEY={'set' if os.environ.get('TYPESAFE_API_KEY') else 'unset'}")
    print_table(rows)

    failures = [r for r in rows if r["result"] != "PASS"]
    if failures:
        print("\nFailures:")
        for r in failures:
            print(f"- {r['slug']}: got {r['actual_action']}/{r['actual_proceed']} from {r['source']}; expected {r['expected_action']}/{r['expected_proceed']} from {r['expected_source']}")
            print(f"  reason: {r['reason']}{r['policy_note']}")
        return 1

    print("\nAll traps matched expected offline outcomes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
