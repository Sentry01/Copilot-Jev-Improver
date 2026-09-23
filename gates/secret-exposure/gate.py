#!/usr/bin/env python3
"""secret-exposure gate — thin wrapper around shared runner."""
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
    default = config.get("default_on_error") or {"action": "block_emit", "proceed": False}
    return {
        "action": default.get("action", "block_emit"),
        "proceed": bool(default.get("proceed", False)),
        "reason": reason,
        "fail_mode_applied": "closed",
        **signals,
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    safe_min = float(thresholds.get("safe_to_emit_min", 0.85))
    allowed_kind = thresholds.get("allowed_exposure_kind", "none")
    safe = _noul(answers, "safe_to_emit")
    exposure_kind = _choice(answers, "exposure_kind")
    severity_idx, severity = _score_index(answers, config, "severity")
    base = {
        "safe_to_emit": safe,
        "exposure_kind": exposure_kind,
        "severity": severity,
        "severity_index": severity_idx,
        "thresholds": {"safe_to_emit_min": safe_min, "allowed_exposure_kind": allowed_kind},
    }

    if safe is None or exposure_kind is None:
        return _closed(config, "missing safe_to_emit or exposure_kind; fail-closed", **base)

    emit = safe >= safe_min and exposure_kind == allowed_kind
    return {
        "action": "emit" if emit else "block_emit",
        "proceed": emit,
        "reason": (
            f"safe_to_emit={safe} >= {safe_min} and exposure_kind={exposure_kind}"
            if emit
            else f"blocked: safe_to_emit={safe} (min {safe_min}) exposure_kind={exposure_kind} (required {allowed_kind}) severity={severity}"
        ),
        **base,
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
