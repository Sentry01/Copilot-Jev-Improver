"""Fixture helpers for Jev gate runs."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("gates.fixtures")


def fixture_path_for(gate_dir: Path | str, name: str) -> Path:
    return Path(gate_dir).resolve() / "fixtures" / f"{name}.json"


def load_fixture(path: Path | str) -> dict[str, Any] | None:
    fixture_path = Path(path)
    if not fixture_path.exists():
        log.warning("fixture not found: %s", fixture_path)
        return None
    try:
        with fixture_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not load fixture %s: %s", fixture_path, e)
        return None
    if not isinstance(data, dict):
        log.warning("fixture %s must contain a JSON object", fixture_path)
        return None
    return data


def record_fixture(path: Path | str, client_result: dict[str, Any]) -> Path:
    if client_result.get("source") != "live":
        raise ValueError("refusing to record fixture from non-live client result")

    payload = {
        "model": client_result.get("model"),
        "answers": client_result.get("answers") or {},
        "usage": client_result.get("usage") or {},
        "latency_ms": client_result.get("latency_ms"),
    }
    fixture_path = Path(path)
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    with fixture_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log.info("recorded Jev fixture %s", fixture_path)
    return fixture_path
