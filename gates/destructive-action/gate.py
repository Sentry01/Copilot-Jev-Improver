#!/usr/bin/env python3
"""destructive-action gate — thin wrapper around shared runner."""
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


def _closed(config: dict, reason: str, **signals: object) -> dict:
    default = config.get("default_on_error") or {"action": "ask_user", "proceed": False}
    return {
        "action": default.get("action", "ask_user"),
        "proceed": bool(default.get("proceed", False)),
        "reason": reason,
        "fail_mode_applied": "closed",
        **signals,
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    safe_min = float(thresholds.get("safe_to_execute_min", 0.8))
    blast_max_label = thresholds.get("blast_radius_max", "recoverable")
    criteria = (((config.get("questions") or {}).get("blast_radius") or {}).get("criteria") or [])
    blast_max_idx = criteria.index(blast_max_label) if blast_max_label in criteria else None

    safe = _noul(answers, "safe_to_execute")
    blast_idx, blast_label = _score_index(answers, config, "blast_radius")
    alternative = _choice(answers, "safer_alternative")
    base = {
        "safe_to_execute": safe,
        "blast_radius": blast_label,
        "blast_radius_index": blast_idx,
        "safer_alternative": alternative,
        "thresholds": {"safe_to_execute_min": safe_min, "blast_radius_max": blast_max_label, "blast_radius_max_index": blast_max_idx},
    }

    if safe is None or blast_idx is None or blast_max_idx is None:
        return _closed(config, "missing safe_to_execute or blast_radius; fail-closed", **base)

    execute = safe >= safe_min and blast_idx <= blast_max_idx
    if execute:
        return {
            "action": "execute",
            "proceed": True,
            "reason": f"safe_to_execute={safe} >= {safe_min} and blast_radius={blast_label} <= {blast_max_label}",
            **base,
        }

    action = alternative if alternative and alternative != "none_needed" else "ask_user"
    return {
        "action": action,
        "proceed": False,
        "reason": f"blocked: safe_to_execute={safe} (min {safe_min}) and blast_radius={blast_label} (max {blast_max_label}); safer_alternative={action}",
        **base,
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
