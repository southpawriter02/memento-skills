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
# Rule 3.1 — MS-DES-0007 hardening (proper-noun widening + sentence
# boundaries). These tests enforce the new behaviors documented in
# docs/design/rule-3-1-proper-nouns-and-sentence-boundaries.md.
# -----------------------------------------------------------------------------


def test_rule_3_1_preserves_openclaw_proper_noun() -> None:
    """AC #2 (MS-DES-0007): ``OpenClaw`` is preserved verbatim.

    This is the specific gap that triggered the spec — before the
    widening, the heading ``## Memento-Skills vs OpenClaw`` was being
    mangled to ``## Memento-Skills vs openclaw``.
    """

    src = "## Memento-Skills vs OpenClaw\n"
    result = _run(src, rules={"3.1"})
    assert "## Memento-Skills vs OpenClaw" in result.new_content, result.new_content
    assert result.findings == [], result.findings


def test_rule_3_1_canonicalizes_database_proper_nouns() -> None:
    """SQLite / PostgreSQL / MySQL all round-trip to canonical casing."""

    cases = [
        ("## Storing data in Sqlite\n", "## Storing data in SQLite"),
        ("## Using Postgresql for prod\n", "## Using PostgreSQL for prod"),
        ("## Migrating from Mysql\n", "## Migrating from MySQL"),
    ]
    for src, expected in cases:
        result = _run(src, rules={"3.1"})
        assert expected in result.new_content, (src, result.new_content)


def test_rule_3_1_canonicalizes_ios_and_github() -> None:
    """``iOS`` and ``GitHub`` have vendor-mandated internal capitalization."""

    result = _run("## Running on Ios via Github\n", rules={"3.1"})
    assert "## Running on iOS via GitHub" in result.new_content, result.new_content


def test_rule_3_1_canonicalizes_framework_proper_nouns() -> None:
    """Flet / Briefcase / Pydantic / SQLAlchemy all round-trip."""

    cases = [
        ("## Packaging with Flet\n", "## Packaging with Flet"),
        ("## Shipping with Briefcase\n", "## Shipping with Briefcase"),
        ("## Modeling with Pydantic\n", "## Modeling with Pydantic"),
        ("## ORM via Sqlalchemy\n", "## ORM via SQLAlchemy"),
    ]
    for src, expected in cases:
        result = _run(src, rules={"3.1"})
        assert expected in result.new_content, (src, result.new_content)


def test_rule_3_1_preserves_language_and_locale_proper_nouns() -> None:
    """``Latin``, ``American``, ``English``, etc. survive sentence-case.

    Surfaced while style-cleaning the style guide itself: Rule 5.3's
    heading (``Avoid Latin abbreviations``) and Rule 5.5's heading (``Use
    American English spelling``) were getting mangled. Neither ``latin``
    nor ``american`` is a tech acronym, but both are proper nouns as
    language / locale names.
    """

    cases = [
        ("## Avoid Latin abbreviations\n", "## Avoid Latin abbreviations"),
        ("## Use American English spelling\n",
         "## Use American English spelling"),
        ("## Prefer British over Continental\n",
         "## Prefer British over continental"),
        ("## Unicode NFKC normalization\n",
         "## Unicode NFKC normalization"),
    ]
    for src, expected in cases:
        result = _run(src, rules={"3.1"})
        assert expected in result.new_content, (src, result.new_content)


def test_rule_3_1_preserves_html_heading_level_tags() -> None:
    """``H1``...``H6`` are HTML heading-tag acronyms and must survive.

    Surfaced while style-cleaning the style guide itself on 2026-04-14:
    the heading ``### Rule 3.3 — Start with an H1, use only one H1 per
    document`` was getting mangled to ``### ...start with an h1, use only
    one h1 per document``. The ``_is_acronym`` helper only matches
    pure-alpha all-caps runs and skips ``H1`` because of the digit, so an
    explicit ``PROPER_NOUNS`` entry is needed. This test locks in the fix.
    """

    cases = [
        ("### Start with an H1\n", "### Start with an H1"),
        ("### Use H2 for subsections\n", "### Use H2 for subsections"),
        ("### Skipping from H2 to H4 is an error\n",
         "### Skipping from H2 to H4 is an error"),
    ]
    for src, expected in cases:
        result = _run(src, rules={"3.1"})
        assert expected in result.new_content, (src, result.new_content)


def test_rule_3_1_preserves_market_as_proper_noun() -> None:
    """``Market`` is a proper noun for the Skill Market system.

    Surfaced while drafting MS-DES-0010 (remote BM25 fusion): headings like
    ``### Alternative E — wait indefinitely for the Market owner`` were
    getting lowercased to ``... market owner``. Throughout MS-DES-0004,
    MS-DES-0010, and the retrieval-layer codebase, ``Market`` (capitalized)
    refers to the Skill Market service — the same way ``Cowork`` or
    ``Claude`` would. The autofixer now preserves it. This test locks in
    the fix.
    """

    cases = [
        ("### Wait for the Market owner\n", "### Wait for the Market owner"),
        ("## Talking to the Market\n", "## Talking to the Market"),
        ("### Market-side schema changes\n", "### Market-side schema changes"),
    ]
    for src, expected in cases:
        result = _run(src, rules={"3.1"})
        assert expected in result.new_content, (src, result.new_content)


def test_rule_3_1_sentence_boundary_period_flips_case() -> None:
    """AC #3 (MS-DES-0007): a `.` inside a heading starts a new sentence.

    The heading ``## One Repo. One Learning Agent.`` becomes
    ``## One repo. One learning agent.`` — the second ``One`` must stay
    capitalized, because a period terminated the previous sentence.
    """

    result = _run("## One Repo. One Learning Agent.\n", rules={"3.1"})
    assert (
        "## One repo. One learning agent." in result.new_content
    ), result.new_content


def test_rule_3_1_sentence_boundary_question_mark_flips_case() -> None:
    """A `?` also starts a new sentence."""

    result = _run("## Does It Work? Yes. Absolutely.\n", rules={"3.1"})
    assert (
        "## Does it work? Yes. Absolutely." in result.new_content
    ), result.new_content


def test_rule_3_1_sentence_boundary_exclamation_flips_case() -> None:
    """An `!` also starts a new sentence."""

    result = _run("## Hello World! Goodbye World!\n", rules={"3.1"})
    assert (
        "## Hello world! Goodbye world!" in result.new_content
    ), result.new_content


def test_rule_3_1_ellipsis_is_not_a_sentence_terminator() -> None:
    """AC #5 (MS-DES-0007): ``...`` does NOT flip the sentence-start state.

    ``## Wait... really?`` becomes ``## Wait... really?`` — ``really``
    stays lowercase because the ellipsis is multi-character punctuation,
    not a terminator.
    """

    src = "## Wait... really?\n"
    result = _run(src, rules={"3.1"})
    assert result.new_content == src, result.new_content


def test_rule_3_1_version_literal_is_not_a_sentence_terminator() -> None:
    """AC #6 (MS-DES-0007): the trailing period on ``v0.3.0`` doesn't flip.

    The token ``v0.3.0`` is a technical identifier. The existing
    technical-identifier passthrough short-circuits re-casing it. When
    the period at the end is followed by a space and a new sentence,
    the real sentence boundary is the `.` after ``released`` — not the
    period inside the version.
    """

    result = _run("## v0.3.0 released. More coming\n", rules={"3.1"})
    assert (
        "## v0.3.0 released. More coming" in result.new_content
    ), result.new_content


# -----------------------------------------------------------------------
# MS-DES-0012 — abbreviation non-terminator allowlist.
#
# These tests guard the four abbreviations shipped with MS-DES-0012
# (``vs``, ``etc``, ``e.g``, ``i.e``) against the Phase 3 interim
# retrospective's documented failure mode: ``_ends_sentence`` was
# flipping ``at_sentence_start`` on abbreviation terminal periods, which
# caused the *next* token to be incorrectly first-word-capitalized.
# -----------------------------------------------------------------------


def test_rule_3_1_vs_abbreviation_does_not_flip_sentence_start() -> None:
    """AC #1 (MS-DES-0012): ``vs.`` does not flip ``at_sentence_start``.

    Before MS-DES-0012 the heading ``## Lists vs. Tables in Markdown``
    was producing ``## Lists vs. Tables in Markdown`` (no change on
    ``Tables`` because the trailing ``.`` of ``vs.`` flipped the state
    and ``Tables`` was retreated as a first word). The correct output
    lowercases ``Tables`` because ``vs.`` is mid-sentence.
    """

    result = _run("## Lists vs. Tables in Markdown\n", rules={"3.1"})
    assert (
        "## Lists vs. tables in Markdown" in result.new_content
    ), result.new_content


def test_rule_3_1_etc_abbreviation_does_not_flip_sentence_start() -> None:
    """AC #2 (MS-DES-0012): ``etc.`` does not flip sentence start."""

    # ``Dependencies`` starts the heading (correctly capitalized by the
    # first-word rule). After ``etc.`` the following word must stay
    # lowercased because ``etc.`` is an abbreviation, not a terminator.
    result = _run(
        "## Dependencies, Build Tools, etc. Used in CI\n", rules={"3.1"}
    )
    assert (
        "## Dependencies, build tools, etc. used in CI" in result.new_content
    ), result.new_content


def test_rule_3_1_eg_abbreviation_does_not_flip_sentence_start() -> None:
    """AC #3 (MS-DES-0012): ``e.g.`` does not flip sentence start.

    Exercises the ``_is_technical_identifier`` interaction: ``e.g.`` has
    an internal period, so the token-transform path passes it through
    untouched. The MS-DES-0012 fix lives in ``_ends_sentence`` and
    must still suppress the state flip even when the token-transform
    path short-circuits.
    """

    result = _run(
        "## Common Short Forms, e.g. and i.e. Clarified\n", rules={"3.1"}
    )
    # Note: ``i.e.`` is handled by the next test; here we just need
    # ``Clarified`` to stay lowercase despite the ``.`` after ``i.e``.
    assert (
        "## Common short forms, e.g. and i.e. clarified" in result.new_content
    ), result.new_content


def test_rule_3_1_ie_abbreviation_does_not_flip_sentence_start() -> None:
    """AC #4 (MS-DES-0012): ``i.e.`` does not flip sentence start."""

    result = _run("## Clarify i.e. Examples Here\n", rules={"3.1"})
    assert (
        "## Clarify i.e. examples here" in result.new_content
    ), result.new_content


def test_rule_3_1_abbreviation_lookup_is_case_insensitive() -> None:
    """AC #5 (MS-DES-0012): ``Vs.`` / ``VS.`` / ``Etc.`` all suppress flip.

    The allowlist stores lowercase cores; ``_ends_sentence`` lowercases
    the incoming core before comparing. All capitalization variants must
    be treated identically *for the state-flip decision*. What the
    sentence-case transform does with the core itself is governed by
    separate rules (the all-caps-acronym rule preserves ``VS`` as-is,
    for example); MS-DES-0012 only owns the ``at_sentence_start`` flip.
    The key invariant across all cases below is that the *next* token
    must be lowercased (``Bar`` → ``bar``, ``Onwards`` → ``onwards``).
    """

    cases = [
        # ``Vs`` — not all-caps, so the sentence-case rule lowercases
        # the core itself as well as suppressing the state flip.
        ("## Foo Vs. Bar in Markdown\n", "## Foo vs. bar in Markdown"),
        # ``VS`` — all-caps, length ≥ 2 → treated as an acronym by the
        # existing ``_is_acronym`` rule and preserved verbatim. The
        # MS-DES-0012 fix still fires because the state-flip lookup is
        # case-insensitive: the next word ``Bar`` must still be
        # lowercased to ``bar``.
        ("## Foo VS. Bar in Markdown\n", "## Foo VS. bar in Markdown"),
        # ``Etc`` — not all-caps, lowercased to ``etc``; state flip
        # suppressed so ``Onwards`` becomes ``onwards``.
        ("## Alpha, Beta, Etc. Onwards\n", "## Alpha, beta, etc. onwards"),
    ]
    for src, expected in cases:
        result = _run(src, rules={"3.1"})
        assert expected in result.new_content, (src, result.new_content)


def test_rule_3_1_real_terminator_after_abbreviation_still_flips() -> None:
    """AC #6 (MS-DES-0012): a real ``.`` after an abbreviation still flips.

    Regression guard against an over-eager fix: ``## Lists vs. tables.
    Next section.`` must still capitalize ``Next`` because the ``.``
    after ``tables`` is a real sentence boundary. The MS-DES-0012 fix
    only suppresses the flip on the abbreviation itself, not on
    subsequent real terminators.
    """

    src = "## Lists vs. Tables. Next Section.\n"
    result = _run(src, rules={"3.1"})
    assert (
        "## Lists vs. tables. Next section." in result.new_content
    ), result.new_content


def test_rule_3_1_abbreviation_allowlist_entries_are_lowercase() -> None:
    """Tripwire: every MS-DES-0012 allowlist entry must be lowercase.

    ``_ends_sentence`` does a case-insensitive lookup by lowercasing the
    incoming core. If an allowlist entry is accidentally stored with an
    uppercase letter, the lookup becomes a no-op and the bug the entry
    was added to fix silently returns. Catch it at import time.
    """

    for entry in sa._ABBREVIATION_NON_TERMINATORS:
        assert entry == entry.lower(), (
            f"_ABBREVIATION_NON_TERMINATORS entry {entry!r} must be lowercase"
        )


def test_rule_3_1_proper_nouns_registry_has_no_lowercase_values() -> None:
    """Tripwire: every canonical spelling must differ from its lowercase key.

    If someone accidentally adds an entry like ``"python": "python"``,
    the lookup becomes a no-op. Catch that at import time.
    """

    for key, value in sa.PROPER_NOUNS.items():
        assert key == key.lower(), f"PROPER_NOUNS key {key!r} must be lowercase"
        # Vendor spellings like ``iOS`` deliberately start lowercase;
        # requiring a different spelling (rather than a different
        # capitalization on the first character) is the right check.
        assert value != key, f"PROPER_NOUNS entry {key!r} is a no-op (value equals key)"


def test_rule_3_1_proper_nouns_includes_openclaw() -> None:
    """MS-DES-0007 §Proposed solution committed to fixing this specific gap."""

    assert "openclaw" in sa.PROPER_NOUNS
    assert sa.PROPER_NOUNS["openclaw"] == "OpenClaw"


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
