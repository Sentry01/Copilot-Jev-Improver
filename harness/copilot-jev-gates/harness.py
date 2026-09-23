"""Routing and state construction for the Copilot CLI gate harness.

The harness sits between Copilot CLI's hook events and the gate library. Its job
is to decide *which* gate applies to a given hook payload, build that gate's
state from the payload, and translate the gate's decision back into the JSON
contract Copilot CLI expects on stdout.

Two properties matter more than anything else here.

**It must be fast.** Hooks run synchronously and block the agent. A Jev call is
300-500 ms, which is cheap next to a 9-second bash call and ruinous next to a
256 ms edit. Every route therefore has a deterministic pre-filter that decides
whether the gate is worth running *before* any network call happens.

**It must not crash.** Copilot CLI treats a crashed or non-zero-exit
``preToolUse`` command hook as a *deny*. An unhandled exception here would block
the user's tool call with no explanation. Every entry point therefore catches
everything and emits an explicit decision.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

HARNESS_DIR = Path(__file__).resolve().parent
DEFAULT_GATES_ROOT = HARNESS_DIR.parent.parent / "gates"


def gates_root() -> Path:
    override = os.environ.get("COPILOT_JEV_GATES_ROOT")
    return Path(override).expanduser().resolve() if override else DEFAULT_GATES_ROOT


# --------------------------------------------------------------------------
# Deterministic pre-filters
#
# These run before any gate and decide whether a gate is worth its latency.
# They are intentionally regex-and-substring crude: a pre-filter that is itself
# expensive defeats the purpose.
# --------------------------------------------------------------------------

# Tools cheap enough that gating them is a net loss. From the measured latency
# profile: edit 256 ms, glob 629 ms, view 908 ms.
CHEAP_TOOLS = frozenset({"edit", "create", "view", "glob", "grep", "str_replace"})

# Tools expensive or unreliable enough to be worth a gate. bash averages 9.1 s,
# web_search 39 s, task 174 s.
EXPENSIVE_TOOLS = frozenset({"bash", "task", "run_factory", "web_fetch", "web_search"})

DESTRUCTIVE_PATTERNS = (
    r"\brm\s+-[a-zA-Z]*[rf]",
    r"\bgit\s+clean\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+checkout\s+--\s",
    r"\bgit\s+restore\b",
    r"\bgit\s+push\b.*(--force|-f)\b",
    r"\bgit\s+branch\s+-D\b",
    r"\bgit\s+filter-branch\b",
    r"\btruncate\b",
    r"\bdrop\s+(table|database)\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
)
_DESTRUCTIVE = re.compile("|".join(DESTRUCTIVE_PATTERNS), re.IGNORECASE)

# Commands where a credential could become durable or leave the machine.
EMIT_PATTERNS = (
    r"\bgit\s+commit\b",
    r"\bgit\s+push\b",
    r"\bgh\s+(pr|issue|release|gist)\s+(create|edit|comment)\b",
    r"\bcurl\b.*-d\b",
)
_EMIT = re.compile("|".join(EMIT_PATTERNS), re.IGNORECASE)

# bash doing a purpose-built tool's job. 40.3% of measured bash calls.
READ_PATTERNS = (
    r"\b(grep|rg|ack|ag)\b",
    r"\b(cat|head|tail|less|more)\b",
    r"\b(find|ls|tree)\b",
)
_READ = re.compile("|".join(READ_PATTERNS), re.IGNORECASE)

# Tools that reach another person. Never inferred from the command text.
EXTERNAL_WRITE_TOOLS = frozenset(
    {
        "create_pull_request",
        "update_pull_request",
        "create_issue",
        "add_pr_review_comment",
        "reply_to_comment",
        "reply_and_resolve_review_thread",
        "send_session_message",
        "create_issue_artifact",
    }
)
EXTERNAL_WRITE_PREFIXES = (
    "slack-",
    "cc-828GDeeqlf0t1i29-",  # Teams
    "cc-pdqHAftw9cy3d8Vw-",  # Outlook mail
    "cc-qoxxvytaDqWyRth7-",  # Calendar
    "atlassian-",
    "workiq-",
)

# Standing read-only policy. These are hard rules, not thresholds: the gate
# blocks without consulting Jev at all.
READ_ONLY_PREFIXES = (
    "slack-",
    "cc-828GDeeqlf0t1i29-",
    "cc-pdqHAftw9cy3d8Vw-",
    "cc-qoxxvytaDqWyRth7-",
    "workiq-",
)

# Verb matching is done on whole tokens, never substrings. Substring matching is
# actively dangerous here: "SendMessageToChannel" lowercases to
# "sendmessagetochannel", which contains "get", so a naive `"get" in verb` check
# silently waves a Slack send past a read-only policy.
WRITE_VERBS = frozenset(
    {
        "send", "create", "update", "delete", "add", "remove", "reply", "forward",
        "post", "put", "patch", "cancel", "accept", "decline", "tentatively",
        "upload", "do", "transition", "edit", "set", "move", "archive", "invite",
        "join", "leave", "schedule", "draft", "flag", "resolve",
    }
)
READ_VERBS = frozenset(
    {
        "get", "list", "read", "search", "find", "fetch", "retrieve", "describe",
        "query", "ask", "view", "show", "lookup", "download", "schema", "info",
    }
)

_TOKEN_SPLIT = re.compile(r"[_\-.]+|(?<=[a-z0-9])(?=[A-Z])")

SPAWN_TOOLS = frozenset({"task", "run_factory"})


def command_text(tool_args: Any) -> str:
    if isinstance(tool_args, dict):
        for key in ("command", "cmd", "script", "input"):
            value = tool_args.get(key)
            if isinstance(value, str):
                return value
    return ""


def is_destructive(tool_name: str, tool_args: Any) -> bool:
    return tool_name == "bash" and bool(_DESTRUCTIVE.search(command_text(tool_args)))


def is_emit(tool_name: str, tool_args: Any) -> bool:
    return tool_name == "bash" and bool(_EMIT.search(command_text(tool_args)))


def is_bash_read(tool_name: str, tool_args: Any) -> bool:
    return tool_name == "bash" and bool(_READ.search(command_text(tool_args)))


def is_external_write(tool_name: str) -> bool:
    return tool_name in EXTERNAL_WRITE_TOOLS or tool_name.startswith(EXTERNAL_WRITE_PREFIXES)


def tool_tokens(tool_name: str) -> set[str]:
    """Split a tool name into lowercase word tokens.

    Handles snake_case, kebab-case and camelCase, so ``SendMessageToChannel``
    becomes {send, message, to, channel} rather than one opaque blob.
    """
    return {token.lower() for token in _TOKEN_SPLIT.split(tool_name) if token}


def violates_read_only(tool_name: str) -> bool:
    """A write-shaped call against a read-only integration.

    The operator carries a standing read-only rule for Microsoft 365 and Slack.
    A calibrated score must not be able to argue its way past that, so this is
    checked before any gate runs.

    Deliberately conservative: an explicit write verb blocks, and so does a name
    with no recognised read verb at all. On a read-only channel, an unrecognised
    verb should be refused rather than assumed harmless.
    """
    if not tool_name.startswith(READ_ONLY_PREFIXES):
        return False
    tokens = tool_tokens(tool_name)
    if tokens & WRITE_VERBS:
        return True
    return not (tokens & READ_VERBS)


# --------------------------------------------------------------------------
# Gate loading
# --------------------------------------------------------------------------


def load_gate(slug: str) -> Any:
    """Import a gate module by slug without requiring the repo on sys.path."""
    import importlib.util

    root = gates_root()
    gate_path = root / slug / "gate.py"
    if not gate_path.is_file():
        raise FileNotFoundError(f"gate not found: {gate_path}")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location(f"jevgate_{slug.replace('-', '_')}", gate_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load gate: {gate_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_gate(slug: str, state: dict[str, Any]) -> dict[str, Any]:
    return load_gate(slug).decide(state)


# --------------------------------------------------------------------------
# preToolUse routing
#
# Order matters. Safety gates are evaluated before cost gates, because a call
# that is cheap and also destructive must still be stopped.
# --------------------------------------------------------------------------

Route = tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]


def route_pre_tool_use(tool_name: str, tool_args: Any, cwd: str) -> Route | None:
    """Pick the single gate that applies, or None to allow without gating."""
    if is_destructive(tool_name, tool_args):
        return "destructive-action", lambda p: _destructive_state(tool_args, cwd)

    if is_external_write(tool_name):
        return "external-write", lambda p: _external_write_state(tool_name, tool_args)

    if is_emit(tool_name, tool_args):
        return "secret-exposure", lambda p: _secret_state(tool_args)

    if tool_name in SPAWN_TOOLS:
        return "subagent-spawn", lambda p: _spawn_state(tool_name, tool_args)

    if is_bash_read(tool_name, tool_args):
        return "context-read-budget", lambda p: _read_state(tool_args)

    if tool_name in EXPENSIVE_TOOLS:
        return "tool-worth-it", lambda p: _tool_worth_state(tool_name, tool_args)

    return None


def _destructive_state(tool_args: Any, cwd: str) -> dict[str, Any]:
    command = command_text(tool_args)
    return {
        "proposed_command": command,
        "working_tree_state": _working_tree_state(cwd),
        "scope": cwd or "unknown",
        "recoverable": "from_git" if "git" in command.lower() else "no",
        "user_asked_for_it": False,
    }


def _working_tree_state(cwd: str) -> str:
    """Cheap, bounded git probe. Never raises; the harness must not crash."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if out.returncode != 0:
            return "unknown"
        lines = [line for line in out.stdout.splitlines() if line.strip()]
        if not lines:
            return "clean"
        return f"{len(lines)} uncommitted or untracked entries present"
    except Exception:
        return "unknown"


def _external_write_state(tool_name: str, tool_args: Any) -> dict[str, Any]:
    return {
        "action": tool_name,
        "destination": _summarise(tool_args, ("repo_full_name", "channel", "to", "session_id")),
        "content_summary": _summarise(tool_args, ("body", "message", "title", "response")),
        "user_authorised": False,
        "channel_policy": "read_only" if violates_read_only(tool_name) else "write_allowed",
        "reversible": "editable",
    }


def _secret_state(tool_args: Any) -> dict[str, Any]:
    return {
        "proposed_output": command_text(tool_args),
        "destination": "commit",
        "contains_env_reference": "$" in command_text(tool_args),
        "repo_visibility": os.environ.get("COPILOT_JEV_REPO_VISIBILITY", "public"),
        "data_classification": "internal",
    }


def _spawn_state(tool_name: str, tool_args: Any) -> dict[str, Any]:
    args = tool_args if isinstance(tool_args, dict) else {}
    return {
        "task_description": _summarise(tool_args, ("prompt", "description", "name")),
        "context_transfer_size": "large" if len(json.dumps(args)) > 4000 else "medium",
        "parent_can_do_inline": "unknown",
        "parallelism_benefit": "unknown",
        "spawn_kind": "factory_fleet" if tool_name == "run_factory" else "subagent",
        "writes_to_shared_tree": tool_name == "run_factory"
        or args.get("agent_type") in {"general-purpose", "task"},
    }


def _read_state(tool_args: Any) -> dict[str, Any]:
    command = command_text(tool_args)
    return {
        "goal": "shell-issued read or search",
        "target": command,
        "known_size_tier": "unknown",
        "proposed_read": "recursive_grep" if _READ.search(command) else "full_file",
        "already_read": "",
    }


def _tool_worth_state(tool_name: str, tool_args: Any) -> dict[str, Any]:
    return {
        "user_goal": "unknown",
        "already_have": "",
        "proposed_tool": f"{tool_name}: {_summarise(tool_args, ('command', 'query', 'url', 'prompt'))}",
        "est_cost_tier": "high" if tool_name in {"task", "run_factory"} else "medium",
        "est_latency_ms": {"task": 174000, "web_search": 39000, "bash": 9100}.get(tool_name, 5000),
    }


def _summarise(tool_args: Any, keys: tuple[str, ...], limit: int = 400) -> str:
    if not isinstance(tool_args, dict):
        return str(tool_args)[:limit]
    for key in keys:
        value = tool_args.get(key)
        if isinstance(value, str) and value.strip():
            return value[:limit]
    return json.dumps(tool_args)[:limit]


# --------------------------------------------------------------------------
# Hook I/O
# --------------------------------------------------------------------------


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def field(payload: dict[str, Any], camel: str, snake: str, default: Any = None) -> Any:
    """Copilot CLI emits either a camelCase or a VS Code compatible payload."""
    if camel in payload:
        return payload[camel]
    return payload.get(snake, default)


def progress(message: str, temporary: bool = True) -> None:
    """Emit a status line to the CLI timeline. Display-only."""
    sys.stdout.write(json.dumps({"type": "progress", "message": message, "temporary": temporary}) + "\n")
    sys.stdout.flush()


def emit(decision: dict[str, Any]) -> None:
    """Write the single final decision object. Exactly one, or it is ignored."""
    sys.stdout.write(json.dumps(decision))
    sys.stdout.flush()


def allow() -> dict[str, Any]:
    return {"permissionDecision": "allow"}


def deny(reason: str) -> dict[str, Any]:
    return {"permissionDecision": "deny", "permissionDecisionReason": reason}


def ask(reason: str) -> dict[str, Any]:
    return {"permissionDecision": "ask", "permissionDecisionReason": reason}
