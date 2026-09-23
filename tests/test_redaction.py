"""Redaction tests.

This repository is public and the telemetry source contains client and customer
work, so the guarantee that nothing identifying reaches a published artifact must
be tested, not merely asserted in a README.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "telemetry"))

from mine_waste import (  # noqa: E402
    ALLOWED_COLUMNS,
    RedactionError,
    check_rows,
    looks_identifying,
)

BANNED_PATTERNS = ("/Users/", "/home/", "session_id", "arguments_json")


class LooksIdentifyingTests(unittest.TestCase):
    def test_rejects_uuid(self):
        self.assertTrue(looks_identifying("1845a3af-93d2-495d-a419-def92f861193"))

    def test_rejects_uuid_embedded_in_longer_string(self):
        self.assertTrue(looks_identifying("session 1845a3af-93d2-495d-a419-def92f861193"))

    def test_rejects_posix_home_paths(self):
        self.assertTrue(looks_identifying("/Users/someone/Projects/client-repo"))
        self.assertTrue(looks_identifying("/home/someone/work"))

    def test_rejects_windows_home_paths(self):
        self.assertTrue(looks_identifying(r"C:\Users\someone\repo"))

    def test_rejects_leading_tilde_and_slash(self):
        self.assertTrue(looks_identifying("~/Projects/secret"))
        self.assertTrue(looks_identifying("/etc/passwd"))

    def test_rejects_overlong_strings(self):
        self.assertTrue(looks_identifying("x" * 65))

    def test_allows_model_and_tool_names(self):
        for safe in (
            "claude-opus-5",
            "gpt-6-astra",
            "kusto-explorer-kusto_query_readonly",
            "playwright-browser_navigate",
            "ba85352d/claude-fable-5",
            "read_file_via_bash",
            "(none)",
        ):
            with self.subTest(safe=safe):
                self.assertFalse(looks_identifying(safe))

    def test_ignores_non_strings(self):
        for value in (1, 1.5, None, True):
            with self.subTest(value=value):
                self.assertFalse(looks_identifying(value))


class CheckRowsTests(unittest.TestCase):
    def test_rejects_column_outside_allowlist(self):
        with self.assertRaises(RedactionError):
            check_rows("q", [{"session_id": "abc", "calls": 1}])

    def test_rejects_identifying_value_in_allowed_column(self):
        with self.assertRaises(RedactionError):
            check_rows("q", [{"model": "/Users/someone/repo", "requests": 1}])

    def test_accepts_legitimate_aggregate_row(self):
        check_rows(
            "q",
            [{"model": "claude-opus-5", "reasoning_effort": "high", "requests": 10, "aiu": 1.5}],
        )

    def test_allowlist_excludes_known_identifiers(self):
        for banned in ("session_id", "cwd", "repository", "branch", "summary",
                       "user_message", "assistant_response", "file_path",
                       "agent_id", "arguments_json", "tool_call_id"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, ALLOWED_COLUMNS)


class PublishedArtifactTests(unittest.TestCase):
    """Whatever is actually committed under telemetry/reports must be clean."""

    @property
    def reports(self) -> list[Path]:
        return sorted((REPO_ROOT / "telemetry" / "reports").glob("baseline-*"))

    def test_reports_exist(self):
        self.assertTrue(self.reports, "no baseline report found to verify")

    def test_no_banned_substrings_in_reports(self):
        for path in self.reports:
            text = path.read_text(encoding="utf-8")
            for pattern in BANNED_PATTERNS:
                with self.subTest(path=path.name, pattern=pattern):
                    self.assertNotIn(pattern, text)

    def test_no_uuids_in_reports(self):
        for path in self.reports:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertFalse(
                    looks_identifying_anywhere(text),
                    f"{path.name} contains a UUID-shaped identifier",
                )

    def test_json_report_columns_are_allowlisted(self):
        for path in self.reports:
            if path.suffix != ".json":
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            for query_name, rows in payload.get("results", {}).items():
                for row in rows:
                    for column in row:
                        with self.subTest(path=path.name, query=query_name, column=column):
                            self.assertIn(column, ALLOWED_COLUMNS)


def looks_identifying_anywhere(text: str) -> bool:
    import re

    return bool(
        re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            text,
            re.I,
        )
    )


if __name__ == "__main__":
    unittest.main()
