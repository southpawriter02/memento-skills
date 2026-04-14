#!/usr/bin/env python3
"""
test_style_autofix.py — plain-assert tests for ``style_autofix.py``.

Each test is a zero-argument function whose name starts with ``test_``.
A failure raises ``AssertionError``. The harness at the bottom runs all
of them and prints a summary.

Usage::

    python3 test_style_autofix.py

These tests cover every numbered acceptance criterion from the design
spec ``docs/design/style-checker-autofix-script.md``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Make the sibling module importable without a package installation.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import style_autofix as sa  # noqa: E402  (after sys.path mutation)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _run(content: str, rules: set[str] | None = None) -> sa.FixResult:
    """Shortcut for ``run_fixes`` with the argument reordered for brevity."""
    return sa.run_fixes(content, enabled_rules=rules)


# -----------------------------------------------------------------------------
# Rule 3.1 — Sentence case
# -----------------------------------------------------------------------------


def test_rule_3_1_sentence_case_basic() -> None:
    """AC #1: `## Configure The Database` → `## Configure the database`."""
    result = _run("## Configure The Database\n", rules={"3.1"})
    assert "## Configure the database\n" in result.new_content, result.new_content
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "3.1"


def test_rule_3_1_preserves_proper_nouns() -> None:
    """AC #2: proper-noun `Memento-Skills` is preserved."""
    result = _run("## Using Memento-Skills\n", rules={"3.1"})
    # "Using" is the first word so stays capitalized. "Memento-Skills"
    # is in the allowlist; its canonical casing wins.
    assert "## Using Memento-Skills" in result.new_content, result.new_content


def test_rule_3_1_preserves_acronyms() -> None:
    """AC #3: all-caps acronyms like `API` are preserved."""
    result = _run("## API Documentation\n", rules={"3.1"})
    assert "## API documentation" in result.new_content, result.new_content


def test_rule_3_1_preserves_acronym_in_hyphenated_compound() -> None:
    """Hyphenated compounds with an acronym prefix preserve the acronym.

    ``## AST-based transforms`` stays as ``## AST-based transforms``.
    """
    src = "## AST-based transforms\n"
    result = _run(src, rules={"3.1"})
    assert result.new_content == src
    assert result.findings == []


def test_rule_3_1_preserves_single_letter_marker() -> None:
    """Single uppercase letter after another word is treated as a marker.

    ``### Alternative A: something`` should keep ``A`` capitalized.
    """
    src = "### Alternative A: new idea\n"
    result = _run(src, rules={"3.1"})
    # Heading text becomes "Alternative A: new idea" — A preserved, other
    # words lowercased where applicable (they already are).
    assert "Alternative A:" in result.new_content, result.new_content


def test_rule_3_1_preserves_technical_identifier() -> None:
    """Tokens containing ``.`` or ``/`` are passed through untouched."""
    src = "## Edit SKILL.md now\n"
    result = _run(src, rules={"3.1"})
    assert "SKILL.md" in result.new_content, result.new_content


def test_rule_3_1_hyphenated_compound_fully_lowercased() -> None:
    """Hyphenated compounds after the first word should be fully lowercased.

    ``## Quick Auto-Fix Setup`` should become ``## Quick auto-fix setup``,
    not the awkward ``## Quick auto-Fix setup`` a first-letter-only fix
    would produce.
    """
    result = _run("## Quick Auto-Fix Setup\n", rules={"3.1"})
    assert "## Quick auto-fix setup" in result.new_content, result.new_content


def test_rule_3_1_preserves_inline_code_in_heading() -> None:
    """Inline code spans inside a heading are passed through verbatim."""
    result = _run("## Configure `GOOGLE_API_KEY` Setting\n", rules={"3.1"})
    assert "`GOOGLE_API_KEY`" in result.new_content
    assert "## Configure `GOOGLE_API_KEY` setting" in result.new_content, result.new_content


def test_rule_3_1_treats_numeric_prefix_as_marker() -> None:
    """Numeric prefixes like ``1.`` don't steal "first word" status.

    ``## 1. What we're working with`` must stay unchanged — "What" is
    the actual first word, so it should remain capitalized, and
    "working" / "with" are already lowercase.
    """
    src = "## 1. What we're working with\n"
    result = _run(src, rules={"3.1"})
    assert result.new_content == src
    assert result.findings == []


def test_rule_3_1_numeric_prefix_still_casefixes_rest() -> None:
    """Numeric prefix does not prevent rule 3.1 from lowercasing later tokens."""
    src = "## 1. What We're Working With\n"
    result = _run(src, rules={"3.1"})
    assert "## 1. What we're working with" in result.new_content, result.new_content


def test_rule_3_1_no_change_already_sentence_case() -> None:
    """A heading already in sentence case produces no findings."""
    result = _run("## Configure the database\n", rules={"3.1"})
    assert result.findings == []
    assert result.changed is False


# -----------------------------------------------------------------------------
# Rule 3.2 — Heading levels
# -----------------------------------------------------------------------------


def test_rule_3_2_closes_level_jump() -> None:
    """AC #4: `#, ###, ###` collapses to `#, ##, ##`."""
    src = "# A\n\n### B\n\n### C\n"
    result = _run(src, rules={"3.2"})
    assert "## B" in result.new_content, result.new_content
    assert "## C" in result.new_content, result.new_content
    assert result.findings  # at least one finding


def test_rule_3_2_partial_jump() -> None:
    """AC #5: `#, ##, ##, ####` collapses to `#, ##, ##, ###`."""
    src = "# A\n\n## B\n\n## C\n\n#### D\n"
    result = _run(src, rules={"3.2"})
    # Preserve the earlier levels, only the ## -> #### jump is fixed.
    assert "## B" in result.new_content
    assert "## C" in result.new_content
    assert "### D" in result.new_content, result.new_content


def test_rule_3_2_no_change_when_sequential() -> None:
    """Sequential heading levels produce no findings."""
    src = "# A\n\n## B\n\n### C\n"
    result = _run(src, rules={"3.2"})
    assert result.findings == []
    assert result.changed is False


# -----------------------------------------------------------------------------
# Rule 3.6 — Trailing colons on headings
# -----------------------------------------------------------------------------


def test_rule_3_6_trailing_colon_removed() -> None:
    """AC #6: `### Parameters:` → `### Parameters`."""
    result = _run("### Parameters:\n", rules={"3.6"})
    assert "### Parameters\n" in result.new_content
    assert result.findings[0].rule_id == "3.6"


def test_rule_3_6_internal_colon_preserved() -> None:
    """AC #7: colons mid-heading are not touched."""
    src = "### Step 1: setup\n"
    result = _run(src, rules={"3.6"})
    assert result.new_content == src
    assert result.findings == []


# -----------------------------------------------------------------------------
# Rule 4.1 — Fence language
# -----------------------------------------------------------------------------


def test_rule_4_1_bare_fence_gets_text() -> None:
    """AC #8: A bare fence containing plain text gets tagged `text`."""
    src = "```\nhello world\n```\n"
    result = _run(src, rules={"4.1"})
    assert "```text" in result.new_content, result.new_content


def test_rule_4_1_preserves_existing_tag() -> None:
    """AC #9: An existing language tag is left alone."""
    src = "```python\nprint('hi')\n```\n"
    result = _run(src, rules={"4.1"})
    assert result.new_content == src
    assert result.findings == []


def test_rule_4_1_infers_json() -> None:
    """AC #10: Body with `{` and `"key"` gets tagged `json`."""
    src = '```\n{"key": "value"}\n```\n'
    result = _run(src, rules={"4.1"})
    assert "```json" in result.new_content, result.new_content


def test_rule_4_1_infers_python() -> None:
    """Body with `def` gets tagged `python`."""
    src = "```\ndef foo():\n    return 1\n```\n"
    result = _run(src, rules={"4.1"})
    assert "```python" in result.new_content, result.new_content


def test_rule_4_1_infers_bash() -> None:
    """Body with `$ command` gets tagged `bash`."""
    src = "```\n$ echo hello\n```\n"
    result = _run(src, rules={"4.1"})
    assert "```bash" in result.new_content, result.new_content


# -----------------------------------------------------------------------------
# Rule 6.1 — Blank line before lists
# -----------------------------------------------------------------------------


def test_rule_6_1_insert_blank_before_list() -> None:
    """AC #11: Paragraph directly followed by a list gets a blank inserted."""
    src = "Some intro.\n- first item\n- second item\n"
    result = _run(src, rules={"6.1"})
    assert "Some intro.\n\n- first item" in result.new_content, result.new_content
    assert result.findings[0].rule_id == "6.1"


def test_rule_6_1_list_continuation_not_misread_as_paragraph() -> None:
    """Indented lines inside a list item must not trigger Rule 6.1.

    A list item whose description wraps to an indented second line,
    followed by another list item, is a *list continuation*, not a
    paragraph. No blank line should be inserted.
    """
    src = (
        "- First item\n"
        "  with a continuation line.\n"
        "- Second item\n"
    )
    result = _run(src, rules={"6.1"})
    assert result.new_content == src, result.new_content
    assert result.findings == []


def test_rule_6_1_idempotent() -> None:
    """AC #12: A list already preceded by a blank line is not touched."""
    src = "Some intro.\n\n- first item\n- second item\n"
    result = _run(src, rules={"6.1"})
    assert result.new_content == src
    assert result.findings == []


# -----------------------------------------------------------------------------
# Rule 7.1 — Descriptive link text (report-only)
# -----------------------------------------------------------------------------


def test_rule_7_1_flags_but_does_not_rewrite() -> None:
    """AC #13: `click here` produces a finding, but no rewrite."""
    src = "See [click here](https://example.com) for details.\n"
    result = _run(src, rules={"7.1"})
    assert result.new_content == src
    assert result.changed is False
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "7.1"
    assert result.findings[0].after is None


def test_rule_7_1_code_span_link_text_is_ok() -> None:
    """Inline code inside link text is treated as self-descriptive."""
    src = "See [`handleClick`](api.md) for the API.\n"
    result = _run(src, rules={"7.1"})
    assert result.findings == []


# -----------------------------------------------------------------------------
# Safety — fenced blocks and MDX front matter
# -----------------------------------------------------------------------------


def test_safety_inside_fence_untouched() -> None:
    """AC #14: Heading-like text inside a fence is not altered."""
    src = "```\n## Not Really A Heading\n```\n"
    # Run all rules; content inside the fence must survive.
    result = _run(src)
    assert "## Not Really A Heading" in result.new_content, result.new_content


def test_safety_mdx_front_matter_preserved() -> None:
    """AC #15: MDX front-matter block is passed through unchanged."""
    src = (
        "---\n"
        "title: My Page\n"
        "description: This Is Not Sentence Case\n"
        "---\n"
        "\n"
        "# My page\n"
    )
    result = _run(src)
    # The description line (inside front matter) must be byte-for-byte intact.
    assert "description: This Is Not Sentence Case" in result.new_content, result.new_content


# -----------------------------------------------------------------------------
# Idempotence
# -----------------------------------------------------------------------------


def test_idempotence_all_rules() -> None:
    """AC #16: Running fixes twice produces the same output the second time."""
    src = (
        "# Top-Level Heading\n"
        "\n"
        "Some intro:\n"
        "- one\n"
        "- two\n"
        "\n"
        "### Heading:\n"
        "\n"
        "```\nhello world\n```\n"
    )
    first = _run(src)
    second = _run(first.new_content)
    assert second.new_content == first.new_content, (
        "second pass changed the output — rule(s) are not idempotent\n"
        f"after pass 1:\n{first.new_content!r}\n"
        f"after pass 2:\n{second.new_content!r}\n"
    )
    assert second.findings == [] or not second.changed


# -----------------------------------------------------------------------------
# CLI — --check, --dry-run, directory recursion
# -----------------------------------------------------------------------------


SCRIPT_PATH = HERE / "style_autofix.py"


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke the script as a subprocess and return the completed process."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_cli_check_exit_codes() -> None:
    """AC #17: `--check` returns 0 on clean, 1 on dirty."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        clean = tdp / "clean.md"
        clean.write_text("# Clean heading\n", encoding="utf-8")
        dirty = tdp / "dirty.md"
        dirty.write_text("## Configure The Database\n", encoding="utf-8")

        r_clean = _run_cli("--check", str(clean))
        assert r_clean.returncode == 0, r_clean.stdout + r_clean.stderr

        r_dirty = _run_cli("--check", str(dirty))
        assert r_dirty.returncode == 1, r_dirty.stdout + r_dirty.stderr
        # File was not modified in check mode.
        assert dirty.read_text(encoding="utf-8") == "## Configure The Database\n"


def test_cli_dry_run_no_write() -> None:
    """AC #18: `--dry-run` does not modify the file on disk."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        f = tdp / "dirty.md"
        original = "## Configure The Database\n"
        f.write_text(original, encoding="utf-8")
        r = _run_cli("--dry-run", str(f))
        assert r.returncode == 0
        assert f.read_text(encoding="utf-8") == original
        # A diff should have been emitted.
        assert "Configure the database" in r.stdout


def test_cli_directory_recursion() -> None:
    """AC #19: Directory input recurses and processes every .md / .mdx file."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "a.md").write_text("## A Heading\n", encoding="utf-8")
        sub = tdp / "sub"
        sub.mkdir()
        (sub / "b.mdx").write_text("## B Heading\n", encoding="utf-8")
        r = _run_cli(str(tdp))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "## A heading" in (tdp / "a.md").read_text(encoding="utf-8")
        assert "## B heading" in (sub / "b.mdx").read_text(encoding="utf-8")


def test_cli_writes_fixes_by_default() -> None:
    """Default mode (no flags) writes the fixed content back to disk."""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "dirty.md"
        f.write_text("## Heading:\n", encoding="utf-8")
        r = _run_cli(str(f))
        assert r.returncode == 0
        assert f.read_text(encoding="utf-8") == "## Heading\n"


def test_cli_json_output() -> None:
    """`--json` emits a valid JSON findings list on stdout."""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "dirty.md"
        f.write_text("## Heading:\n", encoding="utf-8")
        r = _run_cli("--check", "--json", str(f))
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert payload["files"] == 1
        assert any(fn["rule_id"] == "3.6" for fn in payload["findings"])


# -----------------------------------------------------------------------------
# Harness
# -----------------------------------------------------------------------------


def _collect_tests() -> list[tuple[str, callable]]:  # type: ignore[valid-type]
    """Return ``[(name, fn), ...]`` for every test_* function in this module."""
    g = globals()
    tests = [(name, g[name]) for name in sorted(g) if name.startswith("test_") and callable(g[name])]
    return tests


def main() -> int:
    tests = _collect_tests()
    passed = 0
    failed: list[tuple[str, BaseException]] = []
    for name, fn in tests:
        try:
            fn()
        except BaseException as exc:  # pragma: no cover — diagnostic path
            failed.append((name, exc))
            print(f"FAIL  {name}: {exc}")
        else:
            passed += 1
            print(f"ok    {name}")
    total = len(tests)
    print()
    print(f"{passed} passed, {len(failed)} failed ({total} total)")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
