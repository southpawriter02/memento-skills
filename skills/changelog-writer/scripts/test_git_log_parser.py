#!/usr/bin/env python3
"""test_git_log_parser.py — Unit tests for the changelog-writer git_log_parser.

These tests lock in the behavior of `parse_conventional` (the conventional-
commit subject parser) and the newer `scopes_used` summary field and
`--filter-scope` / `filter_scopes=` filtering behavior introduced in
MS-DES-0008.

We use plain `unittest` (stdlib) — the project's house rule is "no third-party
test dependencies unless unavoidable". Run via:

    python -m unittest skills.changelog-writer.scripts.test_git_log_parser

Or directly:

    python skills/changelog-writer/scripts/test_git_log_parser.py

Coverage map (MS-DES-0008 AC #9 — "at least 14 new tests"):

    parse_conventional edge cases .......................... 10 tests
        - bare type, no scope, no breaking
        - type with scope
        - type with breaking marker (no scope)
        - type with scope AND breaking marker
        - uppercase type
        - scope containing a hyphen
        - scope containing a slash
        - trailing whitespace on subject
        - uncategorized subject (doesn't match regex)
        - "BREAKING CHANGE" token in body promoting breaking=True

    scopes_used aggregation ................................  2 tests
    --filter-scope CLI / filter_scopes= kwarg ..............  2 tests

Total: 14 tests. We exercise `parse_git_log` by monkey-patching the few
functions that shell out to `git` so the tests don't require a real git repo.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

# Make the sibling module importable regardless of where unittest is invoked
# from. We insert the script directory at the head of sys.path so that
# `import git_log_parser` resolves to the sibling .py file.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import git_log_parser  # noqa: E402  (import after sys.path mutation)
from git_log_parser import parse_conventional, parse_git_log  # noqa: E402


# ---------------------------------------------------------------------------
# parse_conventional — edge-case coverage (AC #1-#4 plus extra corners)
# ---------------------------------------------------------------------------


class TestParseConventionalBareType(unittest.TestCase):
    """Bare conventional prefix: type only, no scope, no breaking marker."""

    def test_fix_no_scope_no_breaking(self):
        """AC #2: `fix: typo` → type=fix, scope=None, breaking=False."""
        result = parse_conventional("fix: typo")
        self.assertEqual(result, {
            "type": "fix",
            "scope": None,
            "breaking": False,
            "description": "typo",
        })


class TestParseConventionalWithScope(unittest.TestCase):
    """Conventional prefix with a parenthesized scope."""

    def test_feat_with_scope(self):
        """AC #1: `feat(auth): add JWT` → scope captured."""
        result = parse_conventional("feat(auth): add JWT")
        self.assertEqual(result, {
            "type": "feat",
            "scope": "auth",
            "breaking": False,
            "description": "add JWT",
        })


class TestParseConventionalBreakingNoScope(unittest.TestCase):
    """Breaking marker `!` without a scope parenthetical."""

    def test_feat_breaking_no_scope(self):
        """`feat!: drop legacy` → breaking=True, scope=None."""
        result = parse_conventional("feat!: drop legacy API")
        self.assertEqual(result["type"], "feat")
        self.assertIsNone(result["scope"])
        self.assertTrue(result["breaking"])
        self.assertEqual(result["description"], "drop legacy API")


class TestParseConventionalScopeAndBreaking(unittest.TestCase):
    """Both parenthesized scope AND the `!` breaking marker present."""

    def test_feat_api_breaking(self):
        """AC #3: `feat(api)!: breaking API change` → scope=api, breaking=True."""
        result = parse_conventional("feat(api)!: breaking API change")
        self.assertEqual(result["type"], "feat")
        self.assertEqual(result["scope"], "api")
        self.assertTrue(result["breaking"])
        self.assertEqual(result["description"], "breaking API change")


class TestParseConventionalUppercaseType(unittest.TestCase):
    """Uppercase `FEAT:` — regex is case-insensitive; type normalizes to lower."""

    def test_uppercase_type_normalized(self):
        """`FEAT(auth): add login` → type=feat (lowercased)."""
        result = parse_conventional("FEAT(auth): add login")
        self.assertEqual(result["type"], "feat")
        self.assertEqual(result["scope"], "auth")


class TestParseConventionalHyphenatedScope(unittest.TestCase):
    """Scopes frequently include a hyphen (e.g., `style-checker`)."""

    def test_scope_with_hyphen(self):
        """`feat(style-checker): widen` → scope preserved exactly."""
        result = parse_conventional("feat(style-checker): widen PROPER_NOUNS")
        self.assertEqual(result["scope"], "style-checker")


class TestParseConventionalSlashInScope(unittest.TestCase):
    """Some projects use `scope/subscope` — the regex allows anything but `)`."""

    def test_scope_with_slash(self):
        """`feat(auth/jwt): issue refresh` → slash survives."""
        result = parse_conventional("feat(auth/jwt): issue refresh tokens")
        self.assertEqual(result["scope"], "auth/jwt")


class TestParseConventionalTrailingWhitespace(unittest.TestCase):
    """Subject with trailing whitespace should be stripped before matching."""

    def test_trailing_whitespace_stripped(self):
        """`  fix: typo   ` → whitespace removed, matched normally."""
        result = parse_conventional("  fix: typo   ")
        self.assertEqual(result["type"], "fix")
        self.assertEqual(result["description"], "typo")


class TestParseConventionalUncategorized(unittest.TestCase):
    """Subject that doesn't match the conventional-commit pattern."""

    def test_free_form_subject(self):
        """AC #4: `update stuff` → type=uncategorized, full subject as desc."""
        result = parse_conventional("update stuff")
        self.assertEqual(result, {
            "type": "uncategorized",
            "scope": None,
            "breaking": False,
            "description": "update stuff",
        })


class TestParseConventionalBreakingChangeInBody(unittest.TestCase):
    """Non-conventional subject but `BREAKING CHANGE` token present."""

    def test_breaking_change_token_in_subject(self):
        """`BREAKING CHANGE: dropped v1 endpoint` → breaking=True, uncategorized."""
        result = parse_conventional("BREAKING CHANGE: dropped v1 endpoint")
        # The subject doesn't start with a conventional-commit type, so it
        # falls through to the uncategorized branch — but the presence of
        # "BREAKING CHANGE" still flips the breaking flag.
        self.assertEqual(result["type"], "uncategorized")
        self.assertTrue(result["breaking"])


# ---------------------------------------------------------------------------
# scopes_used summary field (MS-DES-0008 AC #5)
# ---------------------------------------------------------------------------
#
# We exercise parse_git_log by monkey-patching the two functions that shell
# out to git (`run_git` and `get_changed_files`) with deterministic fakes.
# This keeps the tests hermetic — no real repository needed.

FIELD_SEP = git_log_parser.FIELD_SEP
RECORD_SEP = git_log_parser.RECORD_SEP


def _fake_log_record(commit_hash, subject, author="Alice <alice@example.com>",
                     date="2026-04-13 12:00:00 -0700", body=""):
    """Build a single git-log record matching LOG_FORMAT + RECORD_SEP."""
    return FIELD_SEP.join([
        commit_hash, commit_hash[:7], author, date, subject, body,
    ]) + RECORD_SEP


def _fake_run_git_factory(subjects_by_hash):
    """Return a replacement for ``run_git`` that produces fake log output.

    Args:
        subjects_by_hash: dict mapping full-hash-string → subject string.
            Record order follows iteration order (Python 3.7+ ordered dict).
    """
    def fake_run_git(args, cwd):
        # We don't care about what args are — we return canned output for
        # `log` and empty output for `diff-tree` (handled separately below).
        if args and args[0] == "log":
            return "\n".join(
                _fake_log_record(h, s) for h, s in subjects_by_hash.items()
            )
        return ""
    return fake_run_git


def _fake_get_changed_files(commit_hash, cwd):
    """Stub for file-stats lookup — returns empty stats."""
    return [], 0, 0


class TestScopesUsedAggregation(unittest.TestCase):
    """MS-DES-0008 AC #5: summary.scopes_used is always present + sorted."""

    def test_scopes_used_deduplicates_and_sorts(self):
        """Mixed scopes → sorted, de-duplicated list."""
        subjects = {
            "h0000000000000000000000000000000000000001": "feat(api): add endpoint",
            "h0000000000000000000000000000000000000002": "fix(auth): token bug",
            "h0000000000000000000000000000000000000003": "feat(api): another one",
            "h0000000000000000000000000000000000000004": "chore: bump deps",
        }
        with mock.patch.object(git_log_parser, "run_git",
                               _fake_run_git_factory(subjects)), \
             mock.patch.object(git_log_parser, "get_changed_files",
                               _fake_get_changed_files):
            result = parse_git_log(repo_path=".")

        # Two unique scopes ("api", "auth"), sorted alphabetically. The
        # chore commit has no scope so it contributes nothing.
        self.assertEqual(result["summary"]["scopes_used"], ["api", "auth"])

    def test_scopes_used_empty_list_when_no_scopes(self):
        """AC #5: scopes_used always present — empty list when no scopes seen."""
        subjects = {
            "h0000000000000000000000000000000000000001": "fix: typo",
            "h0000000000000000000000000000000000000002": "random free-form commit",
        }
        with mock.patch.object(git_log_parser, "run_git",
                               _fake_run_git_factory(subjects)), \
             mock.patch.object(git_log_parser, "get_changed_files",
                               _fake_get_changed_files):
            result = parse_git_log(repo_path=".")

        self.assertIn("scopes_used", result["summary"])
        self.assertEqual(result["summary"]["scopes_used"], [])


# ---------------------------------------------------------------------------
# filter_scopes kwarg (MS-DES-0008 AC #6 & #7)
# ---------------------------------------------------------------------------


class TestFilterScope(unittest.TestCase):
    """--filter-scope (CLI) / filter_scopes= (kwarg): exact-match, case-insensitive."""

    def test_filter_scope_selects_only_matching_commits(self):
        """AC #6: filter reduces commits to those matching a scope (OR-semantics)."""
        subjects = {
            "h0000000000000000000000000000000000000001": "feat(auth): jwt",
            "h0000000000000000000000000000000000000002": "feat(api): endpoint",
            "h0000000000000000000000000000000000000003": "feat(retrieval): index",
            "h0000000000000000000000000000000000000004": "chore: bump",
        }
        with mock.patch.object(git_log_parser, "run_git",
                               _fake_run_git_factory(subjects)), \
             mock.patch.object(git_log_parser, "get_changed_files",
                               _fake_get_changed_files):
            # Mix a lowercase and an uppercase filter value to confirm the
            # case-insensitive comparison documented in the design spec.
            result = parse_git_log(
                repo_path=".",
                filter_scopes=["auth", "API"],
            )

        # Two commits should survive: the auth one and the api one.
        self.assertEqual(result["summary"]["total_commits"], 2)
        kept_scopes = sorted(c["conventional"]["scope"] for c in result["commits"])
        self.assertEqual(kept_scopes, ["api", "auth"])
        # scopes_used must recompute against the filtered list.
        self.assertEqual(result["summary"]["scopes_used"], ["api", "auth"])

    def test_filter_scope_no_matches_returns_empty(self):
        """AC #7: filter with no matches returns empty result, not an error."""
        subjects = {
            "h0000000000000000000000000000000000000001": "feat(auth): jwt",
            "h0000000000000000000000000000000000000002": "chore: bump",
        }
        with mock.patch.object(git_log_parser, "run_git",
                               _fake_run_git_factory(subjects)), \
             mock.patch.object(git_log_parser, "get_changed_files",
                               _fake_get_changed_files):
            result = parse_git_log(
                repo_path=".",
                filter_scopes=["nonexistent"],
            )

        self.assertEqual(result["commits"], [])
        self.assertEqual(result["summary"]["total_commits"], 0)
        self.assertEqual(result["summary"]["scopes_used"], [])
        # The round-trip through json.dumps should succeed — no NaN/None
        # values sneaking through from the empty-list edge cases.
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
