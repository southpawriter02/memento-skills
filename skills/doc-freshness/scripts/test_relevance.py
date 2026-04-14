#!/usr/bin/env python3
"""test_relevance.py — Tests for the doc-freshness relevance filter.

These tests cover the path-overlap matching logic introduced on 2026-04-13.
The design rationale is in ``docs/design/doc-freshness-relevance-filter.md``.

The tests are intentionally dependency-free: plain ``assert`` statements,
runnable with ``python test_relevance.py``. No pytest, no fixtures, no
tooling to install. Each test function is small and self-contained so a
failing assertion points unambiguously at the rule that broke.

To run:

    cd <repo-root>
    python skills/doc-freshness/scripts/test_relevance.py

Exit code 0 means all tests passed. Any failing test prints a traceback and
the script exits non-zero.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow "import doc_freshness_scanner" when this file is run directly from
# anywhere. We prepend the directory this test lives in to sys.path.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from doc_freshness_scanner import (  # noqa: E402  (import after sys.path tweak)
    _normalize_path_reference,
    _path_overlaps,
    extract_path_references,
    find_related_commits,
)


# ---------------------------------------------------------------------------
# extract_path_references — what the doc mentions
# ---------------------------------------------------------------------------

def test_extracts_inline_code_paths():
    """Backtick spans that look like paths should be captured."""
    content = "See `core/skill/gateway.py` for the entry point."
    refs = extract_path_references(content, Path("docs/overview.md"))
    assert "core/skill/gateway.py" in refs, refs


def test_extracts_directory_references():
    """Trailing slash should be preserved — it marks a directory reference."""
    content = "The `skills/` directory holds all skill manifests."
    refs = extract_path_references(content, Path("docs/overview.md"))
    assert "skills/" in refs, refs


def test_extracts_markdown_link_targets():
    """Relative Markdown links resolve against the doc's directory. A doc
    at ``docs/api/overview.md`` that writes ``[...](../../core/skill/x.py)``
    walks up twice (out of ``api/``, out of ``docs/``) to the repo root and
    then into ``core/skill/x.py``."""
    content = "See [the gateway](../../core/skill/gateway.py) for details."
    refs = extract_path_references(content, Path("docs/api/overview.md"))
    assert "core/skill/gateway.py" in refs, refs


def test_ignores_external_urls():
    """http(s) links, mailto, and anchors should NOT be treated as paths."""
    content = (
        "- [Apple docs](https://support.apple.com/guide)\n"
        "- [Contact](mailto:x@example.com)\n"
        "- [Section](#overview)\n"
    )
    refs = extract_path_references(content, Path("docs/overview.md"))
    assert refs == set(), refs


def test_drops_short_references():
    """References shorter than MIN_PATH_LENGTH must be rejected to avoid
    matching short generic strings like ``io`` against arbitrary paths."""
    content = "Here is `a` and `io` but also `core/skill/`."
    refs = extract_path_references(content, Path("docs/overview.md"))
    # `a` and `io` are below threshold — only the real path survives.
    assert "core/skill/" in refs
    assert "a" not in refs and "io" not in refs, refs


# ---------------------------------------------------------------------------
# _path_overlaps — the core matching rule
# ---------------------------------------------------------------------------

def test_overlap_directory_reference():
    """A directory reference covers all files beneath it."""
    assert _path_overlaps("core/skill/", "core/skill/market.py")
    assert _path_overlaps("core/skill/", "core/skill/store/index.py")
    # But not a sibling directory.
    assert not _path_overlaps("core/skill/", "core/agent/loop.py")


def test_overlap_exact_file():
    """An exact file reference matches exactly that path."""
    assert _path_overlaps("core/skill/gateway.py", "core/skill/gateway.py")


def test_overlap_sibling_file():
    """A file reference also matches sibling files in the same directory —
    the common case where a doc names one module in a package but the
    refactor touched a neighbour."""
    assert _path_overlaps("core/skill/gateway.py", "core/skill/market.py")
    # Not a different directory.
    assert not _path_overlaps("core/skill/gateway.py", "core/agent/loop.py")


def test_overlap_refuses_root_level_wildcard():
    """A bare root-level file reference must not match other root-level
    files — otherwise ``README.md`` would match ``bootstrap.py``."""
    assert not _path_overlaps("README.md", "bootstrap.py")


# ---------------------------------------------------------------------------
# find_related_commits — the regression case that motivated the fix
# ---------------------------------------------------------------------------

def test_regression_meta_commit_does_not_flag_unrelated_doc():
    """Reproduction of the 2026-04-13 false positive:

    A design doc about the agent execution flow mentions "skill" and
    "agent" only in prose (no explicit path references to ``skills/``),
    and a meta-commit adds the tech-writing skill suite under ``skills/``.
    The doc must NOT be flagged as having a related code change.
    """
    doc_refs = {"core/agent/", "core/agent/loop.py"}
    commits = [
        {
            "hash": "c41aa41",
            "date": "2026-04-13",
            "subject": "Added new skills relating to tech writing",
            "files": [
                "skills/style-checker/SKILL.md",
                "skills/doc-pipeline/SKILL.md",
                "CHANGELOG.md",
            ],
        }
    ]
    related = find_related_commits(doc_refs, commits)
    assert related == [], f"Expected no matches, got: {related}"


def test_true_positive_direct_reference():
    """A doc that explicitly references a file must flag commits that
    touch that file."""
    doc_refs = {"core/skill/gateway.py"}
    commits = [
        {
            "hash": "abc1234",
            "date": "2026-04-10",
            "subject": "refactor skill gateway internals",
            "files": ["core/skill/gateway.py"],
        }
    ]
    related = find_related_commits(doc_refs, commits)
    assert len(related) == 1
    assert "core/skill/gateway.py" in related[0]["matched_topics"]


def test_true_positive_directory_reference():
    """A doc that references a directory must flag commits that touch any
    file in that directory, even if the doc doesn't name that specific
    file."""
    doc_refs = {"core/skill/"}
    commits = [
        {
            "hash": "def5678",
            "date": "2026-04-11",
            "subject": "add market.py",
            "files": ["core/skill/market.py"],
        }
    ]
    related = find_related_commits(doc_refs, commits)
    assert len(related) == 1
    assert "core/skill/" in related[0]["matched_topics"]


def test_doc_with_no_path_references_never_matches():
    """A doc that mentions no paths at all must always show zero related
    commits — this is the deliberate tradeoff documented in the design
    note. False negatives are preferred over false positives for this
    signal."""
    doc_refs: set[str] = set()
    commits = [
        {
            "hash": "xyz9999",
            "date": "2026-04-12",
            "subject": "update everything",
            "files": ["core/skill/gateway.py", "core/agent/loop.py"],
        }
    ]
    related = find_related_commits(doc_refs, commits)
    assert related == []


# ---------------------------------------------------------------------------
# Path normalization edge cases
# ---------------------------------------------------------------------------

def test_normalize_strips_leading_dotslash():
    """In markdown-link mode, ``./foo/bar.py`` written in a doc at ``docs/``
    should resolve to ``docs/foo/bar.py`` — the explicit ``./`` declares
    "same directory as the doc."
    """
    result = _normalize_path_reference(
        "./foo/bar.py", Path("docs"), resolve_relative_to_doc=True,
    )
    assert result == "docs/foo/bar.py", result


def test_normalize_resolves_parent_relative():
    """A Markdown link target like ``../core/skill/x.py`` written inside
    ``docs/api/overview.md`` should resolve to ``docs/core/skill/x.py``
    — one level up from ``docs/api/`` is ``docs/``, and the link points
    into ``docs/core/skill/x.py``. Reaching the repo root would require
    ``../../``."""
    result = _normalize_path_reference(
        "../core/skill/x.py", Path("docs/api"), resolve_relative_to_doc=True,
    )
    assert result == "docs/core/skill/x.py", result


def test_normalize_inline_code_is_repo_relative():
    """In inline-code mode, ``core/skill/gateway.py`` is repo-relative
    regardless of which doc mentions it. This is the common convention in
    technical docs — authors name files by their repo path, not relative
    to their own doc."""
    result = _normalize_path_reference(
        "core/skill/gateway.py", Path("docs/api"),
        resolve_relative_to_doc=False,
    )
    assert result == "core/skill/gateway.py", result


def test_normalize_rejects_out_of_repo():
    """If ``../../`` walks us above the repo root, reject the reference.
    Using markdown-link mode because that's where `../` resolution happens.
    """
    result = _normalize_path_reference(
        "../../../etc/passwd", Path("docs"), resolve_relative_to_doc=True,
    )
    assert result is None, result


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _collect_tests():
    """Collect every top-level function in this module whose name starts
    with ``test_``. Keeps the runner dead-simple — no decorators, no
    registration step."""
    return [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]


def main():
    tests = _collect_tests()
    failures = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures.append((name, str(exc) or "assertion failed"))
            print(f"FAIL  {name}  — {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"ERROR {name}  — {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")

    print()
    print(f"{len(tests) - len(failures)} passed, {len(failures)} failed "
          f"({len(tests)} total)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
