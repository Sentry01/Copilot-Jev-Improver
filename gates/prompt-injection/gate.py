#!/usr/bin/env python3
"""prompt-injection gate — local hard rules plus shared runner."""
from __future__ import annotations

import base64
import binascii
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

GATE_DIR = Path(__file__).resolve().parent
ROOT = GATE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.runner import decide as _decide  # noqa: E402
from common.runner import load_config, load_example_state, write_dry_result  # noqa: E402

SYD = ZoneInfo("Australia/Sydney")

ZERO_WIDTH = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff"),
    None,
)

HOMOGLYPHS = str.maketrans(
    {
        "а": "a", "А": "A",
        "е": "e", "Е": "E",
        "і": "i", "І": "I",
        "ї": "i", "Ї": "I",
        "ј": "j", "Ј": "J",
        "о": "o", "О": "O",
        "р": "p", "Р": "P",
        "с": "c", "С": "C",
        "х": "x", "Х": "X",
        "у": "y", "У": "Y",
        "ѕ": "s", "Ѕ": "S",
        "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I",
        "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T",
        "Υ": "Y", "Χ": "X",
        "α": "a", "β": "b", "γ": "y", "δ": "d", "ε": "e", "ι": "i",
        "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u",
        "χ": "x",
    }
)

TOKEN_RE = re.compile(r"[a-z0-9]+")
BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/=])([A-Za-z0-9+/]{16,}={0,2})(?![A-Za-z0-9+/=])")

OVERRIDE_SEQUENCES = (
    ("ignore", "previous", "instructions"),
    ("ignore", "all", "previous", "instructions"),
    ("ignore", "prior", "instructions"),
    ("disregard", "previous", "instructions"),
    ("disregard", "prior", "instructions"),
    ("forget", "previous", "instructions"),
    ("forget", "prior", "instructions"),
    ("override", "system", "prompt"),
    ("reveal", "system", "prompt"),
    ("show", "system", "prompt"),
    ("print", "system", "prompt"),
    ("leak", "system", "prompt"),
    ("hidden", "instructions"),
    ("developer", "message"),
)

SECRET_TOKENS = frozenset(
    {
        "credential", "credentials", "secret", "secrets", "token", "tokens",
        "password", "passwords", "apikey", "api", "key", "keys", "env",
        "environment", "cookie", "cookies", "private",
    }
)
EXFIL_TOKENS = frozenset(
    {
        "send", "upload", "post", "curl", "exfiltrate", "exfil", "leak",
        "print", "reveal", "dump", "show", "paste", "transmit",
    }
)
EXEC_TOKENS = frozenset({"run", "execute", "exec", "shell", "bash", "sh", "invoke"})
DESTRUCTIVE_SEQUENCES = (
    ("rm", "rf"),
    ("git", "reset", "hard"),
    ("git", "clean"),
    ("git", "push", "force"),
    ("drop", "database"),
    ("drop", "table"),
    ("delete", "everything"),
    ("wipe", "workspace"),
    ("erase", "workspace"),
    ("mkfs",),
    ("dd", "if"),
)
BENIGN_CONTEXT_TOKENS = frozenset(
    {
        "advisory", "benign", "detection", "docs", "documentation", "example",
        "examples", "literal", "quoted", "regression", "sample", "security",
        "spec", "test", "training", "warning",
    }
)
NEGATION_TOKENS = frozenset({"not", "never", "dont", "do", "cannot", "shouldnt", "avoid"})


def _normalize(text: str) -> str:
    text = text.translate(ZERO_WIDTH)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(HOMOGLYPHS)
    return text.casefold()


def _tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(_normalize(text).replace("'", ""))


def _contains_sequence(tokens: list[str], sequence: tuple[str, ...]) -> bool:
    if not sequence or len(sequence) > len(tokens):
        return False
    end = len(tokens) - len(sequence) + 1
    return any(tuple(tokens[idx:idx + len(sequence)]) == sequence for idx in range(end))


def _contains_any_sequence(tokens: list[str], sequences: tuple[tuple[str, ...], ...]) -> bool:
    return any(_contains_sequence(tokens, sequence) for sequence in sequences)


def _has_prompt_injection_terms(tokens: list[str]) -> bool:
    return _contains_sequence(tokens, ("prompt", "injection")) or _contains_sequence(tokens, ("jailbreak",))


def _looks_like_benign_discussion(original: str, tokens: list[str]) -> bool:
    norm = _normalize(original)
    discusses_security = (
        _has_prompt_injection_terms(tokens)
        or _contains_any_sequence(tokens, OVERRIDE_SEQUENCES)
        or _contains_any_sequence(tokens, DESTRUCTIVE_SEQUENCES)
    )
    has_context = bool(set(tokens) & BENIGN_CONTEXT_TOKENS) or "e.g." in norm or "for example" in norm
    has_negation = bool(set(tokens) & NEGATION_TOKENS) or "do not follow" in norm or "do not execute" in norm
    has_quote_marker = any(mark in original for mark in ("`", "\"", "'", "“", "”", "‘", "’"))
    return discusses_security and has_context and (has_negation or has_quote_marker)


def _printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    printable = sum(1 for char in text if char.isprintable() or char in "\r\n\t")
    return printable / len(text)


def _decoded_candidates(text: str) -> list[tuple[str, str]]:
    decoded: list[tuple[str, str]] = []
    if "%" in text:
        unquoted = unquote(text)
        if unquoted != text and len(unquoted) >= 12:
            decoded.append(("percent", unquoted))

    seen: set[str] = set()
    for match in BASE64_RE.finditer(text):
        candidate = match.group(1)
        if candidate in seen:
            continue
        seen.add(candidate)
        padded = candidate + "=" * (-len(candidate) % 4)
        try:
            raw = base64.b64decode(padded, validate=True)
        except (binascii.Error, ValueError):
            continue
        if not (12 <= len(raw) <= 4096):
            continue
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if _printable_ratio(value) >= 0.85:
            decoded.append(("base64", value))
        if len(decoded) >= 8:
            break
    return decoded


def _classify_hard_rule(text: str) -> dict[str, Any] | None:
    texts = [("plain", text)]
    texts.extend(_decoded_candidates(text))

    for layer, candidate in texts:
        tokens = _tokens(candidate)
        if _looks_like_benign_discussion(candidate, tokens):
            continue

        if _contains_any_sequence(tokens, OVERRIDE_SEQUENCES):
            return {
                "rule": "instruction_override",
                "matched_layer": layer,
                "reason": "untrusted content attempts to override higher-priority instructions or reveal hidden prompts",
            }

        token_set = set(tokens)
        has_secret = bool(token_set & SECRET_TOKENS) or _contains_sequence(tokens, ("api", "key"))
        has_exfil = bool(token_set & EXFIL_TOKENS)
        if has_secret and has_exfil:
            return {
                "rule": "credential_or_env_exfiltration",
                "matched_layer": layer,
                "reason": "untrusted content asks the agent to reveal, print, send, or upload sensitive data",
            }

        has_destructive = _contains_any_sequence(tokens, DESTRUCTIVE_SEQUENCES)
        has_execute = bool(token_set & EXEC_TOKENS)
        if has_destructive and has_execute:
            return {
                "rule": "destructive_tool_instruction",
                "matched_layer": layer,
                "reason": "untrusted content asks the agent to execute a destructive command",
            }

    return None


def _decoded_layers(text: str) -> list[str]:
    return [layer for layer, _ in _decoded_candidates(text)]


def _noul(answers: dict[str, Any], key: str) -> float | None:
    value = (answers.get(key) or {}).get("noul")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _choice(answers: dict[str, Any], key: str) -> str | None:
    value = (answers.get(key) or {}).get("choice")
    return value if isinstance(value, str) else None


def _score_index(answers: dict[str, Any], config: dict[str, Any], key: str) -> tuple[int | None, str | None]:
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


def _closed(config: dict[str, Any], reason: str, **signals: Any) -> dict[str, Any]:
    default = config.get("default_on_error") or {"action": "quarantine_content", "proceed": False}
    return {
        "action": default.get("action", "quarantine_content"),
        "proceed": bool(default.get("proceed", False)),
        "reason": reason,
        "fail_mode_applied": "closed",
        **signals,
    }


def _state(client_result: dict[str, Any]) -> dict[str, Any]:
    request = client_result.get("request_sans_auth") or {}
    state = request.get("state") or {}
    return state if isinstance(state, dict) else {}


def evaluate(answers: dict[str, Any], config: dict[str, Any], client_result: dict[str, Any]) -> dict[str, Any]:
    state = _state(client_result)
    text = state.get("untrusted_content") if isinstance(state.get("untrusted_content"), str) else ""
    hard = _classify_hard_rule(text)
    if hard:
        return _policy_decision(config, state, hard)

    thresholds = config.get("thresholds") or {}
    safe_min = float(thresholds.get("safe_to_consume_min", 0.8))
    allowed = set(thresholds.get("allowed_injection_intent", ["none", "benign_discussion"]))
    severity_max_label = thresholds.get("severity_max", "low")
    criteria = (((config.get("questions") or {}).get("severity") or {}).get("criteria") or [])
    severity_max_idx = criteria.index(severity_max_label) if severity_max_label in criteria else None

    safe = _noul(answers, "safe_to_consume")
    intent = _choice(answers, "injection_intent")
    severity_idx, severity = _score_index(answers, config, "severity")
    base = {
        "safe_to_consume": safe,
        "injection_intent": intent,
        "severity": severity,
        "severity_index": severity_idx,
        "thresholds": {
            "safe_to_consume_min": safe_min,
            "allowed_injection_intent": sorted(allowed),
            "severity_max": severity_max_label,
            "severity_max_index": severity_max_idx,
        },
    }

    if safe is None or intent is None or severity_idx is None or severity_max_idx is None:
        return _closed(config, "missing safe_to_consume, injection_intent, or severity; fail-closed", **base)

    consume = safe >= safe_min and intent in allowed and severity_idx <= severity_max_idx
    return {
        "action": "consume_content" if consume else "quarantine_content",
        "proceed": consume,
        "reason": (
            f"safe_to_consume={safe} >= {safe_min}, injection_intent={intent}, severity={severity} <= {severity_max_label}"
            if consume
            else f"blocked: safe_to_consume={safe} (min {safe_min}) injection_intent={intent} (allowed {sorted(allowed)}) severity={severity} (max {severity_max_label})"
        ),
        **base,
    }


def _policy_decision(config: dict[str, Any], state: dict[str, Any], hard: dict[str, Any] | None) -> dict[str, Any]:
    thresholds = config.get("thresholds") or {}
    text = state.get("untrusted_content") if isinstance(state.get("untrusted_content"), str) else ""
    decoded_layers = _decoded_layers(text)
    if hard:
        return {
            "action": "quarantine_content",
            "proceed": False,
            "reason": f"{hard['reason']}; hard policy block before Jev",
            "safe_to_consume": 0.0,
            "injection_intent": hard["rule"],
            "severity": "critical" if hard["rule"] != "instruction_override" else "high",
            "severity_index": 4 if hard["rule"] != "instruction_override" else 3,
            "hard_rule_applied": hard["rule"],
            "matched_layer": hard["matched_layer"],
            "decoded_layers": decoded_layers,
            "thresholds": {
                "safe_to_consume_min": thresholds.get("safe_to_consume_min", 0.8),
                "allowed_injection_intent": thresholds.get("allowed_injection_intent", ["none", "benign_discussion"]),
                "severity_max": thresholds.get("severity_max", "low"),
            },
        }

    return {
        "action": "consume_content",
        "proceed": True,
        "reason": "benign quoted or negated prompt-injection discussion; local allow before Jev",
        "safe_to_consume": 1.0,
        "injection_intent": "benign_discussion",
        "severity": "low",
        "severity_index": 1,
        "hard_rule_applied": "benign_discussion",
        "decoded_layers": decoded_layers,
        "thresholds": {
            "safe_to_consume_min": thresholds.get("safe_to_consume_min", 0.8),
            "allowed_injection_intent": thresholds.get("allowed_injection_intent", ["none", "benign_discussion"]),
            "severity_max": thresholds.get("severity_max", "low"),
        },
    }


def _policy_outcome(state: dict[str, Any], config: dict[str, Any], decision: dict[str, Any],
                    *, write_dry: bool = False) -> dict[str, Any]:
    slug = config.get("slug") or GATE_DIR.name
    name = config.get("name") or slug
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


def decide(state: dict[str, Any], *, write_dry: bool = False) -> dict[str, Any]:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    config = load_config(GATE_DIR)
    text = state.get("untrusted_content") if isinstance(state, dict) and isinstance(state.get("untrusted_content"), str) else ""
    if isinstance(state, dict) and state.get("content_available") is False:
        decision = {
            "action": "consume_content",
            "proceed": True,
            "reason": "no returned content available to inspect at this hook point; allow retrieval without treating source metadata as instructions",
            "safe_to_consume": 1.0,
            "injection_intent": "none",
            "severity": "none",
            "severity_index": 0,
            "hard_rule_applied": "no_returned_content",
            "decoded_layers": [],
            "thresholds": {
                "safe_to_consume_min": (config.get("thresholds") or {}).get("safe_to_consume_min", 0.8),
                "allowed_injection_intent": (config.get("thresholds") or {}).get("allowed_injection_intent", ["none", "benign_discussion"]),
                "severity_max": (config.get("thresholds") or {}).get("severity_max", "low"),
            },
        }
        return _policy_outcome(state, config, decision, write_dry=write_dry)
    tokens = _tokens(text)
    if _looks_like_benign_discussion(text, tokens):
        return _policy_outcome(state, config, _policy_decision(config, state, None), write_dry=write_dry)
    hard = _classify_hard_rule(text)
    if hard:
        return _policy_outcome(state, config, _policy_decision(config, state, hard), write_dry=write_dry)
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
