#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_scripts/check_release_versions.py
=======================================

Release-version drift checker for the Memento-Skills repository.

Reads the canonical version from ``pyproject.toml [project].version`` and
verifies that every other place the version appears in the repo matches it.
Intended to be run as part of a release cut (right after the version bump),
and / or wired into CI so pull requests that touch version strings get
checked automatically.

Why this exists
---------------
The `v0.3.0` release cut (see ``docs/.doc-pipeline-log.json`` run #9)
revealed ten canonical version strings scattered across nine files,
including five Python-literal fallbacks that would silently drift if a
future release cut missed one. Inline comments were added to every
fallback naming its lockstep-with-``pyproject.toml`` requirement, but the
comments are advisory — they rely on whoever cuts the next release
remembering to grep for the old version before bumping. This script
turns that convention into an automated check.

Design spec
-----------
See ``docs/design/release-checklist-script.md`` (MS-DES-0005).

Exit codes
----------
``0``
    All call sites match the canonical version.
``1``
    Drift detected — at least one call site disagreed with the canonical.
``2``
    Usage error — canonical source missing, malformed, or registry
    corrupted. The script could not complete the check.

Usage
-----
Human-readable output (the default):

.. code-block:: text

    python3 build_scripts/check_release_versions.py

Machine-readable output, suitable for CI log scraping:

.. code-block:: text

    python3 build_scripts/check_release_versions.py --json

Relative paths in the registry are resolved against the repo root, which is
the parent directory of this script's own directory (``build_scripts/``).
Override with ``--repo-root /some/other/path`` for testing or when running
from a subdirectory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# `tomllib` ships in Python 3.11+ under the standard library. The repo's
# `pyproject.toml` pins `requires-python = ">=3.11"` (see MS-DES-0004), so
# this is a hard requirement, not a soft one. A clean ImportError message
# is still friendlier than a NameError inside `_read_canonical_version`.
try:
    import tomllib
except ImportError as exc:  # pragma: no cover — 3.10-and-older guard
    sys.stderr.write(
        "check_release_versions.py requires Python 3.11+ for tomllib "
        f"(got {sys.version_info.major}.{sys.version_info.minor}): {exc}\n"
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Registry data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallSite:
    """
    One place in the repo where the release version appears.

    Attributes
    ----------
    path:
        Repo-relative path to the file, forward-slashed. Resolved against
        ``--repo-root`` at check time.
    pattern:
        Python regex that matches the line containing the version string.
        Must contain **exactly one** capture group — the captured text is
        compared against the canonical version. If the regex matches
        multiple lines in the file, the **first** match wins (which is why
        every site below either anchors to a unique prefix or lives near
        the top of its file).
    description:
        Short human-readable label for the site, used in the drift report.
    """

    path: str
    pattern: str
    description: str

    def compiled(self) -> re.Pattern[str]:
        """
        Compile the regex with the flags every registry entry needs.

        ``re.MULTILINE`` lets patterns anchor to line starts with ``^``;
        ``re.VERBOSE`` is not used because every pattern here is a
        one-liner.
        """

        return re.compile(self.pattern, re.MULTILINE)


@dataclass
class SiteResult:
    """
    Result of checking one call site.

    ``found`` is ``None`` when the file is missing, the regex does not
    match, or the regex matches but yields an empty capture group. In
    every non-``None`` case, ``line`` and ``context`` carry the
    1-indexed line number and the full matched line (trailing newline
    stripped) for the drift report.
    """

    site: CallSite
    found: str | None
    line: int | None = None
    context: str | None = None
    error: str | None = None

    def in_sync_with(self, canonical: str) -> bool:
        """Return True if this site's version matches the canonical."""

        return self.found is not None and self.found == canonical


# ---------------------------------------------------------------------------
# The registry itself — the single source of truth for "what do I need to
# bump on release?" Adding a new call site is a one-line edit here.
#
# Order matches the table in MS-DES-0005 §"The ten known call sites".
# ---------------------------------------------------------------------------


CALL_SITES: tuple[CallSite, ...] = (
    # Site #1 — the canonical source itself. Listed here so the drift
    # report explicitly confirms it's readable, even though this is what
    # everything else gets compared against. (Self-drift is impossible by
    # definition, but a missing file would still show up.)
    CallSite(
        path="pyproject.toml",
        pattern=r'^version\s*=\s*"([^"]+)"',
        description="Canonical [project].version (pyproject.toml)",
    ),
    # Site #2 — Flet packager's `app.build_version`. Lives under a
    # `[tool.flet]` table further down the file. The regex is anchored to
    # the `app.build_version` prefix to distinguish it from site #1 above
    # and site #3 below.
    CallSite(
        path="pyproject.toml",
        pattern=r'^app\.build_version\s*=\s*"([^"]+)"',
        description="Flet packager app.build_version (pyproject.toml)",
    ),
    # Site #3 — Briefcase's `[tool.briefcase].version`. Same filename as
    # sites #1 and #2; distinguished by the absence of any `app.` prefix
    # and by living in a `[tool.briefcase]` table. Because the regex is
    # identical to site #1's, we rely on first-match-wins *within a file*
    # being broken by the `_read_site` helper, which scans the file once
    # per site and records the Nth match of the pattern.
    #
    # To keep the registry declarative, we use a marker comment on the
    # preceding line — this regex skips ahead until it finds the
    # `[tool.briefcase]` section header, then grabs the next `version =`.
    CallSite(
        path="pyproject.toml",
        pattern=r'\[tool\.briefcase\][^\[]*?version\s*=\s*"([^"]+)"',
        description="Briefcase packager version (pyproject.toml [tool.briefcase])",
    ),
    # Site #4 — the top-level Python version constant. This is what
    # `version.py` exists for; every fallback below is, in theory, a
    # defensive echo of this.
    CallSite(
        path="version.py",
        pattern=r'^__version__\s*=\s*"([^"]+)"',
        description="Top-level __version__ constant (version.py)",
    ),
    # Site #5 — shipped-default config-layer version. Users can edit the
    # User- or Runtime-layer config to override, but the System layer
    # ships with this literal.
    CallSite(
        path="middleware/config/system_config.json",
        pattern=r'"version"\s*:\s*"([^"]+)"',
        description="System-layer config version (middleware/config/system_config.json)",
    ),
    # Site #6 — CLI `--version` fallback. Fires when package metadata
    # can't be read (dev clones, editable installs without
    # `pip install -e .`).
    CallSite(
        path="cli/main.py",
        pattern=r'__version__\s*=\s*"([^"]+)"',
        description="CLI --version fallback (cli/main.py)",
    ),
    # Site #7 — bootstrap version-check fallback. Fires when
    # `system_config.json` is missing or unparseable.
    CallSite(
        path="bootstrap.py",
        pattern=r'system_config\.get\("version",\s*"([^"]+)"\)',
        description="Bootstrap version-check fallback (bootstrap.py)",
    ),
    # Site #8 — Pydantic default for `SkillCreate.version`. Skills created
    # without an explicit version inherit the current release number so
    # that downstream version-comparison logic has something sensible to
    # read. See inline comment at the call site for the contract.
    CallSite(
        path="middleware/storage/schemas.py",
        pattern=r'^\s*version:\s*str\s*=\s*"([^"]+)"',
        description="Pydantic SkillCreate.version default (middleware/storage/schemas.py)",
    ),
    # Site #9 — SQLAlchemy column-level default for `Skill.version`.
    # Mirrors site #8 so rows inserted via raw SQL or Alembic migrations
    # still get stamped with the current release number.
    CallSite(
        path="middleware/storage/models.py",
        pattern=r'mapped_column\(String\(32\),\s*default="([^"]+)"',
        description="SQLAlchemy Skill.version column default (middleware/storage/models.py)",
    ),
    # Site #10 — GUI auto-updater fallback. Fires when the auto-update
    # subsystem cannot read the installed package's version metadata.
    # Returning the correct literal here keeps update-check comparisons
    # from wrongly reporting the installed build as behind.
    CallSite(
        path="gui/modules/auto_update_manager.py",
        pattern=r'return\s*"(\d+\.\d+\.\d+)"',
        description="GUI auto-update version fallback (gui/modules/auto_update_manager.py)",
    ),
)


# ---------------------------------------------------------------------------
# Canonical source — pyproject.toml [project].version
# ---------------------------------------------------------------------------


CANONICAL_PATH = "pyproject.toml"
CANONICAL_SOURCE_LABEL = "pyproject.toml [project].version"


def _read_canonical_version(repo_root: Path) -> str:
    """
    Parse pyproject.toml and return the `[project].version` literal.

    Raises ``SystemExit(2)`` with a structured stderr message on any of
    the well-known failure modes enumerated in MS-DES-0005 §Error
    handling.
    """

    pyproject = repo_root / CANONICAL_PATH
    if not pyproject.is_file():
        sys.stderr.write(
            f"canonical source not found: {pyproject}\n"
            "Expected pyproject.toml at repo root. Use --repo-root to override.\n"
        )
        raise SystemExit(2)

    try:
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        sys.stderr.write(f"failed to parse {pyproject}: {exc}\n")
        raise SystemExit(2)

    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        sys.stderr.write(
            f"canonical version not declared at {pyproject} [project].version\n"
        )
        raise SystemExit(2)

    return version


# ---------------------------------------------------------------------------
# Per-site check
# ---------------------------------------------------------------------------


def _read_site(site: CallSite, repo_root: Path) -> SiteResult:
    """
    Run one registry entry's regex against its file.

    Returns a :class:`SiteResult` describing what was found (or why the
    check couldn't be completed). Does not raise — every failure mode is
    captured on the result object so the caller can aggregate a complete
    report in a single pass.
    """

    path = repo_root / site.path
    if not path.is_file():
        return SiteResult(
            site=site,
            found=None,
            error=f"file not found at {path}",
        )

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return SiteResult(
            site=site,
            found=None,
            error=f"could not read {path}: {exc}",
        )

    try:
        regex = site.compiled()
    except re.error as exc:
        # The registry is authored in this same file, so a bad regex is a
        # programmer error — surface it loudly rather than swallowing it
        # into a per-site `error` string that the drift report could
        # easily overlook.
        sys.stderr.write(
            f"malformed registry entry for {site.path}: {exc}\n"
            f"pattern: {site.pattern!r}\n"
        )
        raise SystemExit(2)

    if regex.groups != 1:
        sys.stderr.write(
            f"malformed registry entry for {site.path}: "
            f"pattern must have exactly one capture group, got {regex.groups}\n"
            f"pattern: {site.pattern!r}\n"
        )
        raise SystemExit(2)

    match = regex.search(text)
    if match is None:
        return SiteResult(
            site=site,
            found=None,
            error="regex did not match any line in the file",
        )

    # Compute the 1-indexed line number of the match's start. `text[:start]`
    # is cheap for files of repo size (all call sites live in files <1 MB).
    line_number = text.count("\n", 0, match.start()) + 1

    # Grab the full line containing the match for the drift-report context
    # column. The match might span multiple lines (rare — only the
    # Briefcase site's regex spans lines today), in which case we join
    # them with `\\n` for a single-line context string. For same-line
    # matches, just strip the trailing newline.
    line_start = text.rfind("\n", 0, match.start()) + 1  # 0 on first line
    line_end = text.find("\n", match.end())
    if line_end == -1:
        line_end = len(text)
    context = text[line_start:line_end].rstrip("\n").strip()

    captured = match.group(1)
    if not captured:
        return SiteResult(
            site=site,
            found=None,
            line=line_number,
            context=context,
            error="regex matched but capture group was empty",
        )

    return SiteResult(
        site=site,
        found=captured,
        line=line_number,
        context=context,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _emit_human(
    canonical: str,
    results: list[SiteResult],
    out: Any,
) -> int:
    """
    Print a human-readable drift report and return the exit code.

    Prints to ``out`` (typically ``sys.stdout``). Returns ``0`` on clean,
    ``1`` on drift. Exit code 2 cases are raised upstream before this
    function is called.
    """

    out.write(f"Canonical version ({CANONICAL_SOURCE_LABEL}): {canonical}\n")

    drifted = [r for r in results if not r.in_sync_with(canonical)]
    if not drifted:
        out.write(f"\nAll {len(results)} site(s) in sync at version {canonical}.\n")
        return 0

    out.write(f"\nDrift detected at {len(drifted)} site(s):\n\n")
    for result in drifted:
        out.write(f"  {result.site.path}")
        if result.line is not None:
            out.write(f":{result.line}")
        out.write(f"\n      Expected: {canonical}\n")
        out.write(f"      Found:    {result.found if result.found is not None else '(no match)'}\n")
        if result.context:
            out.write(f"      Context:  {result.context}\n")
        if result.error:
            out.write(f"      Error:    {result.error}\n")
        out.write("\n")

    out.write(
        f"Exit 1 — {len(drifted)} file(s) need bumping before release.\n"
    )
    return 1


def _emit_json(canonical: str, results: list[SiteResult], out: Any) -> int:
    """
    Emit a JSON drift report to ``out`` and return the exit code.

    Schema matches MS-DES-0005 §"Output format" — ``canonical_version``,
    ``canonical_source``, ``sites_checked``, ``sites_in_sync``, and a
    ``drift`` list with the same fields the human report prints.
    """

    drifted = [r for r in results if not r.in_sync_with(canonical)]
    payload = {
        "canonical_version": canonical,
        "canonical_source": CANONICAL_SOURCE_LABEL,
        "sites_checked": len(results),
        "sites_in_sync": len(results) - len(drifted),
        "drift": [
            {
                "path": r.site.path,
                "description": r.site.description,
                "line": r.line,
                "expected": canonical,
                "found": r.found,
                "context": r.context,
                "error": r.error,
            }
            for r in drifted
        ],
    }
    json.dump(payload, out, indent=2, ensure_ascii=False)
    out.write("\n")
    return 0 if not drifted else 1


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _default_repo_root() -> Path:
    """
    Return the directory above this script's own directory.

    ``build_scripts/check_release_versions.py`` lives one directory below
    the repo root, so `Path(__file__).resolve().parent.parent` points at
    the checkout. Keeping this in a helper makes the unit tests' mocking
    strategy obvious — they instead pass ``--repo-root`` pointing at a
    temp fixture directory.
    """

    return Path(__file__).resolve().parent.parent


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the script's command-line arguments."""

    parser = argparse.ArgumentParser(
        prog="check_release_versions.py",
        description=(
            "Verify that every hard-coded release-version literal in the "
            "Memento-Skills repo matches pyproject.toml [project].version. "
            "See docs/design/release-checklist-script.md (MS-DES-0005)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Path to the repo root. Defaults to the directory above this "
            "script (build_scripts/..). Use an absolute path when running "
            "under CI from a non-default working directory."
        ),
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Script entry point. Returns the process exit code.

    Split from ``if __name__ == '__main__'`` so that the test suite can
    call ``main(['--repo-root', str(fixture)])`` directly and inspect the
    return code without going through ``subprocess``.
    """

    args = _parse_args(argv)
    repo_root = args.repo_root.resolve() if args.repo_root else _default_repo_root()

    canonical = _read_canonical_version(repo_root)

    results = [_read_site(site, repo_root) for site in CALL_SITES]

    out = sys.stdout
    if args.as_json:
        return _emit_json(canonical, results, out)
    return _emit_human(canonical, results, out)


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess in tests
    raise SystemExit(main())
