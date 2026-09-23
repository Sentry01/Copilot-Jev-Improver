#!/usr/bin/env python3
"""parallel-fanout gate — thin wrapper around shared runner."""
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


def _score_index(answers: dict[str, Any], config: dict[str, Any], key: str) -> tuple[int | None, str | None]:
    answer = answers.get(key) or {}
    label = answer.get("score")
    criteria = ((config.get("questions") or {}).get(key) or {}).get("criteria") or []
    if label in criteria:
        return criteria.index(label), label
    return None, label


def _state_from_client(client_result: dict[str, Any]) -> dict[str, Any]:
    request = client_result.get("request_sans_auth") or {}
    state = request.get("state") or {}
    return state if isinstance(state, dict) else {}


def _fail_decision(config: dict[str, Any], message: str, **signals: Any) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    return {
        "action": default.get("action", "sequential"),
        "proceed": bool(default.get("proceed", False)),
        "reason": f"fail-open: {message}",
        "fail_mode_applied": config.get("fail_mode", "open"),
        **signals,
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    independent_min = float(thresholds.get("independent_min", 0.6))
    required_ordering_risk = thresholds.get("required_ordering_risk", "none")

    independent = (answers.get("independent") or {}).get("noul")
    max_parallel_idx, max_parallel_label = _score_index(answers, config, "max_parallel")
    ordering_risk = (answers.get("ordering_risk") or {}).get("choice")
    state = _state_from_client(client_result)
    proposed_calls = state.get("proposed_calls") or []
    proposed_count = len(proposed_calls) if isinstance(proposed_calls, list) else 0

    if independent is None or max_parallel_idx is None or ordering_risk is None:
        return _fail_decision(
            config,
            "missing independent, max_parallel, or ordering_risk",
            independent=independent,
            max_parallel=max_parallel_label,
            ordering_risk=ordering_risk,
            proposed_call_count=proposed_count,
            thresholds={
                "independent_min": independent_min,
                "required_ordering_risk": required_ordering_risk,
            },
        )

    cap = int(max_parallel_label)
    if ordering_risk == "write_conflict":
        parallel = False
        reason = f"sequential: ordering_risk=write_conflict forces sequential regardless of independent={independent}"
    else:
        parallel = float(independent) >= independent_min and ordering_risk == required_ordering_risk
        reason = (
            f"parallelise: independent={independent} >= {independent_min}, ordering_risk={ordering_risk}, "
            f"cap={min(cap, proposed_count) if proposed_count else cap}"
            if parallel
            else f"sequential: independent={independent} (min {independent_min}), "
            f"ordering_risk={ordering_risk} (required {required_ordering_risk})"
        )

    return {
        "action": "parallelise" if parallel else "sequential",
        "proceed": parallel,
        "reason": reason,
        "independent": independent,
        "max_parallel": max_parallel_label,
        "max_parallel_index": max_parallel_idx,
        "parallel_cap": min(cap, proposed_count) if proposed_count else cap,
        "ordering_risk": ordering_risk,
        "proposed_call_count": proposed_count,
        "thresholds": {
            "independent_min": independent_min,
            "required_ordering_risk": required_ordering_risk,
        },
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
