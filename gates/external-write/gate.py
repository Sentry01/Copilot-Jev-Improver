#!/usr/bin/env python3
"""external-write gate — read-only channel hard rule plus shared runner."""
from __future__ import annotations

import sys
from pathlib import Path

GATE_DIR = Path(__file__).resolve().parent
ROOT = GATE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.runner import decide as _decide  # noqa: E402
from common.runner import run_cli  # noqa: E402


def _noul(answers: dict, key: str) -> float | None:
    value = (answers.get(key) or {}).get("noul")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _choice(answers: dict, key: str) -> str | None:
    value = (answers.get(key) or {}).get("choice")
    return value if isinstance(value, str) else None


def _score_index(answers: dict, config: dict, key: str) -> tuple[int | None, str | None]:
    criteria = (((config.get("questions") or {}).get(key) or {}).get("criteria") or [])
    answer = answers.get(key) or {}
    legend = answer.get("legend")
    score = answer.get("score")
    if isinstance(legend, str) and legend in criteria:
        return criteria.index(legend), legend
    if isinstance(score, str) and score in criteria:
        return criteria.index(score), score
    if isinstance(score, (int, float)):
        idx = int(round(float(score)))
        if 0 <= idx < len(criteria):
            return idx, criteria[idx]
    probabilities = answer.get("probabilities") or {}
    if isinstance(probabilities, dict):
        labels = [(label, probabilities.get(label)) for label in criteria]
        labels = [(label, prob) for label, prob in labels if isinstance(prob, (int, float))]
        if labels:
            label = max(labels, key=lambda item: item[1])[0]
            return criteria.index(label), label
    return None, None


def _state(client_result: dict) -> dict:
    request = client_result.get("request_sans_auth") or {}
    state = request.get("state") or {}
    return state if isinstance(state, dict) else {}


def _closed(config: dict, reason: str, **signals: object) -> dict:
    default = config.get("default_on_error") or {"action": "block_external_write", "proceed": False}
    return {
        "action": default.get("action", "block_external_write"),
        "proceed": bool(default.get("proceed", False)),
        "reason": reason,
        "fail_mode_applied": "closed",
        **signals,
    }


def _read_only_decision(config: dict, state: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    return {
        "action": "block_external_write",
        "proceed": False,
        "reason": "channel_policy=read_only; hard policy block before Jev",
        "safe_to_send": None,
        "authorisation_basis": None,
        "audience_risk": None,
        "audience_risk_index": None,
        "channel_policy": state.get("channel_policy"),
        "thresholds": {
            "safe_to_send_min": thresholds.get("safe_to_send_min", 0.75),
            "allowed_authorisation_basis": thresholds.get("allowed_authorisation_basis", ["explicit_request", "standing_policy"]),
        },
        "hard_rule_applied": "read_only_channel_policy",
    }


def hard_rule(state: dict, config: dict) -> dict | None:
    if isinstance(state, dict) and state.get("channel_policy") == "read_only":
        return _read_only_decision(config, state)
    return None


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    state = _state(client_result)
    policy_decision = hard_rule(state, config)
    if policy_decision is not None:
        return policy_decision

    thresholds = config.get("thresholds") or {}
    safe_min = float(thresholds.get("safe_to_send_min", 0.75))
    allowed = set(thresholds.get("allowed_authorisation_basis", ["explicit_request", "standing_policy"]))
    safe = _noul(answers, "safe_to_send")
    basis = _choice(answers, "authorisation_basis")
    risk_idx, risk = _score_index(answers, config, "audience_risk")
    base = {
        "safe_to_send": safe,
        "authorisation_basis": basis,
        "audience_risk": risk,
        "audience_risk_index": risk_idx,
        "channel_policy": state.get("channel_policy"),
        "thresholds": {"safe_to_send_min": safe_min, "allowed_authorisation_basis": sorted(allowed)},
    }

    if safe is None or basis is None:
        return _closed(config, "missing safe_to_send or authorisation_basis; fail-closed", **base)

    send = safe >= safe_min and basis in allowed
    return {
        "action": "send" if send else "block_external_write",
        "proceed": send,
        "reason": (
            f"safe_to_send={safe} >= {safe_min} and authorisation_basis={basis}"
            if send
            else f"blocked: safe_to_send={safe} (min {safe_min}) authorisation_basis={basis} (allowed {sorted(allowed)}) audience_risk={risk}"
        ),
        **base,
    }


def decide(state: dict, *, write_dry: bool = False) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=write_dry, hard_rule=hard_rule)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate, hard_rule=hard_rule))
