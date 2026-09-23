"""Thin Jev (TypeSafe System One) HTTP client."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .fixtures import load_fixture

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

# A Jev call made from inside a Copilot `preToolUse` hook is on a hard clock.
# The CLI kills a command hook at its `timeoutSec`, and a *timeout* is always
# fail-OPEN -- even for a safety gate, and even for an admin policy hook. A
# gate that gets killed therefore lets the tool through, which is exactly the
# opposite of what a safety gate must do.
#
# So the network call must finish, and the gate must return its own fail-mode
# decision, strictly inside the hook's budget. The harness sets JEV_TIMEOUT_S
# well below the configured timeoutSec for this reason. Only the standalone
# (non-hook) path gets the relaxed default.
DEFAULT_TIMEOUT_S = 60


def _timeout_s() -> float:
    raw = (os.environ.get("JEV_TIMEOUT_S") or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S

log = logging.getLogger("gates.jev_client")


def _mask_secrets(text: str) -> str:
    key = os.environ.get("TYPESAFE_API_KEY") or ""
    if key and key in text:
        return text.replace(key, "***REDACTED***")
    return text


def _mode() -> str:
    configured = (os.environ.get("JEV_MODE") or "").strip().lower()
    if configured:
        return configured
    return "live" if os.environ.get("TYPESAFE_API_KEY") else "fixture"


def _error_result(
    *,
    source: str,
    request_sans_auth: dict[str, Any],
    error: str,
    latency_ms: float = 0.0,
    http_status: int | None = None,
    raw: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "error": _mask_secrets(error),
        "model": None,
        "answers": {},
        "usage": {},
        "raw": raw,
        "request_sans_auth": request_sans_auth,
        "headers": headers or {},
        "source": source,
    }


def _fixture_result(
    *,
    fixture_path: Path | str | None,
    request_sans_auth: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    if fixture_path is None:
        msg = (
            "JEV_MODE=fixture but no fixture_path was provided; record one from a "
            "live result with gates.common.fixtures.record_fixture(path, result)"
        )
        log.error(msg)
        return _error_result(source="fixture", request_sans_auth=request_sans_auth, error=msg)

    data = load_fixture(fixture_path)
    if data is None:
        msg = (
            f"JEV_MODE=fixture but fixture was missing or invalid: {fixture_path}. "
            "Record one from a live result with "
            "gates.common.fixtures.record_fixture(path, result)."
        )
        log.error(msg)
        return _error_result(source="fixture", request_sans_auth=request_sans_auth, error=msg)

    answers = data.get("answers")
    if not isinstance(answers, dict):
        msg = f"fixture {fixture_path} must contain an 'answers' object"
        log.error(msg)
        return _error_result(source="fixture", request_sans_auth=request_sans_auth, error=msg, raw=data)

    latency = data.get("latency_ms", 0.0)
    try:
        latency_ms = float(latency)
    except (TypeError, ValueError):
        latency_ms = 0.0

    return {
        "ok": True,
        "http_status": 200,
        "latency_ms": latency_ms,
        "error": None,
        "model": data.get("model") or model,
        "answers": answers,
        "usage": data.get("usage") or {},
        "raw": data,
        "request_sans_auth": request_sans_auth,
        "headers": {"content-type": "application/json"},
        "source": "fixture",
    }


def call_jev(
    state: Any,
    questions: dict[str, Any],
    *,
    model: str = MODEL,
    timeout_s: float | None = None,
    fixture_path: Path | str | None = None,
) -> dict[str, Any]:
    if timeout_s is None:
        timeout_s = _timeout_s()
    request_sans_auth = {
        "model": model,
        "state": state,
        "questions": questions,
    }

    mode = _mode()
    if mode == "fixture":
        return _fixture_result(fixture_path=fixture_path, request_sans_auth=request_sans_auth, model=model)
    if mode != "live":
        msg = "JEV_MODE must be one of: live, fixture"
        log.error(msg)
        return _error_result(source="unknown", request_sans_auth=request_sans_auth, error=msg)

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        msg = "TYPESAFE_API_KEY not set in environment"
        log.error(msg)
        return _error_result(source="live", request_sans_auth=request_sans_auth, error=msg)

    body = json.dumps(request_sans_auth).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Cloudflare blocks urllib's default UA (Error 1010 browser_signature_banned).
            "User-Agent": "CopilotJevGates/1.0 (+https://api.typesafe.ai; Python)",
        },
        method="POST",
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw_bytes = resp.read()
            http_status = getattr(resp, "status", 200) or 200
            response_headers = {k.lower(): v for k, v in resp.headers.items()}
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        headers = {"content-type": response_headers.get("content-type")}
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except json.JSONDecodeError as e:
            msg = f"Jev response was not JSON: {e}"
            log.error(msg)
            return _error_result(
                source="live",
                request_sans_auth=request_sans_auth,
                error=msg,
                latency_ms=latency_ms,
                http_status=http_status,
                headers=headers,
            )
        return {
            "ok": True,
            "http_status": http_status,
            "latency_ms": latency_ms,
            "error": None,
            "model": data.get("model"),
            "answers": data.get("answers") or {},
            "usage": data.get("usage") or {},
            "raw": data,
            "request_sans_auth": request_sans_auth,
            "headers": headers,
            "source": "live",
        }
    except urllib.error.HTTPError as e:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        err_body = _mask_secrets(err_body)[:500]
        msg = f"HTTP {e.code}: {_mask_secrets(str(e.reason))}"
        if err_body:
            msg = f"{msg} | body={err_body}"
        log.error("Jev API error: %s", msg)
        raw: dict[str, Any] | None = None
        try:
            raw = json.loads(err_body) if err_body else None
        except json.JSONDecodeError:
            raw = {"body_text": err_body} if err_body else None
        headers = {"content-type": e.headers.get("content-type") if e.headers else None}
        return _error_result(
            source="live",
            request_sans_auth=request_sans_auth,
            error=msg,
            latency_ms=latency_ms,
            http_status=e.code,
            raw=raw,
            headers=headers,
        )
    except Exception as e:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        msg = f"{type(e).__name__}: {e}"
        log.error("Jev client failure: %s", _mask_secrets(msg))
        return _error_result(
            source="live",
            request_sans_auth=request_sans_auth,
            error=msg,
            latency_ms=latency_ms,
        )
