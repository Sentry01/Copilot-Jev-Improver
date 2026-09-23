#!/usr/bin/env python3
"""response-quality gate — thin wrapper around shared runner."""
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
        "action": default.get("action", "send_response"),
        "proceed": bool(default.get("proceed", True)),
        "reason": f"fail-open for chat response: {message}",
        "fail_mode_applied": config.get("fail_mode", "open"),
        **signals,
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    # Keep this at 0.65 unless the response-quality trap suite is re-run; 0.7 false-held sourced answers.
    ready_min = float(thresholds.get("ready_to_send_min", 0.65))
    quality_min_label = thresholds.get("send_quality_min", "adequate")
    quality_min_idx = ((config.get("questions") or {}).get("send_quality") or {}).get("criteria", []).index(
        quality_min_label
    )

    ready = (answers.get("ready_to_send") or {}).get("noul")
    quality_idx, quality_label = _score_index(answers, config, "send_quality")
    defect = (answers.get("main_defect") or {}).get("choice")
    state = _state_from_client(client_result)
    evidence_sources = state.get("evidence_sources") or []
    evidence_count = len(evidence_sources) if isinstance(evidence_sources, list) else 0

    if ready is None or quality_idx is None:
        return _fail_decision(
            config,
            "missing ready_to_send or send_quality",
            ready_to_send=ready,
            send_quality=quality_label,
            main_defect=defect,
            evidence_source_count=evidence_count,
            thresholds={
                "ready_to_send_min": ready_min,
                "send_quality_min": quality_min_label,
            },
        )

    send = float(ready) >= ready_min and quality_idx >= quality_min_idx
    return {
        "action": "send_response" if send else "revise_response",
        "proceed": send,
        "reason": (
            f"send: ready_to_send={ready} >= {ready_min} and send_quality={quality_label} >= {quality_min_label}; "
            f"evidence_sources={evidence_count}"
            if send
            else f"revise: ready_to_send={ready} (min {ready_min}), "
            f"send_quality={quality_label} (min {quality_min_label}); defect={defect}; "
            f"evidence_sources={evidence_count}"
        ),
        "ready_to_send": ready,
        "send_quality": quality_label,
        "send_quality_index": quality_idx,
        "main_defect": defect,
        "evidence_source_count": evidence_count,
        "thresholds": {
            "ready_to_send_min": ready_min,
            "send_quality_min": quality_min_label,
            "send_quality_min_index": quality_min_idx,
        },
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
