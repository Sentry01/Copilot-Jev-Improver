#!/usr/bin/env python3
"""verification-sufficient gate — thin wrapper around shared runner."""
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


def _fail_decision(config: dict[str, Any], message: str, **signals: Any) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    return {
        "action": default.get("action", "block_completion_claim"),
        "proceed": bool(default.get("proceed", False)),
        "reason": f"fail-closed: {message}",
        "fail_mode_applied": config.get("fail_mode", "closed"),
        **signals,
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    verified_min = float(thresholds.get("outcome_verified_min", 0.7))
    confidence_min_label = thresholds.get("confidence_in_claim_min", "demonstrated")
    confidence_min_idx = ((config.get("questions") or {}).get("confidence_in_claim") or {}).get("criteria", []).index(
        confidence_min_label
    )

    outcome_verified = (answers.get("outcome_verified") or {}).get("noul")
    gap = (answers.get("verification_gap") or {}).get("choice")
    confidence_idx, confidence_label = _score_index(answers, config, "confidence_in_claim")

    if outcome_verified is None or confidence_idx is None:
        return _fail_decision(
            config,
            "missing outcome_verified or confidence_in_claim; do not emit a confident completion claim",
            outcome_verified=outcome_verified,
            verification_gap=gap,
            confidence_in_claim=confidence_label,
            thresholds={
                "outcome_verified_min": verified_min,
                "confidence_in_claim_min": confidence_min_label,
            },
        )

    allow = float(outcome_verified) >= verified_min and confidence_idx >= confidence_min_idx
    return {
        "action": "allow_completion_claim" if allow else "keep_working_or_state_unverified",
        "proceed": allow,
        "reason": (
            f"allow: outcome_verified={outcome_verified} >= {verified_min} and "
            f"confidence_in_claim={confidence_label} >= {confidence_min_label}"
            if allow
            else f"block: outcome_verified={outcome_verified} (min {verified_min}), "
            f"confidence_in_claim={confidence_label} (min {confidence_min_label}); gap={gap}"
        ),
        "outcome_verified": outcome_verified,
        "verification_gap": gap,
        "confidence_in_claim": confidence_label,
        "confidence_in_claim_index": confidence_idx,
        "thresholds": {
            "outcome_verified_min": verified_min,
            "confidence_in_claim_min": confidence_min_label,
            "confidence_in_claim_min_index": confidence_min_idx,
        },
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
