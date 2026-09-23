#!/usr/bin/env python3
"""external-write gate — local hard-policy checks plus shared runner."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

GATE_DIR = Path(__file__).resolve().parent
ROOT = GATE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.runner import decide as _decide  # noqa: E402
from common.runner import load_config, load_example_state, write_dry_result  # noqa: E402

SYD = ZoneInfo("Australia/Sydney")


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


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    state = _state(client_result)
    if state.get("channel_policy") == "read_only":
        return _read_only_decision(config, state)

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


def _policy_outcome(state: dict, config: dict, *, write_dry: bool = False) -> dict:
    slug = config.get("slug") or GATE_DIR.name
    name = config.get("name") or slug
    decision = _read_only_decision(config, state)
    outcome = {
        "slug": slug,
        "name": name,
        "ok": True,
        "http_status": None,
        "latency_ms": 0.0,
        "error": None,
        "model": None,
        "answers": {},
        "usage": {},
        "source": "policy",
        "decision": decision,
        "request_sans_auth": {"model": None, "state": state, "questions": config.get("questions") or {}},
        "as_of": datetime.now(SYD).strftime("%Y-%m-%d %H:%M:%S AEST"),
        "dry_path": None,
    }
    if write_dry:
        dry_path = write_dry_result(GATE_DIR, outcome, {"headers": {}}, dry_name=None)
        outcome["dry_path"] = str(dry_path)
    return outcome


def decide(state: dict, *, write_dry: bool = False) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    config = load_config(GATE_DIR)
    if isinstance(state, dict) and state.get("channel_policy") == "read_only":
        return _policy_outcome(state, config, write_dry=write_dry)
    return _decide(GATE_DIR, state, evaluate, write_dry=write_dry)


def run_cli_gate() -> int:
    state = load_example_state(GATE_DIR)
    outcome = decide(state, write_dry=True)
    d = outcome.get("decision") or {}
    print(
        f"[{outcome.get('slug')}] source={outcome.get('source')} "
        f"http={outcome.get('http_status')} latency_ms={outcome.get('latency_ms')} "
        f"ok={outcome.get('ok')} action={d.get('action')} "
        f"proceed={d.get('proceed')} dry={outcome.get('dry_path')}",
        file=sys.stderr,
    )
    summary = {
        "slug": outcome.get("slug"),
        "source": outcome.get("source"),
        "http_status": outcome.get("http_status"),
        "latency_ms": outcome.get("latency_ms"),
        "ok": outcome.get("ok"),
        "error": outcome.get("error"),
        "answers": outcome.get("answers"),
        "decision": outcome.get("decision"),
        "dry_path": outcome.get("dry_path"),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli_gate())
