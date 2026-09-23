"""Repository hygiene and gate-library invariants.

These tests guard properties that are easy to break silently and expensive to
notice late:

* A `.gitignore` rule quietly excluding a gate. The broad `**/*secret*` secrets
  rule matched the entire `gates/secret-exposure/` directory, which would have
  shipped a 15-gate library with 14 gates in it.
* A gate drifting from the three question types Jev actually supports.
* An identifying path or UUID reaching an example state file in a public repo.
"""
from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATES_DIR = REPO_ROOT / "gates"

REQUIRED_FILES = ("SPEC.md", "config.json", "gate.py", "example_state.json")
VALID_QUESTION_TYPES = {"noul", "score", "choice"}

# From docs/cool-use-cases.md. Safety gates must never fail open.
EXPECTED_FAIL_CLOSED = {"destructive-action", "secret-exposure", "external-write",
                        "verification-sufficient"}

EXPECTED_SLUGS = {
    "context-read-budget", "destructive-action", "external-write", "model-effort-route",
    "parallel-fanout", "plan-vs-act", "redundant-tool-call", "response-quality",
    "retry-worth-it", "secret-exposure", "skill-selection", "stop-vs-continue",
    "subagent-spawn", "tool-worth-it", "verification-sufficient",
}

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HOME = re.compile(r"(/Users/|/home/|C:\\\\Users\\\\)")


def gate_dirs() -> list[Path]:
    return sorted(d for d in GATES_DIR.iterdir() if d.is_dir() and d.name != "common")


def load_config(gate: Path) -> dict:
    return json.loads((gate / "config.json").read_text(encoding="utf-8"))


class GateLibraryTests(unittest.TestCase):
    def test_all_expected_gates_present(self):
        found = {d.name for d in gate_dirs()}
        self.assertEqual(found, EXPECTED_SLUGS, f"missing: {EXPECTED_SLUGS - found}, extra: {found - EXPECTED_SLUGS}")

    def test_every_gate_has_required_files(self):
        for gate in gate_dirs():
            for name in REQUIRED_FILES:
                with self.subTest(gate=gate.name, file=name):
                    self.assertTrue((gate / name).is_file(), f"{gate.name}/{name} missing")

    def test_config_slug_matches_directory(self):
        for gate in gate_dirs():
            with self.subTest(gate=gate.name):
                self.assertEqual(load_config(gate).get("slug"), gate.name)

    def test_only_supported_question_types(self):
        """Jev answers noul, score and choice. There is no free-text type."""
        for gate in gate_dirs():
            for key, question in (load_config(gate).get("questions") or {}).items():
                with self.subTest(gate=gate.name, question=key):
                    self.assertIn(question.get("type"), VALID_QUESTION_TYPES)

    def test_score_criteria_are_ordered_arrays(self):
        for gate in gate_dirs():
            for key, question in (load_config(gate).get("questions") or {}).items():
                if question.get("type") != "score":
                    continue
                with self.subTest(gate=gate.name, question=key):
                    self.assertIsInstance(question.get("criteria"), list)
                    self.assertGreaterEqual(len(question["criteria"]), 2)

    def test_choice_criteria_are_maps(self):
        for gate in gate_dirs():
            for key, question in (load_config(gate).get("questions") or {}).items():
                if question.get("type") != "choice":
                    continue
                criteria = question.get("criteria")
                with self.subTest(gate=gate.name, question=key):
                    self.assertIsInstance(criteria, dict)
                    # skill-selection is the one gate whose choice map is built
                    # at call time from the state's candidate_skills. It ships
                    # only the always-present `none` option.
                    if gate.name == "skill-selection" and key == "best_skill":
                        self.assertIn("none", criteria)
                        continue
                    self.assertGreaterEqual(len(criteria), 2)

    def test_skill_selection_builds_choices_from_candidates(self):
        """The dynamic map must actually include the shortlist, plus `none`."""
        import importlib.util
        import sys

        sys.path.insert(0, str(GATES_DIR))
        spec = importlib.util.spec_from_file_location(
            "gate_skill_selection", GATES_DIR / "skill-selection" / "gate.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        state = {
            "user_request": "write a changelog",
            "candidate_skills": [
                {"name": "copywriting", "description": "business prose"},
                {"name": "blogger", "description": "personal essays"},
            ],
            "task_domain": "document",
            "skill_context_cost": "small",
        }
        outcome = module.decide(state)
        rendered = json.dumps(outcome)
        self.assertIn("copywriting", rendered)
        self.assertIn("blogger", rendered)

    def test_every_question_has_instructions(self):
        for gate in gate_dirs():
            for key, question in (load_config(gate).get("questions") or {}).items():
                with self.subTest(gate=gate.name, question=key):
                    self.assertTrue((question.get("instructions") or "").strip())

    def test_fail_modes_are_declared_and_valid(self):
        for gate in gate_dirs():
            with self.subTest(gate=gate.name):
                self.assertIn(load_config(gate).get("fail_mode"), {"open", "closed"})

    def test_safety_gates_fail_closed(self):
        """A safety gate that fails open is not a gate."""
        for slug in EXPECTED_FAIL_CLOSED:
            config = load_config(GATES_DIR / slug)
            with self.subTest(gate=slug):
                self.assertEqual(config.get("fail_mode"), "closed")
                self.assertFalse(
                    (config.get("default_on_error") or {}).get("proceed", False),
                    f"{slug} must not proceed on error",
                )


class PublicRepoHygieneTests(unittest.TestCase):
    def committed_gate_files(self) -> list[Path]:
        return [p for gate in gate_dirs() for name in REQUIRED_FILES
                if (p := gate / name).is_file()]

    def test_no_identifying_paths_in_gate_files(self):
        for path in self.committed_gate_files():
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                self.assertIsNone(_HOME.search(text), "absolute home path leaked")

    def test_no_uuids_in_example_states(self):
        for gate in gate_dirs():
            text = (gate / "example_state.json").read_text(encoding="utf-8")
            with self.subTest(gate=gate.name):
                self.assertIsNone(_UUID.search(text))

    def test_gitignore_does_not_exclude_any_gate_source(self):
        """Regression: **/*secret* silently swallowed gates/secret-exposure/."""
        paths = [str(p.relative_to(REPO_ROOT)) for p in self.committed_gate_files()]
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=REPO_ROOT,
            input="\n".join(paths),
            capture_output=True,
            text=True,
            timeout=30,
        )
        ignored = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(ignored, [], f"gate source files are gitignored: {ignored}")

    def test_real_secrets_are_still_ignored(self):
        """The gitignore fix must not have weakened the secrets rules."""
        candidates = [".env", "secrets.json", "my_secret.txt", "api_keys.txt",
                      "telemetry/raw/export.json"]
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=REPO_ROOT,
            input="\n".join(candidates),
            capture_output=True,
            text=True,
            timeout=30,
        )
        ignored = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
        for candidate in candidates:
            with self.subTest(path=candidate):
                self.assertIn(candidate, ignored, f"{candidate} is no longer ignored")


if __name__ == "__main__":
    unittest.main()
