#!/usr/bin/env python3
"""
style_autofix.py — Mechanical style-guide fixer for Markdown / MDX files.

Applies the mechanical (non-judgment) rules from
``skills/style-checker/references/style-guide.md`` to one or more Markdown
or MDX files. Designed to be invoked from CI, pre-commit hooks, and
interactive sessions.

Rules implemented
-----------------

- **Rule 3.1 — Sentence case for headings** (auto-fix).
  Rewrites heading text so only the first word and recognized proper nouns
  / acronyms are capitalized.
- **Rule 3.2 — No skipped heading levels** (auto-fix).
  Walks the heading level sequence and closes any jumps greater than one.
- **Rule 3.6 — No trailing colons on headings** (auto-fix).
  Strips a single trailing ``:`` from heading text.
- **Rule 4.1 — Code fence language tags** (auto-fix).
  Adds a language identifier to bare fences, inferring from the body when
  possible and falling back to ``text``.
- **Rule 6.1 — Blank line before lists** (auto-fix).
  Inserts a blank line between a paragraph and a following list.
- **Rule 7.1 — Descriptive link text** (report-only).
  Flags generic link text like ``[click here]``; does not rewrite.

Usage
-----

    python3 style_autofix.py <path> [<path> ...]

    --check        Do not write. Exit 1 if any rule would fire.
    --dry-run      Do not write. Print a unified diff.
    --rules R1,R2  Enable only these rule IDs (default: all).
    --ignore-rules Disable these rule IDs after --rules is applied.
    --verbose      Print one line per finding.
    --json         Emit findings as JSON on stdout.

Exit codes
----------

- ``0`` — Nothing to fix, or fixes applied (non-check mode).
- ``1`` — ``--check`` mode and at least one violation was found.
- ``2`` — I/O error, unreadable path, or invalid arguments.

See ``docs/design/style-checker-autofix-script.md`` for the design spec.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Iterable

# -----------------------------------------------------------------------------
# Regex patterns
# -----------------------------------------------------------------------------

# ATX heading: 1-6 hashes, a space, heading text, optional trailing hashes.
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.+?)(?P<trail>[ \t]+#+[ \t]*)?$")

# Code fence open: up to 3 leading spaces, 3+ backticks or tildes, optional info string.
FENCE_OPEN_RE = re.compile(r"^(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})(?P<tag>[^\n]*)$")

# Unordered or ordered list item (indented up to 3 spaces).
LIST_ITEM_RE = re.compile(r"^ {0,3}([-*+]|\d+\.)[ \t]+")

# Front matter boundary (YAML-fenced).
FRONT_MATTER_RE = re.compile(r"^---\s*$")

# Generic phrases that trigger Rule 7.1.
_GENERIC_LINK_PHRASES = {
    "here", "click here", "click", "this", "this link", "this page",
    "link", "read more", "more", "learn more", "this document",
    "this article", "see this", "this one",
}

# Markdown inline link: [text](url) — captures text and url.
# Permissive: matches basic links. Excludes image syntax ![alt](url).
LINK_RE = re.compile(r"(?<!\!)\[(?P<text>[^\]\n]+)\]\((?P<url>[^)\n]+)\)")

# -----------------------------------------------------------------------------
# Proper noun / acronym allowlist for Rule 3.1
# -----------------------------------------------------------------------------

# Proper nouns preserved with their canonical casing. Lookup is
# case-insensitive; the canonical spelling wins.
PROPER_NOUNS: dict[str, str] = {
    "memento-skills": "Memento-Skills",
    "claude": "Claude",
    "anthropic": "Anthropic",
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "markdown": "Markdown",
    "mdx": "MDX",
    "git": "Git",
    "github": "GitHub",
    "gitlab": "GitLab",
    "docker": "Docker",
    "linux": "Linux",
    "macos": "macOS",
    "windows": "Windows",
    "cowork": "Cowork",
    "node.js": "Node.js",
    "react": "React",
    "vue": "Vue",
    "angular": "Angular",
    "finder": "Finder",
    "column": "Column",  # For the Finder column-view context
    "docusaurus": "Docusaurus",
    "nextra": "Nextra",
    "astro": "Astro",
    "jsx": "JSX",
    "yaml": "YAML",
    "json": "JSON",
    "csv": "CSV",
    "html": "HTML",
    "css": "CSS",
    "bm25": "BM25",
}

# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A single style-guide issue surfaced by one of the rule functions.

    Attributes
    ----------
    rule_id
        Dotted rule identifier matching the style guide (e.g. ``"3.1"``).
    line
        One-indexed source line number where the issue was detected.
    severity
        Severity label from the style guide: ``"error"``, ``"warning"``,
        or ``"info"``.
    message
        Human-readable explanation of what was flagged.
    before
        Original line text (no trailing newline).
    after
        Rewritten line text, or ``None`` for report-only findings (Rule 7.1).
    """

    rule_id: str
    line: int
    severity: str
    message: str
    before: str
    after: str | None


@dataclass
class FixResult:
    """The result of applying the enabled rules to a single document.

    Attributes
    ----------
    path
        Source file path, or ``None`` when the input was a string.
    findings
        All findings raised by all rule functions, in encounter order.
    new_content
        Post-fix document content. Equal to the input when no rule fired.
    changed
        True iff ``new_content`` differs from the input.
    """

    path: str | None
    findings: list[Finding] = field(default_factory=list)
    new_content: str = ""
    changed: bool = False


# -----------------------------------------------------------------------------
# Line classification helpers
# -----------------------------------------------------------------------------


def _compute_protected_mask(lines: list[str]) -> list[bool]:
    """Return a boolean mask of lines that rules must NOT modify.

    A line is "protected" if it is:

    - Inside a YAML front-matter block (between the first two ``---`` lines,
      when the file begins with ``---``).
    - Inside a fenced code block (between a ``` or ~~~ open fence and its
      matching close fence). The fence *open* and *close* lines themselves
      are NOT protected — Rule 4.1 needs to edit the open fence to add a
      language tag.

    The mask is computed in a single forward pass.
    """
    mask = [False] * len(lines)
    if not lines:
        return mask

    # Detect front matter: must begin with a line that is exactly "---".
    i = 0
    if FRONT_MATTER_RE.match(lines[0]):
        mask[0] = True
        i = 1
        while i < len(lines):
            if FRONT_MATTER_RE.match(lines[i]):
                mask[i] = True
                i += 1
                break
            mask[i] = True
            i += 1

    # Scan for fenced code blocks.
    in_fence = False
    fence_marker_char: str | None = None
    fence_marker_len = 0
    while i < len(lines):
        line = lines[i]
        if not in_fence:
            m = FENCE_OPEN_RE.match(line)
            if m:
                in_fence = True
                marker = m.group("marker")
                fence_marker_char = marker[0]
                fence_marker_len = len(marker)
                # Open fence line NOT marked protected — Rule 4.1 edits it.
        else:
            stripped = line.lstrip(" ")
            # A matching close fence must be the same character, at least as long.
            if (
                stripped
                and stripped[0] == fence_marker_char
                and len(stripped) >= fence_marker_len
                and all(c == fence_marker_char for c in stripped.rstrip())
                and len(stripped.rstrip()) >= fence_marker_len
            ):
                in_fence = False
                fence_marker_char = None
                fence_marker_len = 0
                # Close fence line itself not protected.
            else:
                mask[i] = True
        i += 1

    return mask


def _collect_fence_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Return a list of ``(open_idx, close_idx)`` for every fenced block.

    Indices are 0-based line numbers into ``lines``. An unclosed fence
    yields ``(open_idx, len(lines) - 1)``. Front matter is not considered
    a fence.
    """
    ranges: list[tuple[int, int]] = []
    # Skip front matter if present.
    start_i = 0
    if lines and FRONT_MATTER_RE.match(lines[0]):
        # Advance past the second ---
        start_i = 1
        while start_i < len(lines) and not FRONT_MATTER_RE.match(lines[start_i]):
            start_i += 1
        start_i = min(start_i + 1, len(lines))

    i = start_i
    while i < len(lines):
        m = FENCE_OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        open_idx = i
        marker = m.group("marker")
        fence_char = marker[0]
        fence_len = len(marker)
        j = i + 1
        close_idx = len(lines) - 1
        while j < len(lines):
            stripped = lines[j].lstrip(" ").rstrip()
            if (
                stripped
                and all(c == fence_char for c in stripped)
                and len(stripped) >= fence_len
            ):
                close_idx = j
                break
            j += 1
        ranges.append((open_idx, close_idx))
        i = close_idx + 1
    return ranges


# -----------------------------------------------------------------------------
# Rule 3.1 — Sentence case for headings
# -----------------------------------------------------------------------------


def _is_acronym(token: str) -> bool:
    """A token is treated as an acronym if it has at least 2 letters, all
    uppercase letters are uppercase, and it contains no lowercase letters.

    Numbers and punctuation are allowed (e.g. ``BM25``, ``API/SDK``).
    """
    letters = [c for c in token if c.isalpha()]
    if len(letters) < 2:
        return False
    return all(c.isupper() for c in letters)


def _strip_surrounding(token: str) -> tuple[str, str, str]:
    """Split a token into (leading_punctuation, core, trailing_punctuation).

    Used by Rule 3.1 to avoid mangling punctuation around words.
    """
    leading = ""
    trailing = ""
    core = token
    while core and not (core[0].isalnum() or core[0] == "`"):
        leading += core[0]
        core = core[1:]
    while core and not (core[-1].isalnum() or core[-1] == "`"):
        trailing = core[-1] + trailing
        core = core[:-1]
    return leading, core, trailing


def _is_numeric_marker(token: str) -> bool:
    """True if ``token`` looks like a numbered-list marker such as ``1.``,
    ``2)``, or ``1.1``.

    Numeric markers are treated as list markers, not as words, so the
    first *actual* word after them receives "first word" treatment for
    Rule 3.1.
    """
    if not token:
        return False
    stripped = token.rstrip(".)")
    return bool(stripped) and all(c.isdigit() or c == "." for c in stripped)


def _is_technical_identifier(core: str) -> bool:
    """True if a token looks like a file path, module, or dotted identifier.

    These tokens should be passed through verbatim because lowercasing
    them would break their meaning. Examples: ``SKILL.md``, ``config.json``,
    ``core/skill/gateway.py``, ``api/v1``.

    Heuristic: the token contains a ``.`` or ``/``. This is loose on
    purpose — authors are expected to wrap identifiers in inline code
    when they appear in prose, but preserving them when they don't is
    safer than mangling them.
    """
    return any(c in core for c in "./")


def _transform_hyphenated_core(core: str, is_first_word: bool) -> str:
    """Apply sentence-case rules to a single (possibly hyphenated) token.

    The token is split on hyphens into subparts. For each subpart:

    - All-uppercase subparts (2+ letters) are treated as acronyms and
      preserved (``AST-based`` → ``AST-based``).
    - A single uppercase letter as a standalone subpart is preserved
      when not at the start of the heading (``Alternative A`` keeps
      ``A`` as a label).
    - Otherwise the subpart is lowercased.
    - The very first subpart of the *first word* of a heading has its
      leading character capitalized (``Multi-platform`` stays
      ``Multi-platform``).

    Subparts are rejoined with ``-``.
    """
    parts = core.split("-")
    transformed: list[str] = []
    for i, part in enumerate(parts):
        if not part:
            transformed.append(part)
            continue
        if _is_acronym(part):
            transformed.append(part)
            continue
        if not is_first_word and len(part) == 1 and part.isupper():
            # Single-letter marker like "A" in "Alternative A".
            transformed.append(part)
            continue
        if i == 0 and is_first_word:
            transformed.append(part[0].upper() + part[1:].lower())
        else:
            transformed.append(part.lower())
    return "-".join(transformed)


def _sentence_case_heading(text: str) -> str:
    """Rewrite a heading's text to sentence case.

    First word is capitalized. Subsequent words are lowercased unless
    they are recognized proper nouns (case-insensitive lookup against
    ``PROPER_NOUNS``), all-caps acronyms, technical identifiers (file
    paths, dotted names), or single-letter markers.

    Tokens wrapped in backticks (inline code) are preserved verbatim.
    Numeric list markers (``1.``, ``2)``, ``1.1``) are treated as markers,
    not as words, so the token after them still receives "first word"
    treatment.
    """
    tokens = text.split(" ")
    out: list[str] = []
    first_word_seen = False
    for tok in tokens:
        if _is_numeric_marker(tok):
            out.append(tok)
            continue
        if not tok:
            out.append(tok)
            continue
        # Preserve inline code verbatim.
        if tok.startswith("`") and tok.endswith("`"):
            out.append(tok)
            first_word_seen = True
            continue
        leading, core, trailing = _strip_surrounding(tok)
        if not core:
            out.append(tok)
            continue
        lower_core = core.lower()
        if lower_core in PROPER_NOUNS:
            new_core = PROPER_NOUNS[lower_core]
        elif _is_technical_identifier(core):
            # File paths, dotted identifiers — pass through untouched.
            new_core = core
        elif _is_acronym(core):
            new_core = core
        else:
            new_core = _transform_hyphenated_core(
                core, is_first_word=not first_word_seen
            )
        first_word_seen = True
        out.append(f"{leading}{new_core}{trailing}")
    return " ".join(out)


def fix_rule_3_1_sentence_case(
    lines: list[str], protected: list[bool]
) -> tuple[list[str], list[Finding]]:
    """Apply Rule 3.1 — convert heading text to sentence case."""
    findings: list[Finding] = []
    out = list(lines)
    for i, line in enumerate(out):
        if protected[i]:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        hashes = m.group("hashes")
        text = m.group("text")
        trail = m.group("trail") or ""
        new_text = _sentence_case_heading(text)
        if new_text != text:
            new_line = f"{hashes} {new_text}{trail}"
            findings.append(
                Finding(
                    rule_id="3.1",
                    line=i + 1,
                    severity="error",
                    message="Heading not in sentence case.",
                    before=line,
                    after=new_line,
                )
            )
            out[i] = new_line
    return out, findings


# -----------------------------------------------------------------------------
# Rule 3.2 — Heading levels must be sequential
# -----------------------------------------------------------------------------


def fix_rule_3_2_heading_levels(
    lines: list[str], protected: list[bool]
) -> tuple[list[str], list[Finding]]:
    """Apply Rule 3.2 — close any gap greater than one between heading levels.

    Uses the mapping algorithm documented in the design spec: maintain a
    dict mapping original-level → emitted-level. When entering a shallower
    level, drop deeper entries from the map. A previously-seen deeper
    level gets its prior emitted value (siblings stay siblings). A new
    deeper level gets ``min(original_level, prev_emitted + 1)``.
    """
    findings: list[Finding] = []
    out = list(lines)
    level_map: dict[int, int] = {}
    prev_emitted = 0

    for i, line in enumerate(out):
        if protected[i]:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        hashes = m.group("hashes")
        text = m.group("text")
        trail = m.group("trail") or ""
        original_level = len(hashes)

        # Drop any entries for levels deeper than the current one — those
        # sections have ended.
        level_map = {k: v for k, v in level_map.items() if k <= original_level}

        if original_level in level_map:
            emitted = level_map[original_level]
        else:
            if prev_emitted == 0:
                # First heading in the document — whatever level it's at is
                # the baseline. Rule 3.3 (must start with H1) is a separate
                # rule and is not this function's concern.
                emitted = original_level
            else:
                emitted = min(original_level, prev_emitted + 1)
            level_map[original_level] = emitted

        prev_emitted = emitted
        if emitted != original_level:
            new_hashes = "#" * emitted
            new_line = f"{new_hashes} {text}{trail}"
            findings.append(
                Finding(
                    rule_id="3.2",
                    line=i + 1,
                    severity="error",
                    message=(
                        f"Heading level {original_level} follows a gap; "
                        f"adjusted to {emitted}."
                    ),
                    before=line,
                    after=new_line,
                )
            )
            out[i] = new_line
    return out, findings


# -----------------------------------------------------------------------------
# Rule 3.6 — No trailing colons on headings
# -----------------------------------------------------------------------------


def fix_rule_3_6_trailing_colons(
    lines: list[str], protected: list[bool]
) -> tuple[list[str], list[Finding]]:
    """Apply Rule 3.6 — strip a single trailing ``:`` from heading text."""
    findings: list[Finding] = []
    out = list(lines)
    for i, line in enumerate(out):
        if protected[i]:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        hashes = m.group("hashes")
        text = m.group("text")
        trail = m.group("trail") or ""
        if text.endswith(":") and not text.endswith("::"):
            new_text = text[:-1].rstrip()
            if new_text and new_text != text:
                new_line = f"{hashes} {new_text}{trail}"
                findings.append(
                    Finding(
                        rule_id="3.6",
                        line=i + 1,
                        severity="warning",
                        message="Trailing colon on heading.",
                        before=line,
                        after=new_line,
                    )
                )
                out[i] = new_line
    return out, findings


# -----------------------------------------------------------------------------
# Rule 4.1 — Code fences must have a language tag
# -----------------------------------------------------------------------------


def _infer_fence_language(body_lines: list[str]) -> str:
    """Guess a language identifier for a bare fenced block.

    Heuristic. Looks at up to the first 20 lines of the fence body and
    returns one of a small set of tags, or ``text`` if nothing matches.
    """
    sample = "\n".join(body_lines[:20])
    stripped = sample.lstrip()
    if not stripped:
        return "text"
    # JSON: starts with { or [ and contains a quoted key/value.
    if stripped.startswith(("{", "[")) and '"' in sample:
        return "json"
    # Python: def/class/import/from/print( patterns.
    if re.search(r"^\s*(def |class |import |from \w+ import|print\()", sample, re.MULTILINE):
        return "python"
    # Shell: shebang, or common commands, or $ prompt.
    if (
        stripped.startswith("#!/")
        or re.search(
            r"^\s*(\$ |sudo |apt |apt-get |npm |pip |pip3 |yarn |brew |cd |git |python3? |curl |wget |echo |export )",
            sample,
            re.MULTILINE,
        )
    ):
        return "bash"
    # YAML: key: value at start of line, not JSON-like.
    if re.search(r"^[A-Za-z_][\w\-]*:\s", sample, re.MULTILINE):
        return "yaml"
    return "text"


def fix_rule_4_1_fence_language(
    lines: list[str], protected: list[bool]
) -> tuple[list[str], list[Finding]]:
    """Apply Rule 4.1 — add a language identifier to bare fences.

    Only edits the opening fence line. Inferred from body content with
    ``text`` as the fallback.
    """
    findings: list[Finding] = []
    out = list(lines)
    ranges = _collect_fence_ranges(out)
    for open_idx, close_idx in ranges:
        m = FENCE_OPEN_RE.match(out[open_idx])
        if not m:
            continue
        tag = m.group("tag").strip()
        if tag:
            continue
        body = out[open_idx + 1 : close_idx]
        lang = _infer_fence_language(body)
        indent = m.group("indent")
        marker = m.group("marker")
        new_line = f"{indent}{marker}{lang}"
        findings.append(
            Finding(
                rule_id="4.1",
                line=open_idx + 1,
                severity="error",
                message=f"Bare code fence tagged as `{lang}`.",
                before=out[open_idx],
                after=new_line,
            )
        )
        out[open_idx] = new_line
    return out, findings


# -----------------------------------------------------------------------------
# Rule 6.1 — Blank line before lists
# -----------------------------------------------------------------------------


def fix_rule_6_1_blank_before_list(
    lines: list[str], protected: list[bool]
) -> tuple[list[str], list[Finding]]:
    """Apply Rule 6.1 — insert a blank line before a list that directly
    follows a paragraph.

    Walks the line list forward, inserting when needed. Protects indices
    shift with each insert, so we re-read the ``protected`` mask-equivalent
    on-the-fly via the fence-range computation.
    """
    findings: list[Finding] = []
    out: list[str] = []
    # Rebuild a live "protected" view as we go by tracking fence / front
    # matter state incrementally. We mirror the logic in
    # _compute_protected_mask rather than reuse the precomputed array,
    # because insertions would shift it.
    in_fm = False
    fm_seen_open = False
    in_fence = False
    fence_char: str | None = None
    fence_len = 0

    prev_out_kind: str = "blank"  # categorize the previous *emitted* line
    # "blank" | "list_item" | "list_continuation" | "heading" | "prose"
    # | "fence_open" | "in_fence" | "fence_close" | "front_matter"
    # | "fm_boundary"

    # Track whether we're inside a list so that indented continuation
    # lines (two or more leading spaces) are classified correctly and
    # don't get misread as paragraphs that should have a blank line
    # before the next list item.
    in_list = False

    # We iterate over input lines; prev_out_kind is the category of the
    # last line we've already appended to ``out``.

    for i, line in enumerate(lines):
        # Figure out this line's category and whether it's protected.
        is_fm_boundary = FRONT_MATTER_RE.match(line) is not None
        if not fm_seen_open and i == 0 and is_fm_boundary:
            in_fm = True
            fm_seen_open = True
            kind = "fm_boundary"
        elif in_fm:
            if is_fm_boundary:
                in_fm = False
                kind = "fm_boundary"
            else:
                kind = "front_matter"
        elif in_fence:
            stripped = line.lstrip(" ").rstrip()
            if (
                stripped
                and fence_char is not None
                and all(c == fence_char for c in stripped)
                and len(stripped) >= fence_len
            ):
                in_fence = False
                fence_char = None
                fence_len = 0
                kind = "fence_close"
            else:
                kind = "in_fence"
        else:
            fm = FENCE_OPEN_RE.match(line)
            if fm:
                in_fence = True
                fence_char = fm.group("marker")[0]
                fence_len = len(fm.group("marker"))
                kind = "fence_open"
                in_list = False
            elif line.strip() == "":
                kind = "blank"
                # A blank line does NOT necessarily end a list; loose
                # lists have blank-separated items. Leave in_list alone.
            elif HEADING_RE.match(line):
                kind = "heading"
                in_list = False
            elif LIST_ITEM_RE.match(line):
                kind = "list_item"
                in_list = True
            elif in_list and line.startswith((" ", "\t")):
                # Indented line inside a list: this is a continuation of
                # the current list item (prose paragraph inside the item,
                # nested block, etc.), not a new top-level paragraph.
                kind = "list_continuation"
            else:
                kind = "prose"
                in_list = False

        # Insertion logic: only outside protected regions. Rule 6.1 only
        # fires when a true paragraph is *directly* followed by a list
        # item — not when the apparent "prose" is actually a continuation
        # of the list we're already inside.
        if kind == "list_item" and prev_out_kind == "prose":
            # Insert a blank line before this one.
            out.append("")
            findings.append(
                Finding(
                    rule_id="6.1",
                    line=len(out),  # 1-indexed line number of inserted blank
                    severity="error",
                    message="List must be preceded by a blank line.",
                    before="",
                    after="",
                )
            )
            prev_out_kind = "blank"

        out.append(line)
        prev_out_kind = kind

    return out, findings


# -----------------------------------------------------------------------------
# Rule 7.1 — Descriptive link text (report-only)
# -----------------------------------------------------------------------------


def report_rule_7_1_link_text(
    lines: list[str], protected: list[bool]
) -> tuple[list[str], list[Finding]]:
    """Report (do not rewrite) Rule 7.1 violations — generic link text.

    A link is flagged when its text, lowercased and stripped, matches one
    of the phrases in ``_GENERIC_LINK_PHRASES``. Links whose text contains
    a backtick (inline code) are skipped — an inline code span is
    considered self-descriptive.
    """
    findings: list[Finding] = []
    for i, line in enumerate(lines):
        if protected[i]:
            continue
        for m in LINK_RE.finditer(line):
            text = m.group("text").strip()
            if "`" in text:
                continue
            if text.lower() in _GENERIC_LINK_PHRASES:
                findings.append(
                    Finding(
                        rule_id="7.1",
                        line=i + 1,
                        severity="error",
                        message=(
                            f"Generic link text {text!r}. Rewrite to describe "
                            f"the destination."
                        ),
                        before=line,
                        after=None,  # report-only
                    )
                )
    return lines, findings


# -----------------------------------------------------------------------------
# Rule registry & orchestration
# -----------------------------------------------------------------------------

# Order matters: Rule 3.2 should run before Rule 3.1 so heading level fixes
# don't interact with text transforms. Rule 6.1 runs last because it
# inserts lines, which would invalidate other rules' line indices.
RULE_REGISTRY: list[tuple[str, Callable[..., tuple[list[str], list[Finding]]]]] = [
    ("3.2", fix_rule_3_2_heading_levels),
    ("3.1", fix_rule_3_1_sentence_case),
    ("3.6", fix_rule_3_6_trailing_colons),
    ("4.1", fix_rule_4_1_fence_language),
    ("7.1", report_rule_7_1_link_text),  # no-op on content, just findings
    ("6.1", fix_rule_6_1_blank_before_list),
]


def run_fixes(
    content: str,
    enabled_rules: set[str] | None = None,
) -> FixResult:
    """Apply all enabled rules to ``content``.

    Parameters
    ----------
    content
        Full document text.
    enabled_rules
        Set of rule IDs (e.g. ``{"3.1", "6.1"}``). ``None`` enables all
        rules in the registry.

    Returns
    -------
    FixResult
        With ``new_content`` set to the post-transform text and
        ``findings`` in encounter order.
    """
    # Detect line ending so we can preserve it on output.
    if "\r\n" in content:
        newline = "\r\n"
    else:
        newline = "\n"

    # splitlines() strips line endings; we reattach newline on join.
    lines = content.split(newline)
    # splitlines-style trailing handling: a file ending with a newline will
    # produce a trailing empty string after split, which we keep so rejoin
    # round-trips correctly.

    all_findings: list[Finding] = []
    for rule_id, fn in RULE_REGISTRY:
        if enabled_rules is not None and rule_id not in enabled_rules:
            continue
        # Recompute protected mask after each rule in case line count changed.
        protected = _compute_protected_mask(lines)
        lines, findings = fn(lines, protected)
        all_findings.extend(findings)

    new_content = newline.join(lines)
    return FixResult(
        path=None,
        findings=all_findings,
        new_content=new_content,
        changed=new_content != content,
    )


def process_file(
    path: Path,
    enabled_rules: set[str] | None,
    dry_run: bool,
    check_only: bool,
) -> FixResult:
    """Read ``path``, apply fixes, optionally write back.

    Returns a ``FixResult`` with ``path`` populated. Raises ``OSError``
    subclasses on I/O failure (caller handles exit code 2).
    """
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OSError(f"{path}: not valid UTF-8 ({exc})") from exc

    result = run_fixes(text, enabled_rules)
    result.path = str(path)
    if result.changed and not dry_run and not check_only:
        path.write_text(result.new_content, encoding="utf-8")
    return result


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def _iter_markdown_files(paths: Iterable[Path]) -> Iterable[Path]:
    """Expand a list of paths into concrete ``.md`` / ``.mdx`` files."""
    for p in paths:
        if p.is_dir():
            yield from sorted(p.rglob("*.md"))
            yield from sorted(p.rglob("*.mdx"))
        elif p.suffix in (".md", ".mdx"):
            yield p
        else:
            # Non-markdown file argument is a user error.
            raise OSError(f"{p}: not a .md or .mdx file")


def _parse_rules_arg(arg: str | None) -> set[str] | None:
    """Split a comma-separated rules argument into a set, or ``None``."""
    if arg is None:
        return None
    return {r.strip() for r in arg.split(",") if r.strip()}


def _format_diff(before: str, after: str, path: str) -> str:
    """Produce a unified diff between before and after text."""
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="style_autofix.py",
        description="Apply mechanical style-guide fixes to Markdown / MDX files.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Files or directories to process.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write. Exit 1 if any rule would fire.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write. Print a unified diff of proposed changes.",
    )
    parser.add_argument(
        "--rules",
        type=str,
        default=None,
        help="Comma-separated rule IDs to enable (default: all).",
    )
    parser.add_argument(
        "--ignore-rules",
        type=str,
        default=None,
        help="Comma-separated rule IDs to disable (applied after --rules).",
    )
    parser.add_argument("--verbose", action="store_true", help="Print one line per finding.")
    parser.add_argument("--json", action="store_true", help="Emit findings as JSON on stdout.")
    args = parser.parse_args(argv)

    if args.verbose and args.json:
        parser.error("--verbose and --json are mutually exclusive")

    enabled = _parse_rules_arg(args.rules)
    ignored = _parse_rules_arg(args.ignore_rules) or set()
    if enabled is None:
        enabled = {rid for rid, _ in RULE_REGISTRY}
    enabled -= ignored

    # Expand paths to concrete files.
    try:
        files = list(_iter_markdown_files(args.paths))
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for p in args.paths:
        if not p.exists():
            print(f"error: {p}: not found", file=sys.stderr)
            return 2

    total_findings: list[dict] = []
    total_changed = 0
    total_files = 0
    any_would_fix = False

    for path in files:
        total_files += 1
        try:
            result = process_file(path, enabled, args.dry_run, args.check)
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if result.changed:
            total_changed += 1
            any_would_fix = True
        if result.findings:
            any_would_fix = True
        for f in result.findings:
            total_findings.append({**asdict(f), "path": result.path})
        if args.dry_run and result.changed:
            # Recompute original text for the diff.
            original = path.read_text(encoding="utf-8")
            sys.stdout.write(_format_diff(original, result.new_content, str(path)))
        if args.verbose:
            for f in result.findings:
                print(f"{result.path}:{f.line} rule={f.rule_id} {f.message}")

    if args.json:
        json.dump({"files": total_files, "findings": total_findings}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif not args.verbose:
        # Summary line (always printed unless --json).
        if args.check:
            verdict = "clean" if not any_would_fix else f"{len(total_findings)} findings"
            print(f"checked {total_files} files: {verdict}")
        elif args.dry_run:
            print(f"dry-run: {total_changed} of {total_files} files would change")
        else:
            print(f"processed {total_files} files: {total_changed} modified, {len(total_findings)} findings")

    if args.check and any_would_fix:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
