"""Common runner hard-rule regressions."""
from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATES_DIR = REPO_ROOT / "gates"
SCRATCH_ROOT = REPO_ROOT / ".test-work"

if str(GATES_DIR) not in sys.path:
    sys.path.insert(0, str(GATES_DIR))

from common import runner  # noqa: E402


def _evaluate_allow(answers: dict, config: dict, client_result: dict) -> dict:
    return {
        "action": "allow",
        "proceed": True,
        "reason": "normal evaluation",
        "answer_keys": sorted(answers),
    }


class RunnerHardRuleTests(unittest.TestCase):
    def setUp(self):
        SCRATCH_ROOT.mkdir(exist_ok=True)
        self.work = SCRATCH_ROOT / self._testMethodName
        shutil.rmtree(self.work, ignore_errors=True)
        self.gate_dir = self.work / "sample-gate"
        self.gate_dir.mkdir(parents=True)
        (self.gate_dir / "config.json").write_text(
            json.dumps(
                {
                    "slug": "sample-gate",
                    "name": "Sample Gate",
                    "fail_mode": "open",
                    "default_on_error": {"action": "allow", "proceed": True},
                    "questions": {
                        "safe_enough": {
                            "type": "noul",
                            "instructions": "Return confidence that the action is safe.",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        shutil.rmtree(self.work, ignore_errors=True)
        try:
            SCRATCH_ROOT.rmdir()
        except OSError:
            pass

    def _patch_call_jev(self, replacement):
        original = runner.jev_client.call_jev
        runner.jev_client.call_jev = replacement
        self.addCleanup(lambda: setattr(runner.jev_client, "call_jev", original))

    def test_hard_rule_policy_decision_skips_jev(self):
        calls = []

        def call_jev(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("hard-rule policy path must not call Jev")

        def hard_rule(state: dict, config: dict) -> dict | None:
            if state.get("block_locally"):
                return {"action": "block", "proceed": False, "reason": "local policy"}
            return None

        self._patch_call_jev(call_jev)

        outcome = runner.decide(
            self.gate_dir,
            {"block_locally": True},
            _evaluate_allow,
            hard_rule=hard_rule,
        )

        self.assertEqual(calls, [])
        self.assertEqual(outcome["source"], "policy")
        self.assertTrue(outcome["ok"])
        self.assertIsNone(outcome["http_status"])
        self.assertEqual(outcome["latency_ms"], 0.0)
        self.assertEqual(outcome["answers"], {})
        self.assertEqual(outcome["decision"]["action"], "block")

    def test_hard_rule_can_accept_state_only(self):
        self._patch_call_jev(
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("hard-rule policy path must not call Jev")
            )
        )

        outcome = runner.decide(
            self.gate_dir,
            {"block_locally": True},
            _evaluate_allow,
            hard_rule=lambda state: (
                {"action": "block", "proceed": False, "reason": "state-only policy"}
                if state.get("block_locally")
                else None
            ),
        )

        self.assertEqual(outcome["source"], "policy")
        self.assertEqual(outcome["decision"]["reason"], "state-only policy")

    def test_hard_rule_none_falls_through_to_jev(self):
        calls = []

        def call_jev(state, questions, *, fixture_path=None):
            calls.append({"state": state, "questions": questions, "fixture_path": fixture_path})
            return {
                "ok": True,
                "http_status": 200,
                "latency_ms": 12.3,
                "error": None,
                "model": "jev-test",
                "answers": {"safe_enough": {"noul": 0.99}},
                "usage": {"input_tokens": 1},
                "request_sans_auth": {"model": "jev-test", "state": state, "questions": questions},
                "source": "fixture",
                "headers": {"content-type": "application/json"},
            }

        self._patch_call_jev(call_jev)

        outcome = runner.decide(
            self.gate_dir,
            {"block_locally": False},
            _evaluate_allow,
            hard_rule=lambda state, config: None,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(outcome["source"], "fixture")
        self.assertEqual(outcome["answers"], {"safe_enough": {"noul": 0.99}})
        self.assertEqual(outcome["decision"]["action"], "allow")

    def test_policy_dry_artifact_is_well_formed_without_jev(self):
        self._patch_call_jev(
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("hard-rule policy path must not call Jev")
            )
        )

        outcome = runner.decide(
            self.gate_dir,
            {"block_locally": True},
            _evaluate_allow,
            hard_rule=lambda state, config: {
                "action": "block",
                "proceed": False,
                "reason": "local policy",
            },
            write_dry=True,
            dry_name="dry_policy_test.json",
        )

        dry_path = Path(outcome["dry_path"])
        self.assertTrue(dry_path.is_file())
        payload = json.loads(dry_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["meta"]["slug"], "sample-gate")
        self.assertEqual(payload["meta"]["source"], "policy")
        self.assertIsNone(payload["meta"]["http_status"])
        self.assertEqual(payload["meta"]["latency_ms"], 0.0)
        self.assertEqual(payload["request_sans_auth"]["state"], {"block_locally": True})
        self.assertEqual(payload["request_sans_auth"]["questions"], runner.load_config(self.gate_dir)["questions"])
        self.assertEqual(payload["response"]["model"], None)
        self.assertEqual(payload["response"]["answers"], {})
        self.assertEqual(payload["response"]["usage"], {})
        self.assertEqual(payload["decision"], outcome["decision"])


if __name__ == "__main__":
    unittest.main()
