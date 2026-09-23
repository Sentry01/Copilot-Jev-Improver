#!/usr/bin/env python3
"""Measure Copilot Jev gate latency and model session-level impact.

Runs offline with fixture-backed Jev responses only:

    env -u TYPESAFE_API_KEY JEV_MODE=fixture python3 experiments/latency/bench.py

The benchmark intentionally measures both in-process components and the real
hook shape: a fresh Python process with JSON piped to the hook's stdin.
"""
from __future__ import annotations

import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
HARNESS_DIR = REPO_ROOT / "harness" / "copilot-jev-gates"
PRE_TOOL_HOOK = HARNESS_DIR / "hooks" / "pre_tool_use.py"
POST_FAILURE_HOOK = HARNESS_DIR / "hooks" / "post_tool_use_failure.py"
HOOKS_JSON = HARNESS_DIR / "hooks" / "hooks.json"
BASELINE_JSON = REPO_ROOT / "telemetry" / "reports" / "baseline-2026-09-23.json"
RESULTS_JSON = HERE / "results.json"
RESULTS_MD = HERE / "RESULTS.md"
DATA_DIR = HERE / "data"
LARGE_READ_FILE = DATA_DIR / "large_read_fixture.txt"
SMALL_READ_FILE = DATA_DIR / "small_read_fixture.txt"

# Reproduced from telemetry/queries/07-09 with session_store_sql on 2026-09-23.
# The baseline JSON carries local model/session aggregates; its markdown caveat
# states these tool-level rows come from the cloud session store and the checked-in
# SQL is the reproduction method. Keep the values aggregate-only.
TOOL_SESSIONS = 59
TOTAL_TOOL_CALLS = 3970
TOOL_MIX: dict[str, dict[str, float | int | None]] = {
    "bash": {"calls": 2060, "failures": 6, "fail_pct": 0.3, "avg_ms": 9107, "total_seconds": 18077},
    "edit": {"calls": 480, "failures": 5, "fail_pct": 1.0, "avg_ms": 256, "total_seconds": 120},
    "view": {"calls": 372, "failures": 6, "fail_pct": 1.6, "avg_ms": 908, "total_seconds": 310},
    "kusto-explorer-kusto_query_readonly": {"calls": 152, "failures": 20, "fail_pct": 13.2, "avg_ms": 8665, "total_seconds": 1317},
    "open_canvas": {"calls": 68, "failures": 11, "fail_pct": 16.2, "avg_ms": 139, "total_seconds": 9},
    "create": {"calls": 64, "failures": 5, "fail_pct": 7.8, "avg_ms": 549, "total_seconds": 30},
    "playwright-browser_navigate": {"calls": 52, "failures": 31, "fail_pct": 59.6, "avg_ms": 156, "total_seconds": 8},
    "ask_user": {"calls": 50, "failures": 0, "fail_pct": 0.0, "avg_ms": 3219314, "total_seconds": 160966},
    "playwright-browser_snapshot": {"calls": 43, "failures": 1, "fail_pct": 2.3, "avg_ms": 178, "total_seconds": 8},
    "web_fetch": {"calls": 41, "failures": 2, "fail_pct": 4.9, "avg_ms": 1864, "total_seconds": 69},
    "read_bash": {"calls": 39, "failures": 0, "fail_pct": 0.0, "avg_ms": 118617, "total_seconds": 4389},
    "sql": {"calls": 35, "failures": 0, "fail_pct": 0.0, "avg_ms": 114, "total_seconds": 4},
    "send_session_message": {"calls": 31, "failures": 0, "fail_pct": 0.0, "avg_ms": 852, "total_seconds": 26},
    "playwright-browser_click": {"calls": 28, "failures": 22, "fail_pct": 78.6, "avg_ms": 3762, "total_seconds": 105},
    "invoke_canvas_action": {"calls": 28, "failures": 2, "fail_pct": 7.1, "avg_ms": 914, "total_seconds": 26},
    "kusto-explorer-kusto_mgmt_show": {"calls": 27, "failures": 5, "fail_pct": 18.5, "avg_ms": 2809, "total_seconds": 76},
    "rg": {"calls": 19, "failures": 1, "fail_pct": 5.3, "avg_ms": 434, "total_seconds": 7},
    "glob": {"calls": 18, "failures": 0, "fail_pct": 0.0, "avg_ms": 629, "total_seconds": 10},
    "task": {"calls": 10, "failures": 0, "fail_pct": 0.0, "avg_ms": 174362, "total_seconds": 1744},
    "web_search": {"calls": 10, "failures": 0, "fail_pct": 0.0, "avg_ms": 38961, "total_seconds": 273},
    "reply_and_resolve_review_thread": {"calls": 7, "failures": 0, "fail_pct": 0.0, "avg_ms": 2057, "total_seconds": 14},
    "create_pull_request": {"calls": 4, "failures": 0, "fail_pct": 0.0, "avg_ms": 3475, "total_seconds": 14},
    "reply_to_comment": {"calls": 3, "failures": 0, "fail_pct": 0.0, "avg_ms": 38, "total_seconds": 0},
    "slack-slack_search_public": {"calls": 1, "failures": 0, "fail_pct": 0.0, "avg_ms": 954, "total_seconds": 1},
    "workiq-fetch": {"calls": 1, "failures": 0, "fail_pct": 0.0, "avg_ms": 5507, "total_seconds": 6},
}

BASH_INTENT = {
    "search_via_bash": 747,
    "run_code_or_tests": 474,
    "other": 382,
    "git": 203,
    "gh_cli": 125,
    "network_or_cloud": 121,
    "list_via_bash": 44,
    "read_file_via_bash": 40,
}

REDUNDANT_CALLS = {
    "bash": 77,
    "view": 46,
    "playwright-browser_snapshot": 26,
    "create": 13,
    "edit": 12,
    "report_progress": 11,
    "github-mcp-server-get_file_contents": 8,
    "playwright-browser_navigate": 7,
    "skill": 6,
    "invoke_canvas_action": 6,
    "read_bash": 6,
    "runtime-tools-secret_scanning": 5,
    "github-mcp-server-actions_list": 4,
    "github-mcp-server-search_code": 4,
    "playwright-browser_click": 4,
    "rg": 4,
    "codeql_checker": 4,
    "web_fetch": 4,
    "runtime-tools-store_memory": 3,
    "web_search": 3,
    "computer-use-click": 2,
    "glob": 2,
    "apply_patch": 2,
    "grep": 2,
    "github-mcp-server-list_pull_requests": 1,
}

FAILURE_HOOK_CANDIDATES = {
    "playwright-browser_navigate": 31,
    "playwright-browser_click": 22,
    "kusto-explorer-kusto_query_readonly": 20,
    "open_canvas": 11,
    "bash": 6,
    "kusto-explorer-kusto_mgmt_show": 5,
    "playwright-browser_type": 3,
    "web_fetch": 2,
    "playwright-browser_snapshot": 1,
    "kusto-explorer-kusto_principal_roles": 1,
    "playwright-browser_take_screenshot": 1,
}


def bench_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("TYPESAFE_API_KEY", None)
    env["JEV_MODE"] = "fixture"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["COPILOT_JEV_GATES_ROOT"] = str(REPO_ROOT / "gates")
    return env


def ensure_read_fixtures() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LARGE_READ_FILE.exists():
        LARGE_READ_FILE.write_text(
            "".join(f"large fixture line {i:04d}\n" for i in range(1, 1001)),
            encoding="utf-8",
        )
    if not SMALL_READ_FILE.exists():
        SMALL_READ_FILE.write_text(
            "".join(f"small fixture line {i:04d}\n" for i in range(1, 41)),
            encoding="utf-8",
        )


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return ordered[idx]


def summarise(name: str, samples_ms: list[float], *, kind: str, notes: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "iterations": len(samples_ms),
        "median_ms": round(statistics.median(samples_ms), 4),
        "p95_ms": round(percentile(samples_ms, 95), 4),
        "mean_ms": round(statistics.fmean(samples_ms), 4),
        "min_ms": round(min(samples_ms), 4),
        "max_ms": round(max(samples_ms), 4),
        "notes": notes,
    }


def time_callable(
    name: str,
    fn: Callable[[], Any],
    *,
    iterations: int,
    warmups: int,
    kind: str,
    notes: str = "",
) -> dict[str, Any]:
    for _ in range(warmups):
        fn()
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        result = fn()
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        samples.append(elapsed_ms)
        if result is False:
            raise RuntimeError(f"benchmark {name} returned False")
    return summarise(name, samples, kind=kind, notes=notes)


def parse_hook_stdout(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.strip() and '"type": "progress"' not in line]
    if not lines:
        return {}
    return json.loads("".join(lines))


def run_subprocess(command: list[str], *, stdin: str | None = None, parse_json: bool = False) -> Any:
    proc = subprocess.run(
        command,
        input=stdin,
        cwd=REPO_ROOT,
        env=bench_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"subprocess failed ({proc.returncode}): {' '.join(command)}\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
        )
    if parse_json:
        return parse_hook_stdout(proc.stdout)
    return proc.stdout


def time_subprocess(
    name: str,
    command: list[str],
    *,
    stdin: str | None = None,
    iterations: int,
    warmups: int,
    kind: str,
    notes: str = "",
    validator: Callable[[Any], bool] | None = None,
    parse_json: bool = False,
) -> dict[str, Any]:
    for _ in range(warmups):
        out = run_subprocess(command, stdin=stdin, parse_json=parse_json)
        if validator and not validator(out):
            raise RuntimeError(f"warmup validation failed for {name}: {out}")
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        out = run_subprocess(command, stdin=stdin, parse_json=parse_json)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        if validator and not validator(out):
            raise RuntimeError(f"validation failed for {name}: {out}")
        samples.append(elapsed_ms)
    return summarise(name, samples, kind=kind, notes=notes)


def import_harness() -> Any:
    if str(HARNESS_DIR) not in sys.path:
        sys.path.insert(0, str(HARNESS_DIR))
    os.environ.update(bench_env())
    import harness  # type: ignore

    return harness


def run_measurements() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ensure_read_fixtures()
    harness = import_harness()
    cwd = str(REPO_ROOT)

    cheap_payload = {"toolName": "edit", "toolArgs": {"path": "a.py"}, "cwd": cwd}
    policy_payload = {
        "toolName": "slack-SendMessageToChannel",
        "toolArgs": {"text": "hi"},
        "cwd": cwd,
    }
    fixture_payload = {"toolName": "bash", "toolArgs": {"command": "npm test"}, "cwd": cwd}
    large_view_payload = {"toolName": "view", "toolArgs": {"path": str(LARGE_READ_FILE)}, "cwd": cwd}
    post_failure_payload = {
        "toolName": "playwright-browser_click",
        "error": "element not found",
        "cwd": cwd,
    }

    sys_exe = sys.executable
    startup_command = [
        sys_exe,
        "-B",
        "-c",
        (
            "import runpy; "
            f"runpy.run_path({str(PRE_TOOL_HOOK)!r})"
        ),
    ]
    pre_hook_command = [sys_exe, "-B", str(PRE_TOOL_HOOK)]
    post_hook_command = [sys_exe, "-B", str(POST_FAILURE_HOOK)]

    measurements: list[dict[str, Any]] = []
    measurements.append(
        time_subprocess(
            "subprocess_python_plus_pre_tool_import",
            startup_command,
            iterations=80,
            warmups=8,
            kind="subprocess",
            notes="Fresh interpreter plus executing pre_tool_use.py top-level imports; no payload processing.",
        )
    )
    measurements.append(
        time_callable(
            "route_pre_tool_use_not_gated_edit",
            lambda: harness.route_pre_tool_use("edit", {"path": "a.py"}, cwd) is None,
            iterations=20_000,
            warmups=500,
            kind="in_process",
            notes="Direct harness.route_pre_tool_use() None path for a cheap tool.",
        )
    )
    measurements.append(
        time_callable(
            "violates_read_only_policy_check",
            lambda: harness.violates_read_only("slack-SendMessageToChannel"),
            iterations=20_000,
            warmups=500,
            kind="in_process",
            notes="Pure local read-only policy predicate used before any Jev call.",
        )
    )

    external_write_gate = harness.load_gate("external-write")
    policy_state = {
        "action": "slack-SendMessageToChannel",
        "destination": "channel",
        "content_summary": "hi",
        "user_authorised": False,
        "channel_policy": "read_only",
        "reversible": "editable",
    }
    measurements.append(
        time_callable(
            "external_write_decide_source_policy",
            lambda: external_write_gate.decide(policy_state).get("source") == "policy",
            iterations=5_000,
            warmups=200,
            kind="in_process",
            notes="Full gate-local hard-rule decision; source=policy and zero network.",
        )
    )
    measurements.append(
        time_callable(
            "tool_worth_it_full_gate_source_fixture",
            lambda: harness.run_gate(
                "tool-worth-it",
                {
                    "user_goal": "run project tests",
                    "already_have": "",
                    "proposed_tool": "bash: npm test",
                    "est_cost_tier": "medium",
                    "est_latency_ms": 9100,
                },
            ).get("source") == "fixture",
            iterations=2_000,
            warmups=100,
            kind="in_process",
            notes="Dynamic gate load + config load + fixture replay + evaluate(); no subprocess.",
        )
    )
    measurements.append(
        time_callable(
            "unbounded_large_read_large_file",
            lambda: isinstance(
                harness.unbounded_large_read("view", {"path": str(LARGE_READ_FILE)}),
                int,
            ),
            iterations=10_000,
            warmups=500,
            kind="in_process",
            notes="Local file-size prefilter on a 1000-line file; implementation counts to 601 lines.",
        )
    )
    measurements.append(
        time_callable(
            "unbounded_large_read_small_file",
            lambda: harness.unbounded_large_read("view", {"path": str(SMALL_READ_FILE)}) is None,
            iterations=10_000,
            warmups=500,
            kind="in_process",
            notes="Same prefilter on a small file that should not be gated.",
        )
    )

    measurements.append(
        time_subprocess(
            "hook_e2e_cheap_tool_allow",
            pre_hook_command,
            stdin=json.dumps(cheap_payload),
            iterations=80,
            warmups=8,
            kind="hook_e2e",
            notes="Actual preToolUse subprocess with JSON stdin; cheap tool returns allow without a gate.",
            parse_json=True,
            validator=lambda out: out.get("permissionDecision") == "allow",
        )
    )
    measurements.append(
        time_subprocess(
            "hook_e2e_readonly_policy_deny",
            pre_hook_command,
            stdin=json.dumps(policy_payload),
            iterations=80,
            warmups=8,
            kind="hook_e2e",
            notes="Actual preToolUse subprocess; read-only write violation denied locally before Jev.",
            parse_json=True,
            validator=lambda out: out.get("permissionDecision") == "deny",
        )
    )
    measurements.append(
        time_subprocess(
            "hook_e2e_fixture_gate_bash",
            pre_hook_command,
            stdin=json.dumps(fixture_payload),
            iterations=80,
            warmups=8,
            kind="hook_e2e",
            notes="Actual preToolUse subprocess; bash routes to tool-worth-it with source=fixture.",
            parse_json=True,
            validator=lambda out: out.get("permissionDecision") in {"allow", "ask", "deny"},
        )
    )
    measurements.append(
        time_subprocess(
            "hook_e2e_large_view_fixture_gate",
            pre_hook_command,
            stdin=json.dumps(large_view_payload),
            iterations=50,
            warmups=5,
            kind="hook_e2e",
            notes="Actual preToolUse subprocess; large unbounded view routes to context-read-budget fixture.",
            parse_json=True,
            validator=lambda out: out.get("permissionDecision") == "allow" and "modifiedArgs" in out,
        )
    )
    measurements.append(
        time_subprocess(
            "post_failure_retry_fixture_gate",
            post_hook_command,
            stdin=json.dumps(post_failure_payload),
            iterations=80,
            warmups=8,
            kind="hook_e2e",
            notes="Actual postToolUseFailure subprocess; browser click failure routes to retry-worth-it fixture.",
            parse_json=True,
            validator=lambda out: "additionalContext" in out,
        )
    )

    metadata = {
        "payloads": {
            "cheap": cheap_payload,
            "policy": policy_payload,
            "fixture": fixture_payload,
            "large_view": large_view_payload,
            "post_failure": post_failure_payload,
        },
        "fixtures": {
            "large_read_file": str(LARGE_READ_FILE.relative_to(REPO_ROOT)),
            "small_read_file": str(SMALL_READ_FILE.relative_to(REPO_ROOT)),
        },
        "harness_sets": {
            "cheap_tools": sorted(harness.CHEAP_TOOLS),
            "expensive_tools": sorted(harness.EXPENSIVE_TOOLS),
        },
    }
    return measurements, metadata


def by_name(measurements: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for item in measurements:
        if item["name"] == name:
            return item
    raise KeyError(name)


def load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_JSON.read_text(encoding="utf-8"))


def hook_matcher(event_name: str) -> str:
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    hooks = ((data.get("hooks") or {}).get(event_name) or [])
    if not hooks:
        return ""
    return str(hooks[0].get("matcher") or "")


def matched_tool_counts(event_name: str) -> dict[str, int]:
    matcher = hook_matcher(event_name)
    if not matcher:
        return {}
    pattern = re.compile(matcher)
    matched: dict[str, int] = {}
    for tool, row in TOOL_MIX.items():
        calls = row.get("calls")
        if isinstance(calls, int) and pattern.fullmatch(tool):
            matched[tool] = calls
    return matched


def model_session_impact(measurements: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    cheap_hook_s = by_name(measurements, "hook_e2e_cheap_tool_allow")["median_ms"] / 1000.0
    fixture_hook_s = by_name(measurements, "hook_e2e_fixture_gate_bash")["median_ms"] / 1000.0
    policy_hook_s = by_name(measurements, "hook_e2e_readonly_policy_deny")["median_ms"] / 1000.0
    post_failure_s = by_name(measurements, "post_failure_retry_fixture_gate")["median_ms"] / 1000.0

    pretool_matched_by_tool = matched_tool_counts("preToolUse")
    pretool_matched_calls = sum(pretool_matched_by_tool.values())
    # The 30-day telemetry has no matched read-only write attempts, so the actual
    # current-path estimate treats every matched preToolUse candidate as a fixture gate.
    policy_pretool_calls = 0
    fixture_pretool_calls = pretool_matched_calls - policy_pretool_calls
    post_failure_calls = sum(FAILURE_HOOK_CANDIDATES.values())
    unmatched_tool_calls = max(0, TOTAL_TOOL_CALLS - pretool_matched_calls)

    current_pretool_s = fixture_pretool_calls * fixture_hook_s + policy_pretool_calls * policy_hook_s
    current_post_failure_s = post_failure_calls * post_failure_s
    current_total_s = current_pretool_s + current_post_failure_s
    all_tools_total_s = current_total_s + unmatched_tool_calls * cheap_hook_s

    duplicate_bash_s = REDUNDANT_CALLS["bash"] * (TOOL_MIX["bash"]["avg_ms"] or 0) / 1000.0
    duplicate_all_known_s = 0.0
    duplicate_all_known_calls = 0
    for tool, wasted in REDUNDANT_CALLS.items():
        avg = (TOOL_MIX.get(tool) or {}).get("avg_ms")
        if isinstance(avg, (int, float)):
            duplicate_all_known_s += wasted * avg / 1000.0
            duplicate_all_known_calls += wasted

    bash_read_calls = BASH_INTENT["search_via_bash"] + BASH_INTENT["list_via_bash"] + BASH_INTENT["read_file_via_bash"]
    # Conservative comparator: built-in read/search/list calls in this telemetry average under 1s.
    builtin_readish_avg_ms = statistics.fmean([
        TOOL_MIX["view"]["avg_ms"],
        TOOL_MIX["rg"]["avg_ms"],
        TOOL_MIX["glob"]["avg_ms"],
    ])
    bash_to_builtin_s = bash_read_calls * max(0.0, (TOOL_MIX["bash"]["avg_ms"] - builtin_readish_avg_ms) / 1000.0)  # type: ignore[operator]
    duplicate_browser_click_s = REDUNDANT_CALLS["playwright-browser_click"] * (TOOL_MIX["playwright-browser_click"]["avg_ms"] or 0) / 1000.0
    failed_browser_click_s = FAILURE_HOOK_CANDIDATES["playwright-browser_click"] * (TOOL_MIX["playwright-browser_click"]["avg_ms"] or 0) / 1000.0

    def calls_to_break_even(save_s: float, overhead_s: float = current_total_s) -> int | None:
        if save_s <= 0:
            return None
        return math.ceil(overhead_s / save_s)

    break_even_targets = []
    startup_plus_live_400_s = cheap_hook_s + 0.400
    for tool in ["edit", "view", "web_fetch", "bash", "web_search", "task", "playwright-browser_click"]:
        avg_ms = TOOL_MIX[tool]["avg_ms"]
        if not isinstance(avg_ms, (int, float)) or avg_ms <= 0:
            continue
        overhead_s = post_failure_s if tool == "playwright-browser_click" else fixture_hook_s
        break_even_targets.append(
            {
                "saved_tool": tool,
                "avg_saved_ms": avg_ms,
                "fixture_gate_must_be_right_pct": round((overhead_s / (avg_ms / 1000.0)) * 100.0, 2),
                "live_400ms_gate_must_be_right_pct": round((startup_plus_live_400_s / (avg_ms / 1000.0)) * 100.0, 2),
            }
        )

    return {
        "telemetry_source": {
            "baseline_json": str(BASELINE_JSON.relative_to(REPO_ROOT)),
            "cloud_query_rows": "telemetry/queries/07-tool-mix.sql, 08-redundant-tool-calls.sql, 09-bash-intent-split.sql reproduced with session_store_sql on 2026-09-23",
            "tool_sessions": TOOL_SESSIONS,
            "total_tool_calls": TOTAL_TOOL_CALLS,
            "baseline_window": baseline.get("window"),
            "baseline_as_of": baseline.get("as_of"),
        },
        "routing_counts": {
            "current_hooks_json_pretool_matched_calls": pretool_matched_calls,
            "fixture_pretool_calls": fixture_pretool_calls,
            "policy_pretool_calls": policy_pretool_calls,
            "unmatched_tool_calls": unmatched_tool_calls,
            "post_failure_hook_calls": post_failure_calls,
            "pretool_matcher": hook_matcher("preToolUse"),
            "pretool_matched_by_tool": pretool_matched_by_tool,
            "failure_hook_candidates": FAILURE_HOOK_CANDIDATES,
        },
        "overhead_seconds_30d": {
            "current_hooks_json_pretool": round(current_pretool_s, 2),
            "current_post_tool_use_failure": round(current_post_failure_s, 2),
            "current_total": round(current_total_s, 2),
            "current_total_per_session": round(current_total_s / TOOL_SESSIONS, 2),
            "hypothetical_if_pretool_hook_matched_all_tools": round(all_tools_total_s, 2),
            "hypothetical_all_tools_per_session": round(all_tools_total_s / TOOL_SESSIONS, 2),
        },
        "plausible_savings_seconds_30d": {
            "duplicate_bash_only": round(duplicate_bash_s, 2),
            "duplicate_known_latency_tools": round(duplicate_all_known_s, 2),
            "duplicate_known_latency_calls": duplicate_all_known_calls,
            "bash_readish_replaced_by_builtin_upper_bound": round(bash_to_builtin_s, 2),
            "duplicate_browser_click_only": round(duplicate_browser_click_s, 2),
            "all_failed_browser_clicks_if_changed_strategy_avoided_retry": round(failed_browser_click_s, 2),
            "one_task_call": round((TOOL_MIX["task"]["avg_ms"] or 0) / 1000.0, 2),
            "one_web_search_call": round((TOOL_MIX["web_search"]["avg_ms"] or 0) / 1000.0, 2),
        },
        "break_even_current_overhead": {
            "duplicate_bash_calls_needed": calls_to_break_even((TOOL_MIX["bash"]["avg_ms"] or 0) / 1000.0),
            "duplicate_bash_calls_available": REDUNDANT_CALLS["bash"],
            "task_calls_needed": calls_to_break_even((TOOL_MIX["task"]["avg_ms"] or 0) / 1000.0),
            "web_search_calls_needed": calls_to_break_even((TOOL_MIX["web_search"]["avg_ms"] or 0) / 1000.0),
            "browser_click_retries_needed": calls_to_break_even((TOOL_MIX["playwright-browser_click"]["avg_ms"] or 0) / 1000.0),
            "browser_click_wasted_repeats_available": REDUNDANT_CALLS["playwright-browser_click"],
        },
        "break_even_per_invocation": break_even_targets,
        "bash_intent": BASH_INTENT,
        "redundant_calls": REDUNDANT_CALLS,
    }


def md_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    out = ["| " + " | ".join(label for _, label in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row.get(key, "")
            if isinstance(value, float):
                value = f"{value:.4f}" if abs(value) < 10 else f"{value:.2f}"
            cells.append(str(value))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def render_markdown(results: dict[str, Any]) -> str:
    measurements = results["measurements"]
    impact = results["session_model"]
    harness_sets = results["benchmark_metadata"]["harness_sets"]
    overhead = impact["overhead_seconds_30d"]
    savings = impact["plausible_savings_seconds_30d"]
    be = impact["break_even_current_overhead"]

    component_names = {
        "subprocess_python_plus_pre_tool_import",
        "route_pre_tool_use_not_gated_edit",
        "violates_read_only_policy_check",
        "external_write_decide_source_policy",
        "tool_worth_it_full_gate_source_fixture",
        "unbounded_large_read_large_file",
        "unbounded_large_read_small_file",
    }
    hook_names = {
        "hook_e2e_cheap_tool_allow",
        "hook_e2e_readonly_policy_deny",
        "hook_e2e_fixture_gate_bash",
        "hook_e2e_large_view_fixture_gate",
        "post_failure_retry_fixture_gate",
    }
    component_rows = [m for m in measurements if m["name"] in component_names]
    hook_rows = [m for m in measurements if m["name"] in hook_names]

    verdict = (
        "Mixed. The current matcher keeps fixture-mode overhead small enough that expensive-tool gates "
        "can pay for themselves, but cheap-tool gating is negative and live Jev latency will move the "
        "break-even sharply upward."
    )

    lines: list[str] = []
    lines.append("# Latency benchmark results\n")
    lines.append(f"Generated by `python3 experiments/latency/bench.py` at `{results['generated_at']}`.\n")
    lines.append("## Verdict\n")
    lines.append(f"**{verdict}**\n")
    lines.append(
        "The honest result is not \"gate everything\". Fixture-mode gates are net-positive only when they "
        "stop expensive or failure-prone work: `bash`, `task`, `web_search`, duplicate calls, and browser "
        "retry loops. They are net-negative for cheap tools such as `edit`, `view`, `glob`, and `rg` unless "
        "the gate is a local microsecond prefilter such as `unbounded_large_read()`.\n"
    )
    lines.append(
        "All Jev gate numbers here are **fixture mode**. They exclude real Jev network latency. A live "
        "300-500 ms scorer would be materially worse; the live break-even column below models 400 ms as "
        "a midpoint, not as a measurement.\n"
    )

    lines.append("## Measured overhead components\n")
    lines.append(md_table(component_rows, [
        ("name", "Component"),
        ("median_ms", "median ms"),
        ("p95_ms", "p95 ms"),
        ("iterations", "n"),
        ("notes", "Notes"),
    ]))
    lines.append("### End-to-end hook cost\n")
    lines.append(md_table(hook_rows, [
        ("name", "Hook path"),
        ("median_ms", "median ms"),
        ("p95_ms", "p95 ms"),
        ("iterations", "n"),
        ("notes", "Notes"),
    ]))

    lines.append("## Session-level model\n")
    routing = impact["routing_counts"]
    lines.append(
        "The current `hooks.json` preToolUse matcher is narrower than \"all tools\": it matches expensive "
        "tools and external-write/read-only integrations, not `edit`, `view`, `glob`, `rg`, `sql`, etc. "
        "So the startup tax is paid on matched calls, not literally all 3,970 tool calls in this telemetry. "
        "The all-tools line shows the cost if that matcher were widened.\n"
    )
    lines.append(
        f"`harness.py` currently defines `CHEAP_TOOLS={harness_sets['cheap_tools']}` and "
        f"`EXPENSIVE_TOOLS={harness_sets['expensive_tools']}`. The measured matcher is "
        f"`{routing['pretool_matcher']}`.\n"
    )
    lines.append(md_table([
        {"scenario": "current hooks.json preToolUse", "calls": routing["current_hooks_json_pretool_matched_calls"], "overhead_s": overhead["current_hooks_json_pretool"], "per_session_s": round(overhead["current_hooks_json_pretool"] / TOOL_SESSIONS, 2)},
        {"scenario": "postToolUseFailure retry advice", "calls": routing["post_failure_hook_calls"], "overhead_s": overhead["current_post_tool_use_failure"], "per_session_s": round(overhead["current_post_tool_use_failure"] / TOOL_SESSIONS, 2)},
        {"scenario": "current total", "calls": routing["current_hooks_json_pretool_matched_calls"] + routing["post_failure_hook_calls"], "overhead_s": overhead["current_total"], "per_session_s": overhead["current_total_per_session"]},
        {"scenario": "hypothetical preToolUse on all tools", "calls": TOTAL_TOOL_CALLS + routing["post_failure_hook_calls"], "overhead_s": overhead["hypothetical_if_pretool_hook_matched_all_tools"], "per_session_s": overhead["hypothetical_all_tools_per_session"]},
    ], [
        ("scenario", "Scenario"),
        ("calls", "30d hook calls"),
        ("overhead_s", "overhead seconds"),
        ("per_session_s", "seconds/session"),
    ]))

    lines.append("## Plausible savings from the same telemetry\n")
    lines.append(md_table([
        {"lever": "Prevent duplicate `bash` calls", "evidence": "77 wasted repeats × 9.107 s", "saved_s": savings["duplicate_bash_only"], "caveat": "Cleanest defensible latency win; redundant gate is not wired into current preToolUse state."},
        {"lever": "Prevent known-latency duplicate calls", "evidence": f"{savings['duplicate_known_latency_calls']} repeats with avg latency known", "saved_s": savings["duplicate_known_latency_tools"], "caveat": "Includes `read_bash`, which may include legitimate polling; treat as directional."},
        {"lever": "Replace bash read/search/list with built-ins", "evidence": "831 bash calls doing read/search/list", "saved_s": savings["bash_readish_replaced_by_builtin_upper_bound"], "caveat": "Upper bound. Current hook can identify this but does not rewrite bash to rg/view/glob."},
        {"lever": "Avoid duplicate browser clicks", "evidence": "4 identical repeats × 3.762 s", "saved_s": savings["duplicate_browser_click_only"], "caveat": "postToolUseFailure can advise, not block."},
        {"lever": "Avoid one `task`", "evidence": "task average latency", "saved_s": savings["one_task_call"], "caveat": "One correct block pays most of the 30-day fixture overhead."},
        {"lever": "Avoid one `web_search`", "evidence": "web_search average latency", "saved_s": savings["one_web_search_call"], "caveat": "Useful, but only 10 calls in the window."},
    ], [
        ("lever", "Lever"),
        ("evidence", "Telemetry basis"),
        ("saved_s", "plausible saved seconds"),
        ("caveat", "Caveat"),
    ]))

    lines.append("## Break-even\n")
    lines.append(
        f"With the current matcher and fixture-mode measurements, total modeled hook overhead is "
        f"**{overhead['current_total']} s over 30 days** (**{overhead['current_total_per_session']} s/session**). "
        f"That is paid back by **{be['duplicate_bash_calls_needed']}** prevented duplicate `bash` calls "
        f"out of {be['duplicate_bash_calls_available']} available, or **{be['task_calls_needed']}** avoided `task` calls, "
        f"or **{be['web_search_calls_needed']}** avoided `web_search` calls. Browser-click retry advice alone would need "
        f"**{be['browser_click_retries_needed']}** avoided click retries, but only {be['browser_click_wasted_repeats_available']} "
        "identical browser-click repeats were observed, so it cannot carry the whole system by itself.\n"
    )
    lines.append(md_table(impact["break_even_per_invocation"], [
        ("saved_tool", "Saved tool/action"),
        ("avg_saved_ms", "avg saved ms"),
        ("fixture_gate_must_be_right_pct", "fixture break-even correct %"),
        ("live_400ms_gate_must_be_right_pct", "live 400ms break-even correct %"),
    ]))
    lines.append(
        "Read the table bluntly: fixture-mode gating of `bash`, `web_search`, and `task` only needs to be "
        "right occasionally. Live gating of `web_fetch` needs to be right often. Live gating of `edit` is "
        "mathematically hopeless because the scorer costs more than the tool.\n"
    )

    lines.append("## Assumptions and limitations\n")
    lines.append("- `TYPESAFE_API_KEY` was unset and `JEV_MODE=fixture`; no live Jev network call was made.\n")
    lines.append("- Tool-level counts come from the aggregate cloud queries checked into `telemetry/queries/07-09`; the local baseline JSON contains model/session aggregates but not those rows.\n")
    lines.append("- The model assumes the current `hooks.json` matcher. If preToolUse is installed globally for every tool, use the all-tools scenario.\n")
    lines.append("- `unbounded_large_read()` is described as a local stat path, but the current implementation opens the file and counts until line 601; it is still microsecond-scale in this benchmark.\n")
    lines.append("- Fixture replay uses local JSON and is much faster than a real remote scorer. Live Jev latency must be measured before claiming production wall-clock gains.\n")

    lines.append("## Recommendations outside `experiments/latency/`\n")
    lines.append("- Do not widen the preToolUse matcher to cheap tools; keep cheap tools behind local prefilters only.\n")
    lines.append("- Wire `redundant-tool-call` into real hook state if duplicate-call savings are a goal; the telemetry says duplicate `bash` alone can pay for the fixture overhead.\n")
    lines.append("- Make `context-read-budget` able to block or rewrite `bash` read/search/list calls; today it can detect them but `to_decision()` only rewrites large `view` calls.\n")
    lines.append("- Consider adding pre-call coverage for slow/failure-prone Kusto tools if policy allows; current hooks only advise after Kusto failures.\n")
    return "\n".join(lines).rstrip() + "\n"


def build_results() -> dict[str, Any]:
    baseline = load_baseline()
    measurements, metadata = run_measurements()
    session_model = model_session_impact(measurements, baseline)
    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "command": "env -u TYPESAFE_API_KEY JEV_MODE=fixture python3 experiments/latency/bench.py",
        "environment": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
            "cwd": str(REPO_ROOT),
            "jev_mode": "fixture",
            "typesafe_api_key_present": bool(os.environ.get("TYPESAFE_API_KEY")),
        },
        "benchmark_metadata": metadata,
        "measurements": measurements,
        "session_model": session_model,
    }


def _redact_paths(obj: Any) -> Any:
    """Strip machine-specific absolute paths before publishing.

    This repo is public and `tests/test_repo_hygiene.py` forbids home directories in
    committed artifacts, so results are rewritten to be repo-relative.
    """
    root = str(REPO_ROOT)
    home = str(Path.home())
    if isinstance(obj, dict):
        return {k: _redact_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_paths(v) for v in obj]
    if isinstance(obj, str):
        return obj.replace(root, "<repo>").replace(home, "<home>")
    return obj


def main() -> int:
    results = build_results()
    RESULTS_JSON.write_text(
        json.dumps(_redact_paths(results), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    RESULTS_MD.write_text(render_markdown(results), encoding="utf-8")

    impact = results["session_model"]
    overhead = impact["overhead_seconds_30d"]
    print("Latency benchmark complete (fixture mode, no API key).")
    print(f"Wrote {RESULTS_JSON.relative_to(REPO_ROOT)}")
    print(f"Wrote {RESULTS_MD.relative_to(REPO_ROOT)}")
    print(
        "Headline: current matcher overhead = "
        f"{overhead['current_total']}s/30d ({overhead['current_total_per_session']}s/session); "
        f"all-tool matcher = {overhead['hypothetical_if_pretool_hook_matched_all_tools']}s/30d."
    )
    print(
        "Break-even: "
        f"{impact['break_even_current_overhead']['duplicate_bash_calls_needed']} prevented duplicate bash calls "
        f"out of {impact['break_even_current_overhead']['duplicate_bash_calls_available']} observed repeats."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
