"""Shared gate runner: load config + state, call Jev, apply evaluate(), write dry/."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import jev_client
from .fixtures import fixture_path_for

SYD = ZoneInfo("Australia/Sydney")
log = logging.getLogger("gates.runner")

EvaluateFn = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_config(gate_dir: Path | str) -> dict[str, Any]:
    return load_json(Path(gate_dir) / "config.json")


def load_example_state(gate_dir: Path | str) -> Any:
    return load_json(Path(gate_dir) / "example_state.json")


def _fail_open_decision(config: dict[str, Any], error: str) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    action = default.get("action", "continue")
    proceed = bool(default.get("proceed", True))
    return {
        "action": action,
        "proceed": proceed,
        "reason": f"fail-open on API error: {error}",
        "fail_mode_applied": "open",
        "api_error": error,
    }


def _fail_closed_decision(config: dict[str, Any], error: str) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    action = default.get("action", "block")
    proceed = bool(default.get("proceed", False))
    return {
        "action": action,
        "proceed": proceed,
        "reason": f"fail-closed on API error: {error}",
        "fail_mode_applied": "closed",
        "api_error": error,
    }


def _resolve_fixture_path(gate_dir: Path, slug: str, fixture: Path | str | None) -> Path:
    if fixture is None:
        return fixture_path_for(gate_dir, slug)

    candidate = Path(fixture)
    if candidate.is_absolute() or len(candidate.parts) > 1:
        return candidate if candidate.is_absolute() else (gate_dir / candidate).resolve()
    if candidate.suffix == ".json":
        return fixture_path_for(gate_dir, candidate.stem)
    return fixture_path_for(gate_dir, str(fixture))


def decide(
    gate_dir: Path | str,
    state: Any,
    evaluate: EvaluateFn,
    *,
    write_dry: bool = False,
    dry_name: str | None = None,
    fixture: Path | str | None = None,
) -> dict[str, Any]:
    gate_dir = Path(gate_dir).resolve()
    config = load_config(gate_dir)
    slug = config.get("slug") or gate_dir.name
    name = config.get("name") or slug
    questions = config["questions"]
    fail_mode = (config.get("fail_mode") or "open").lower()
    resolved_fixture_path = _resolve_fixture_path(gate_dir, slug, fixture)

    client_result = jev_client.call_jev(state, questions, fixture_path=resolved_fixture_path)

    if not client_result.get("ok"):
        err = client_result.get("error") or "unknown API error"
        if fail_mode == "closed":
            decision = _fail_closed_decision(config, err)
        else:
            decision = _fail_open_decision(config, err)
    else:
        try:
            decision = evaluate(
                client_result.get("answers") or {},
                config,
                client_result,
            )
        except Exception as e:
            log.exception("evaluate() raised for slug=%s", slug)
            err = f"evaluate_error: {type(e).__name__}: {e}"
            if fail_mode == "closed":
                decision = _fail_closed_decision(config, err)
            else:
                decision = _fail_open_decision(config, err)

    outcome = {
        "slug": slug,
        "name": name,
        "ok": bool(client_result.get("ok")),
        "http_status": client_result.get("http_status"),
        "latency_ms": client_result.get("latency_ms"),
        "error": client_result.get("error"),
        "model": client_result.get("model"),
        "answers": client_result.get("answers") or {},
        "usage": client_result.get("usage") or {},
        "source": client_result.get("source"),
        "decision": decision,
        "request_sans_auth": client_result.get("request_sans_auth"),
        "as_of": datetime.now(SYD).strftime("%Y-%m-%d %H:%M:%S AEST"),
        "dry_path": None,
    }

    if write_dry:
        dry_path = write_dry_result(gate_dir, outcome, client_result, dry_name=dry_name)
        outcome["dry_path"] = str(dry_path)

    return outcome


def write_dry_result(
    gate_dir: Path,
    outcome: dict[str, Any],
    client_result: dict[str, Any],
    *,
    dry_name: str | None = None,
) -> Path:
    slug = outcome.get("slug") or gate_dir.name
    fname = dry_name or f"dry_{slug.replace('-', '_')}.json"
    path = gate_dir / "dry" / fname
    payload = {
        "meta": {
            "name": fname.replace(".json", ""),
            "slug": slug,
            "source": outcome.get("source"),
            "http_status": outcome.get("http_status"),
            "latency_ms": outcome.get("latency_ms"),
            "error": outcome.get("error"),
            "as_of": outcome.get("as_of"),
            "headers": client_result.get("headers") or {},
        },
        "request_sans_auth": outcome.get("request_sans_auth"),
        "response": {
            "model": outcome.get("model"),
            "answers": outcome.get("answers"),
            "usage": outcome.get("usage"),
        }
        if outcome.get("ok")
        else (client_result.get("raw") or {"error": outcome.get("error")}),
        "decision": outcome.get("decision"),
    }
    write_json(path, payload)
    log.info("wrote dry result %s (http=%s latency_ms=%s)", path, outcome.get("http_status"), outcome.get("latency_ms"))
    return path


def run_cli(gate_dir: Path | str, evaluate: EvaluateFn) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    gate_dir = Path(gate_dir).resolve()
    state = load_example_state(gate_dir)
    outcome = decide(gate_dir, state, evaluate, write_dry=True)

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
