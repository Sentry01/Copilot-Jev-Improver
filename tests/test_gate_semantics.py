"""Gate-logic regressions.

Both bugs found in this repo so far were the same mistake: matching a
substring inside natural-language text and drawing a conclusion the text does
not support.

* The harness classified `slack-SendMessageToChannel` as a read because the
  name contains `get`.
* `redundant-tool-call` read "no intervening mutation" as evidence of a
  mutation, because the phrase contains "mutation" -- which made the gate
  approve exactly the redundant call it exists to stop.

These tests exist so that class of bug has to be reintroduced deliberately.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATES_DIR = REPO_ROOT / "gates"


def load_gate(slug: str):
    if str(GATES_DIR) not in sys.path:
        sys.path.insert(0, str(GATES_DIR))
    spec = importlib.util.spec_from_file_location(
        f"gate_{slug.replace('-', '_')}", GATES_DIR / slug / "gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MutationNegationTests(unittest.TestCase):
    """`redundant-tool-call` must not read a negated phrase as a positive."""

    @classmethod
    def setUpClass(cls):
        cls.gate = load_gate("redundant-tool-call")

    def assert_hint(self, state: dict, expected: bool, label: str):
        with self.subTest(case=label):
            self.assertEqual(self.gate._mutation_hint(state), expected, label)

    def test_negated_phrases_are_not_mutations(self):
        for text, label in [
            ("no intervening mutation", "no + mutation"),
            ("not modified since the last read", "not + modified"),
            ("never changed", "never + changed"),
            ("without any write completed", "without + write completed"),
            ("no edits and no mutation", "two negations"),
            ("zero mutation observed", "zero + mutation"),
        ]:
            self.assert_hint({"prior_calls": text}, False, label)

    def test_real_mutations_are_still_detected(self):
        for text, label in [
            ("file was mutated between calls", "mutated"),
            ("the file was edited after the read", "edited"),
            ("contents changed on disk", "changed"),
            ("write completed before this call", "write completed"),
        ]:
            self.assert_hint({"prior_calls": text}, True, label)

    def test_negation_does_not_leak_across_clauses(self):
        """A later real mutation still counts, even after an earlier negation."""
        for text, label in [
            ("no mutation, then later edited", "comma clause"),
            ("no mutation; file edited", "semicolon clause"),
            ("no mutation and then the file changed", "and clause"),
        ]:
            self.assert_hint({"prior_calls": text}, True, label)

    def test_explicit_structured_signal_wins_over_prose(self):
        """Sniffing prose is a fallback; a real boolean is authoritative."""
        self.assert_hint(
            {"mutation_between_calls": False, "prior_calls": "mutated mutated edited"},
            False, "explicit False beats positive prose",
        )
        self.assert_hint(
            {"mutation_between_calls": True, "prior_calls": "no mutation at all"},
            True, "explicit True beats negated prose",
        )

    def test_absent_and_malformed_state_never_raises(self):
        for state, label in [
            ({}, "empty"),
            ({"prior_calls": None}, "none"),
            ({"prior_calls": 42}, "non-string"),
            ({"prior_calls": ""}, "empty string"),
            ({"mutation_between_calls": "yes"}, "non-bool explicit falls back"),
        ]:
            with self.subTest(case=label):
                self.assertIsInstance(self.gate._mutation_hint(state), bool)


if __name__ == "__main__":
    unittest.main()
