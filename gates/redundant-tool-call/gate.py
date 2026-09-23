#!/usr/bin/env python3
"""redundant-tool-call gate — thin wrapper around shared runner."""
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


def _state(client_result: dict[str, Any]) -> dict[str, Any]:
    request = client_result.get("request_sans_auth") or {}
    state = request.get("state") or {}
    return state if isinstance(state, dict) else {}


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


def _mutation_hint(state: dict[str, Any]) -> bool:
    text = " ".join(str(state.get(k, "")) for k in ("prior_calls", "elapsed_since_prior"))
    lowered = text.lower()
    return any(token in lowered for token in ("mutation", "mutated", "after edit", "edited", "changed", "modified", "wrote", "write completed"))


def _default_decision(config: dict[str, Any], reason: str, *, signals: dict[str, Any]) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    fail_mode = (config.get("fail_mode") or "open").lower()
    return {
        "action": default.get("action", "call_tool"),
        "proceed": bool(default.get("proceed", True)),
        "reason": f"fail-{fail_mode} on missing/invalid Jev answer: {reason}",
        "fail_mode_applied": fail_mode,
        "signals": signals,
        "thresholds": config.get("thresholds") or {},
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    redundant_min = float(thresholds.get("is_redundant_min", 0.65))
    state = _state(client_result)
    volatility = state.get("volatility")
    mutation_between_calls = _mutation_hint(state)
    redundant = _noul(answers, "is_redundant")
    strategy = _choice(answers, "reuse_strategy")
    signals = {
        "is_redundant": redundant,
        "reuse_strategy": strategy,
        "volatility": volatility,
        "mutation_between_calls": mutation_between_calls,
    }
    if redundant is None or not strategy:
        return _default_decision(config, "required redundancy signal was absent", signals=signals)

    volatile_or_mutated = volatility == "volatile" or mutation_between_calls
    if redundant >= redundant_min and volatile_or_mutated:
        action = "call_tool"
        proceed = True
        reason = (
            f"is_redundant={redundant:.2f} >= {redundant_min:.2f}, but volatility={volatility} "
            "or an intervening mutation makes the repeat legitimate"
        )
    elif redundant >= redundant_min:
        if strategy == "narrow_scope":
            action = "narrow_scope"
            proceed = True
        else:
            action = "reuse_cache"
            proceed = False
        reason = f"is_redundant={redundant:.2f} >= {redundant_min:.2f}; reuse_strategy={strategy}"
    else:
        if strategy == "narrow_scope":
            action = "narrow_scope"
            proceed = True
            reason = f"is_redundant={redundant:.2f} < {redundant_min:.2f}; run a narrower call"
        else:
            action = "call_tool"
            proceed = True
            reason = f"is_redundant={redundant:.2f} < {redundant_min:.2f}; call is not redundant enough to skip"

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
