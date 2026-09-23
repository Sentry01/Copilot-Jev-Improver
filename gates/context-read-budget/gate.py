#!/usr/bin/env python3
"""context-read-budget gate — thin wrapper around shared runner."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

GATE_DIR = Path(__file__).resolve().parent
ROOT = GATE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.runner import decide as _decide  # noqa: E402
from common.runner import run_cli  # noqa: E402


def _noul(answers: dict[str, Any], key: str) -> float | None:
    answer = answers.get(key) or {}
    if not isinstance(answer, dict):
        return None
    value = answer.get("noul")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _choice(answers: dict[str, Any], key: str) -> str | None:
    answer = answers.get(key) or {}
    return answer.get("choice") if isinstance(answer, dict) else None


def _score(answers: dict[str, Any], key: str) -> str | None:
    answer = answers.get(key) or {}
    value = answer.get("score") if isinstance(answer, dict) else None
    return str(value) if value is not None else None


def _score_index(config: dict[str, Any], key: str, value: str | None) -> int | None:
    criteria = (((config.get("questions") or {}).get(key) or {}).get("criteria") or [])
    if value is None or not isinstance(criteria, list):
        return None
    try:
        return criteria.index(value)
    except ValueError:
        return None


def _default_decision(config: dict[str, Any], reason: str, *, signals: dict[str, Any]) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    fail_mode = (config.get("fail_mode") or "open").lower()
    return {
        "action": default.get("action", "use_proposed_read"),
        "proceed": bool(default.get("proceed", True)),
        "reason": f"fail-{fail_mode} on missing/invalid Jev answer: {reason}",
        "fail_mode_applied": fail_mode,
        "signals": signals,
        "thresholds": config.get("thresholds") or {},
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    full_min = float(thresholds.get("full_read_justified_min", 0.7))
    full = _noul(answers, "full_read_justified")
    strategy = _choice(answers, "read_strategy")
    relevance = _score(answers, "expected_relevance")
    relevance_idx = _score_index(config, "expected_relevance", relevance)
    signals = {
        "full_read_justified": full,
        "read_strategy": strategy,
        "expected_relevance": relevance,
        "expected_relevance_index": relevance_idx,
    }
    if full is None or not strategy or relevance_idx is None:
        return _default_decision(config, "required context-read signal was absent", signals=signals)

    if strategy == "already_have_it":
        action = "skip_read"
        proceed = False
        reason = f"read_strategy=already_have_it; skip entirely (full_read_justified={full:.2f})"
    elif full >= full_min:
        action = "full_read"
        proceed = True
        reason = f"full_read_justified={full:.2f} >= {full_min:.2f}; full read allowed"
    elif strategy in {"targeted_search", "ranged_read"}:
        action = strategy
        proceed = True
        reason = f"full_read_justified={full:.2f} < {full_min:.2f}; follow read_strategy={strategy}"
    else:
        action = "ranged_read"
        proceed = True
        reason = (
            f"full_read_justified={full:.2f} < {full_min:.2f}; "
            "read_strategy=full_read conflicts with threshold, so choose a bounded ranged_read"
        )

    return {
        "action": action,
        "proceed": proceed,
        "reason": reason,
        "signals": signals,
        "thresholds": thresholds,
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
