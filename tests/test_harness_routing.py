"""Harness routing tests.

The read-only cases here exist because of a real bug: matching read verbs as
substrings let ``slack-SendMessageToChannel`` through, since lowercasing it
yields ``sendmessagetochannel``, which contains ``get``. A standing read-only
policy that silently permits sends is worse than no policy, so the whole tool
surface is pinned here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = REPO_ROOT / "harness" / "copilot-jev-gates"
HOOKS_DIR = HARNESS_DIR / "hooks"
sys.path.insert(0, str(HARNESS_DIR))

from harness import (  # noqa: E402
    CHEAP_TOOLS,
    DEFAULT_HOOK_TIMEOUT_S,
    gate_budget_s,
    is_bash_read,
    is_destructive,
    is_emit,
    is_external_write,
    route_pre_tool_use,
    tool_tokens,
    violates_read_only,
)

# Real tool names from the live environment.
MUST_BLOCK = [
    "slack-SendMessageToChannel",
    "cc-828GDeeqlf0t1i29-SendMessageToChat",
    "cc-828GDeeqlf0t1i29-ReplyToChannelMessage",
    "cc-828GDeeqlf0t1i29-CreateChannel",
    "cc-828GDeeqlf0t1i29-UpdateChatMessage",
    "cc-828GDeeqlf0t1i29-DeleteChatMessage",
    "cc-pdqHAftw9cy3d8Vw-SendDraftMessage",
    "cc-pdqHAftw9cy3d8Vw-ForwardMessage",
    "cc-pdqHAftw9cy3d8Vw-ReplyAllToMessage",
    "cc-qoxxvytaDqWyRth7-CreateEvent",
    "cc-qoxxvytaDqWyRth7-CancelEvent",
    "cc-qoxxvytaDqWyRth7-DeclineEvent",
    "workiq-create_entity",
    "workiq-update_entity",
    "workiq-delete_entity",
    "workiq-do_action",
]

MUST_ALLOW = [
    "slack-slack_search_public",
    "slack-slack_read_thread",
    "slack-slack_read_channel",
    "cc-828GDeeqlf0t1i29-ListChannelMessages",
    "cc-828GDeeqlf0t1i29-GetChatMessage",
    "cc-828GDeeqlf0t1i29-SearchTeamsMessages",
    "cc-pdqHAftw9cy3d8Vw-SearchMessages",
    "cc-pdqHAftw9cy3d8Vw-DownloadAttachment",
    "cc-qoxxvytaDqWyRth7-ListEvents",
    "cc-qoxxvytaDqWyRth7-FindMeetingTimes",
    "workiq-search_paths",
    "workiq-ask",
    "workiq-retrieve",
    "workiq-fetch",
    "workiq-get_schema",
]


class ReadOnlyPolicyTests(unittest.TestCase):
    def test_write_shaped_calls_are_blocked(self):
        for name in MUST_BLOCK:
            with self.subTest(tool=name):
                self.assertTrue(violates_read_only(name), f"{name} must be blocked")

    def test_read_shaped_calls_are_allowed(self):
        for name in MUST_ALLOW:
            with self.subTest(tool=name):
                self.assertFalse(violates_read_only(name), f"{name} must not be blocked")

    def test_substring_regression_get_inside_send(self):
        """The original bug, pinned explicitly."""
        self.assertIn("get", "slack-SendMessageToChannel".lower())
        self.assertNotIn("get", tool_tokens("slack-SendMessageToChannel"))
        self.assertTrue(violates_read_only("slack-SendMessageToChannel"))

    def test_unrecognised_verb_on_readonly_channel_is_blocked(self):
        self.assertTrue(violates_read_only("workiq-frobnicate_widget"))

    def test_policy_does_not_apply_to_other_integrations(self):
        for name in ("github-mcp-server-search_code", "create_pull_request", "bash"):
            with self.subTest(tool=name):
                self.assertFalse(violates_read_only(name))


class TokeniserTests(unittest.TestCase):
    def test_camel_case(self):
        self.assertEqual(tool_tokens("SendMessageToChat"), {"send", "message", "to", "chat"})

    def test_snake_and_kebab(self):
        self.assertEqual(tool_tokens("workiq-get_schema"), {"workiq", "get", "schema"})

    def test_mixed_with_opaque_id(self):
        self.assertIn("send", tool_tokens("cc-828GDeeqlf0t1i29-SendDraftMessage"))


class PreFilterTests(unittest.TestCase):
    def test_destructive_patterns(self):
        for cmd in (
            "rm -rf build/",
            "git clean -fd",
            "git reset --hard HEAD~1",
            "git push --force origin main",
            "git branch -D feature",
        ):
            with self.subTest(cmd=cmd):
                self.assertTrue(is_destructive("bash", {"command": cmd}))

    def test_non_destructive_commands(self):
        for cmd in ("git status", "ls -la", "python3 -m pytest", "git log --oneline"):
            with self.subTest(cmd=cmd):
                self.assertFalse(is_destructive("bash", {"command": cmd}))

    def test_destructive_only_applies_to_bash(self):
        self.assertFalse(is_destructive("view", {"command": "rm -rf /"}))

    def test_emit_patterns(self):
        for cmd in ("git commit -m x", "git push origin main", "gh pr create --title x"):
            with self.subTest(cmd=cmd):
                self.assertTrue(is_emit("bash", {"command": cmd}))

    def test_bash_read_patterns(self):
        for cmd in ("grep -r TODO .", "cat README.md", "find . -name '*.py'"):
            with self.subTest(cmd=cmd):
                self.assertTrue(is_bash_read("bash", {"command": cmd}))

    def test_external_write_tools(self):
        for name in ("create_pull_request", "create_issue", "send_session_message"):
            with self.subTest(tool=name):
                self.assertTrue(is_external_write(name))


class RoutingTests(unittest.TestCase):
    def route(self, tool, args=None):
        result = route_pre_tool_use(tool, args or {}, ".")
        return result[0] if result else None

    def test_safety_beats_cost(self):
        """A destructive bash call routes to safety, not to the read budget."""
        self.assertEqual(self.route("bash", {"command": "rm -rf ./cache"}), "destructive-action")

    def test_routes(self):
        cases = [
            ("bash", {"command": "grep -r TODO ."}, "context-read-budget"),
            ("bash", {"command": "git commit -m 'x'"}, "secret-exposure"),
            ("bash", {"command": "npm run build"}, "tool-worth-it"),
            ("task", {"prompt": "do a thing"}, "subagent-spawn"),
            ("run_factory", {"name": "f"}, "subagent-spawn"),
            ("create_pull_request", {"title": "x"}, "external-write"),
            ("web_search", {"query": "x"}, "tool-worth-it"),
        ]
        for tool, args, expected in cases:
            with self.subTest(tool=tool, args=args):
                self.assertEqual(self.route(tool, args), expected)

    def test_cheap_tools_are_not_routed(self):
        for tool in CHEAP_TOOLS:
            with self.subTest(tool=tool):
                self.assertIsNone(self.route(tool, {"path": "a.py"}))


class HookProcessTests(unittest.TestCase):
    """End-to-end: the hook scripts must always exit 0 and print one object.

    Copilot CLI treats a crashed or non-zero-exit preToolUse hook as a deny, so
    an exception here would silently block the user's tool call.
    """

    def run_hook(self, script: str, payload: dict) -> tuple[int, dict]:
        proc = subprocess.run(
            [sys.executable, str(HOOKS_DIR / script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=60,
        )
        lines = [
            line
            for line in proc.stdout.splitlines()
            if line.strip() and '"type": "progress"' not in line
        ]
        parsed = json.loads("".join(lines)) if lines else {}
        return proc.returncode, parsed

    def test_read_only_denied_at_hook_level(self):
        code, out = self.run_hook(
            "pre_tool_use.py",
            {"toolName": "slack-SendMessageToChannel", "toolArgs": {"text": "hi"}, "cwd": "."},
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertIn("read-only", out.get("permissionDecisionReason", ""))

    def test_cheap_tool_allowed(self):
        code, out = self.run_hook(
            "pre_tool_use.py", {"toolName": "edit", "toolArgs": {"path": "a.py"}, "cwd": "."}
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.get("permissionDecision"), "allow")

    def test_malformed_payload_does_not_crash(self):
        proc = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "pre_tool_use.py")],
            input="not json at all",
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["permissionDecision"], "allow")

    def test_empty_payload_does_not_crash(self):
        code, out = self.run_hook("pre_tool_use.py", {})
        self.assertEqual(code, 0)
        self.assertEqual(out.get("permissionDecision"), "allow")

    def test_agent_stop_is_off_by_default(self):
        code, out = self.run_hook("agent_stop.py", {"cwd": ".", "stopReason": "end_turn"})
        self.assertEqual(code, 0)
        self.assertEqual(out, {})

    def test_session_start_emits_context(self):
        code, out = self.run_hook("session_start.py", {"cwd": "."})
        self.assertEqual(code, 0)
        self.assertIn("jev-gates", out.get("additionalContext", ""))


if __name__ == "__main__":
    unittest.main()


class TimeoutBudgetTests(unittest.TestCase):
    """A preToolUse hook timeout is fail-OPEN, even for safety gates.

    The CLI kills a command hook at `timeoutSec` and lets the tool proceed.
    A safety gate therefore cannot rely on being allowed to finish: it has to
    return its own fail-closed decision strictly inside the budget. These
    tests pin the arithmetic that guarantees headroom.
    """

    def setUp(self):
        self._saved = os.environ.get("COPILOT_JEV_HOOK_TIMEOUT_S")
        os.environ.pop("COPILOT_JEV_HOOK_TIMEOUT_S", None)

    def tearDown(self):
        os.environ.pop("COPILOT_JEV_HOOK_TIMEOUT_S", None)
        if self._saved is not None:
            os.environ["COPILOT_JEV_HOOK_TIMEOUT_S"] = self._saved

    def test_budget_leaves_headroom_under_default_hook_timeout(self):
        budget = gate_budget_s()
        self.assertLess(budget, DEFAULT_HOOK_TIMEOUT_S)
        self.assertGreaterEqual(DEFAULT_HOOK_TIMEOUT_S - budget, 2.0,
                                "need slack for import, state building and emit")

    def test_budget_scales_with_configured_timeout(self):
        os.environ["COPILOT_JEV_HOOK_TIMEOUT_S"] = "30"
        self.assertEqual(gate_budget_s(), 18.0)

    def test_malformed_budget_falls_back_safely(self):
        for value in ("garbage", "-5", "0", ""):
            with self.subTest(value=value):
                os.environ["COPILOT_JEV_HOOK_TIMEOUT_S"] = value
                self.assertEqual(gate_budget_s(), DEFAULT_HOOK_TIMEOUT_S * 0.6)

    def test_budget_is_below_every_gate_running_hook_timeout(self):
        """Regression: jev_client defaulted to 60s under a 10s hook timeout.

        Only hooks that actually invoke a gate are constrained. sessionStart
        injects static context and never calls Jev, so its tighter 5s budget
        is deliberate and not a violation.
        """
        config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
        gate_running = {"preToolUse", "postToolUseFailure", "agentStop"}
        checked = 0
        for event, entries in config["hooks"].items():
            if event not in gate_running:
                continue
            for entry in entries:
                timeout = entry.get("timeoutSec")
                if not timeout:
                    continue
                checked += 1
                with self.subTest(event=event, timeoutSec=timeout):
                    self.assertLess(gate_budget_s(), timeout,
                                    "gate could be killed before returning fail-closed")
        self.assertEqual(checked, len(gate_running), "every gate-running hook needs a timeoutSec")

    def test_jev_client_honours_the_budget_env_var(self):
        sys.path.insert(0, str(REPO_ROOT))
        from gates.common import jev_client

        saved = os.environ.get("JEV_TIMEOUT_S")
        try:
            os.environ["JEV_TIMEOUT_S"] = "4.5"
            self.assertEqual(jev_client._timeout_s(), 4.5)
            for bad in ("bad", "0", "-1", ""):
                os.environ["JEV_TIMEOUT_S"] = bad
                self.assertEqual(jev_client._timeout_s(), jev_client.DEFAULT_TIMEOUT_S)
        finally:
            os.environ.pop("JEV_TIMEOUT_S", None)
            if saved is not None:
                os.environ["JEV_TIMEOUT_S"] = saved


class LargeReadRewriteTests(unittest.TestCase):
    """`view` is cheap and ungated, except for unbounded reads of large files.

    Measured input:output is 260.8:1, so context is the dominant cost. The
    pre-filter is a local stat so the common small read stays free, and the
    gate redirects rather than denies -- the model still gets its content.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.big = Path(self.tmp) / "big.py"
        self.big.write_text("# line\n" * 1500, encoding="utf-8")
        self.small = Path(self.tmp) / "small.py"
        self.small.write_text("# line\n" * 20, encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_small_file_is_not_gated(self):
        from harness import unbounded_large_read
        self.assertIsNone(unbounded_large_read("view", {"path": str(self.small)}))

    def test_large_unbounded_read_is_gated(self):
        from harness import unbounded_large_read
        self.assertIsNotNone(unbounded_large_read("view", {"path": str(self.big)}))

    def test_already_ranged_read_is_not_gated(self):
        from harness import unbounded_large_read
        self.assertIsNone(
            unbounded_large_read("view", {"path": str(self.big), "view_range": [1, 50]})
        )

    def test_explicit_force_flag_is_respected(self):
        """An explicit request to read the whole file is the user's call."""
        from harness import unbounded_large_read
        self.assertIsNone(
            unbounded_large_read("view", {"path": str(self.big), "forceReadLargeFiles": True})
        )

    def test_missing_or_bad_paths_never_raise(self):
        from harness import unbounded_large_read
        for args in ({}, {"path": ""}, {"path": "/nonexistent/x"}, {"path": self.tmp}, None, "str"):
            with self.subTest(args=args):
                self.assertIsNone(unbounded_large_read("view", args))

    def test_other_tools_are_untouched(self):
        from harness import unbounded_large_read
        self.assertIsNone(unbounded_large_read("bash", {"path": str(self.big)}))

    def test_rewrite_bounds_the_read_and_preserves_other_args(self):
        from harness import ranged_read_args
        out = ranged_read_args({"path": str(self.big), "other": "keep"})
        self.assertEqual(out["view_range"], [1, 200])
        self.assertEqual(out["other"], "keep")

    def test_rewrite_does_not_mutate_the_original(self):
        from harness import ranged_read_args
        original = {"path": str(self.big)}
        ranged_read_args(original)
        self.assertNotIn("view_range", original)

    def _hook(self, payload: dict) -> dict:
        env = dict(os.environ, JEV_MODE="fixture")
        proc = subprocess.run(
            [sys.executable, "-B", str(HOOKS_DIR / "pre_tool_use.py")],
            input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, "hooks must always exit 0")
        lines = [l for l in proc.stdout.splitlines()
                 if l.strip() and '"type": "progress"' not in l]
        return json.loads("\n".join(lines))

    def test_end_to_end_large_read_is_rewritten_not_denied(self):
        out = self._hook({"toolName": "view", "toolArgs": {"path": str(self.big)}, "cwd": self.tmp})
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertEqual(out["modifiedArgs"]["view_range"], [1, 200])

    def test_end_to_end_small_read_is_untouched(self):
        out = self._hook({"toolName": "view", "toolArgs": {"path": str(self.small)}, "cwd": self.tmp})
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertNotIn("modifiedArgs", out)
