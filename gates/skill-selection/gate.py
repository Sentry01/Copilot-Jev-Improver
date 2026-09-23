#!/usr/bin/env python3
"""skill-selection gate — dynamic choice wrapper around shared runner."""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Callable

GATE_DIR = Path(__file__).resolve().parent
ROOT = GATE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common import runner as _runner  # noqa: E402


def _score_index(answers: dict[str, Any], config: dict[str, Any], key: str) -> tuple[int | None, str | None]:
    answer = answers.get(key) or {}
    label = answer.get("score")
    criteria = ((config.get("questions") or {}).get(key) or {}).get("criteria") or []
    if label in criteria:
        return criteria.index(label), label
    return None, label


def _threshold_index(config: dict[str, Any], key: str, label: str) -> int:
    criteria = ((config.get("questions") or {}).get(key) or {}).get("criteria") or []
    return criteria.index(label)


def _fail_decision(config: dict[str, Any], message: str, **signals: Any) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    return {
        "action": default.get("action", "skip_skill"),
        "proceed": bool(default.get("proceed", False)),
        "reason": f"fail-open: {message}",
        "fail_mode_applied": config.get("fail_mode", "open"),
        **signals,
    }


def _candidate_criteria(state: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    max_candidates = int((config.get("thresholds") or {}).get("max_candidates", 8))
    criteria: dict[str, str] = {}
    for item in state.get("candidate_skills") or []:
        if len(criteria) >= max_candidates:
            break
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name == "none" or name in criteria:
            continue
        description = str(item.get("description") or "").strip()
        criteria[name] = description or f"Skill named {name}"
    criteria["none"] = "No skill should be loaded for this task"
    return criteria


def _config_for_state(config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    dynamic = copy.deepcopy(config)
    dynamic["questions"]["best_skill"]["criteria"] = _candidate_criteria(state, config)
    return dynamic


def _with_dynamic_config(state: dict[str, Any], fn: Callable[[], Any]) -> Any:
    original_load_config = _runner.load_config

    def load_config(gate_dir: Path | str) -> dict[str, Any]:
        config = original_load_config(gate_dir)
        if Path(gate_dir).resolve() == GATE_DIR:
            return _config_for_state(config, state)
        return config

    _runner.load_config = load_config
    try:
        return fn()
    finally:
        _runner.load_config = original_load_config


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    skill_needed_min = float(thresholds.get("skill_needed_min", 0.6))
    match_min_label = thresholds.get("match_strength_min", "partial")
    match_min_idx = _threshold_index(config, "match_strength", match_min_label)

    skill_needed = (answers.get("skill_needed") or {}).get("noul")
    best_skill = (answers.get("best_skill") or {}).get("choice")
    match_idx, match_label = _score_index(answers, config, "match_strength")
    candidate_count = max(0, len(((config.get("questions") or {}).get("best_skill") or {}).get("criteria", {})) - 1)

    if skill_needed is None or match_idx is None or best_skill is None:
        return _fail_decision(
            config,
            "missing skill_needed, best_skill, or match_strength",
            skill_needed=skill_needed,
            best_skill=best_skill,
            match_strength=match_label,
            candidate_count=candidate_count,
            thresholds={
                "skill_needed_min": skill_needed_min,
                "match_strength_min": match_min_label,
            },
        )

    load = float(skill_needed) >= skill_needed_min and match_idx >= match_min_idx and best_skill != "none"
    return {
        "action": "load_skill" if load else "skip_skill",
        "proceed": load,
        "reason": (
            f"load {best_skill}: skill_needed={skill_needed} >= {skill_needed_min} and "
            f"match_strength={match_label} >= {match_min_label}; candidates={candidate_count}"
            if load
            else f"skip: skill_needed={skill_needed} (min {skill_needed_min}), "
            f"match_strength={match_label} (min {match_min_label}), best_skill={best_skill}; "
            f"candidates={candidate_count}"
        ),
        "skill_needed": skill_needed,
        "best_skill": best_skill,
        "match_strength": match_label,
        "match_strength_index": match_idx,
        "candidate_count": candidate_count,
        "thresholds": {
            "skill_needed_min": skill_needed_min,
            "match_strength_min": match_min_label,
            "match_strength_min_index": match_min_idx,
            "max_candidates": int(thresholds.get("max_candidates", 8)),
        },
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _with_dynamic_config(state, lambda: _runner.decide(GATE_DIR, state, evaluate, write_dry=False))


def run_cli(gate_dir: Path | str, evaluate_fn: Callable[[dict, dict, dict], dict]) -> int:
    state = _runner.load_example_state(gate_dir)
    return _with_dynamic_config(state, lambda: _runner.run_cli(gate_dir, evaluate_fn))


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
