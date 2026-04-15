#!/usr/bin/env python3
"""doc_freshness_scanner.py — Scan documentation for staleness by cross-referencing Git history.

This script is part of the doc-freshness skill. It identifies documentation that may
be out of date by comparing the doc's last modification date against recent commits
that touch code files mentioned or referenced in the documentation.

Usage:
    python doc_freshness_scanner.py [OPTIONS]

Options:
    --repo-path PATH        Path to the Git repository (default: current directory)
    --docs-path PATH        Path to documentation directory relative to repo
                            (default: docs/)
    --since DATE            Include code changes after this date (ISO 8601 or relative
                            e.g. '30 days ago'; default: 30 days ago)
    --output PATH           Write JSON to this file (default: stdout)
    --include-untracked     Include docs with no Git history, using filesystem
                            mtime as a fallback (default: off — untracked docs
                            are skipped). Each document record gains a
                            ``tracked`` boolean when this flag is used.
    --min-priority LEVEL    Filter output to docs at or above this priority
                            (one of: low, medium, high; default: low = no
                            filter). Summary counters recompute against the
                            filtered list. See MS-DES-0009 for rationale.
    --format FORMAT         Output format (one of: json, priority-digest;
                            default: json). ``priority-digest`` emits a
                            concise Markdown digest suitable for weekly
                            review; ``json`` is the existing machine-
                            readable output.

Output format (JSON, default):
    {
        "scan_date": "2026-04-13",
        "docs_path": "docs/",
        "since": "2026-03-13",
        "documents": [
            {
                "path": "docs/getting-started.md",
                "last_updated": "2026-02-15",
                "days_since_update": 57,
                "status": "likely_stale",
                "importance_score": 0.73,
                "priority": "high",
                "related_code_changes": [
                    {
                        "hash": "abc1234",
                        "date": "2026-04-01",
                        "subject": "refactor auth module",
                        "files": ["src/auth.py"]
                    }
                ],
                "matched_topics": ["auth", "config.json"],
                "recommendation": "Review — related code changed 12 days ago but doc
                                 hasn't been updated in 57 days"
            }
        ],
        "summary": {
            "total_docs": 10,
            "fresh": 6,
            "possibly_stale": 2,
            "likely_stale": 2,
            "priority_counts": {"high": 2, "medium": 3, "low": 5}
        }
    }

The ``importance_score`` and ``priority`` fields are added by MS-DES-0009
(relevance v2). See ``doc_importance.py`` for the scoring formula; in short,
a BM25-derived "distinctive content density" signal is combined with an
inbound-reference-count signal, both max-normalized across the corpus, to
produce a float in [0.0, 1.0]. Priority is a three-bucket discretization.

Status classification:
    - fresh: Doc updated more recently than any related code change, OR no related
             code changes found
    - possibly_stale: Related code changed, but doc was updated within 30 days of
                     that change
    - likely_stale: Related code changed and doc hasn't been updated within 30 days
                    of that change
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Sibling import — doc_importance lives alongside this script and exposes
# the compute_importance_scores() / classify_priority() entry points.
# Keep import relative to this file's directory so the script works whether
# invoked as ``python doc_freshness_scanner.py`` from its own dir or as
# ``python skills/doc-freshness/scripts/doc_freshness_scanner.py`` from the
# repo root. See MS-DES-0009 "Why a ported BM25 module" for why we import
# a sibling rather than core/skill/retrieval/local_bm25_recall.py.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from doc_importance import (  # noqa: E402  (after sys.path mutation)
    classify_priority,
    compute_importance_scores,
)


# ---------------------------------------------------------------------------
# Path reference extraction (primary signal for relevance matching)
# ---------------------------------------------------------------------------
#
# Design note: docs/design/doc-freshness-relevance-filter.md (2026-04-13).
#
# The scanner previously matched commits to docs using fuzzy substring
# matching over every backtick-quoted term and heading in the doc. That
# produced false positives when docs happened to share common English words
# ("skill", "agent", "tool") with commit subjects or file paths.
#
# The new matching strategy uses only paths the doc *explicitly references* —
# file paths, directory paths, and the targets of repo-relative Markdown
# links — and matches them against a commit's changed files via directory-
# prefix containment. Commit-subject matching is dropped entirely.

# Regex explanations:
#
# PATH_IN_BACKTICKS matches an inline-code span whose contents look like a
# filesystem path: must contain at least one slash OR end in a common file
# extension. Examples matched:
#   `core/skill/gateway.py`, `docs/design/`, `skills/`, `config.json`
#
# FILE_EXTENSIONS is the set of extensions we accept as "path-like" even
# without a slash. Extend this list if the project uses additional source
# languages (e.g., .cs for C#, .tsx for TypeScript React).
FILE_EXTENSIONS = (
    "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml",
    "md", "mdx", "txt", "conf", "cfg", "sh", "rb", "go", "rs",
    "cs", "cshtml", "xml", "toml", "ini",
)

# Inline-code span with a path-looking payload.
PATH_IN_BACKTICKS = re.compile(
    r"`([^`\s]*(?:/[^`\s]*|\.(?:" + "|".join(FILE_EXTENSIONS) + r")))`"
)

# Markdown link with a repo-relative target (./foo, ../foo, or bare path).
# We skip http(s) links and anchor-only links (#section).
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")

# Bare file paths in prose (already present in the original scanner —
# kept for the path-reference extraction below).
BARE_FILE_PATH = re.compile(
    r"(?:^|\s)([a-zA-Z0-9_./\-]+\.(?:" + "|".join(FILE_EXTENSIONS) + r"))"
)

# Minimum length for a path reference to count. Guards against matching
# two-character strings like "io" that would overlap almost any path.
MIN_PATH_LENGTH = 3


def _normalize_path_reference(
    raw: str,
    doc_dir: Path,
    *,
    resolve_relative_to_doc: bool,
) -> str | None:
    """Normalize a raw path reference into a repo-relative path string.

    Two resolution modes exist because Markdown has two conventions:

    - **Inline code and bare prose paths** (``resolve_relative_to_doc=False``).
      When a doc writes `` `core/skill/gateway.py` `` in prose, the path is
      virtually always intended as a repo-relative path — the author is
      naming a file in the repo, not a file beneath their own doc's folder.
      We trust what the author wrote and do no resolution.

    - **Markdown link targets** (``resolve_relative_to_doc=True``). By the
      CommonMark spec, a link target like ``../core/skill/x.py`` is
      resolved against the document's own directory. We follow that rule
      so we can compute the repo-relative form.

    Args:
        raw: The raw path string as it appears in the doc (may contain
             ``./``, ``../``, trailing ``/``, etc.).
        doc_dir: The directory of the doc that contains the reference, as
                 a Path relative to the repo root.
        resolve_relative_to_doc: If True, apply Markdown link-target
                                 resolution semantics. If False, treat the
                                 path as repo-relative.

    Returns:
        A normalized, repo-relative path (no leading ``./``; trailing ``/``
        preserved on directories). Returns None if the reference is too
        short, is an external URL, an anchor-only link, or resolves
        outside the repo root.
    """
    import os

    if not raw:
        return None

    # Reject URLs and anchors outright — they're never repo paths.
    if raw.startswith(("http://", "https://", "mailto:", "#")):
        return None

    # Preserve whether the caller wrote a trailing slash (indicates a
    # directory reference vs. a file reference).
    had_trailing_slash = raw.endswith("/")

    try:
        if raw.startswith("/"):
            # Absolute-looking path — strip leading slash and treat the
            # remainder as repo-relative.
            candidate = raw.lstrip("/")
        elif resolve_relative_to_doc:
            # Markdown link semantics: resolve against the doc's directory.
            candidate = str(doc_dir / raw)
        else:
            # Inline-code / bare-prose path: trust it as-is (repo-relative).
            candidate = raw
        normalized = os.path.normpath(candidate)
    except (ValueError, OSError):
        return None

    # Force forward slashes so matching works cross-platform and aligns
    # with the paths Git emits.
    normalized = normalized.replace(os.sep, "/")

    # Drop leading `./` that normpath may leave on a same-directory reference.
    if normalized.startswith("./"):
        normalized = normalized[2:]

    # ``os.path.normpath`` strips trailing slashes; put it back for dirs.
    if had_trailing_slash:
        normalized = normalized.rstrip("/") + "/"

    # Reject overly short references.
    if len(normalized.rstrip("/")) < MIN_PATH_LENGTH:
        return None

    # Reject anything that resolved out of the repo (starts with `..`).
    if normalized.startswith(".."):
        return None

    return normalized


def extract_path_references(content: str, doc_rel_path: Path) -> set[str]:
    """Extract normalized, repo-relative paths that the doc references.

    This is the primary signal for the relevance filter. It considers three
    sources, in order of reliability:

    1. Inline code spans that look like paths (`core/skill/gateway.py`).
    2. Markdown link targets that point at repo-relative locations
       (`[text](../auth.md)`) — external URLs and anchors are ignored.
    3. Bare path-looking tokens in prose (`src/foo.py mentioned without
       backticks`).

    Args:
        content: The full Markdown source as a string.
        doc_rel_path: The doc's path relative to the repo root. Used to
                      resolve relative link targets.

    Returns:
        A set of normalized path strings (directory paths retain their
        trailing slash; file paths do not). All paths are repo-relative.
    """
    refs: set[str] = set()
    doc_dir = doc_rel_path.parent

    # 1. Inline-code path references — treat as repo-relative.
    for match in PATH_IN_BACKTICKS.finditer(content):
        normalized = _normalize_path_reference(
            match.group(1), doc_dir, resolve_relative_to_doc=False,
        )
        if normalized:
            refs.add(normalized)

    # 2. Markdown link targets — follow CommonMark link resolution (the
    #    target is relative to the doc's own directory).
    for match in MARKDOWN_LINK.finditer(content):
        normalized = _normalize_path_reference(
            match.group(1), doc_dir, resolve_relative_to_doc=True,
        )
        if normalized:
            refs.add(normalized)

    # 3. Bare path-like tokens in prose — treat as repo-relative, same as
    #    inline-code references.
    for match in BARE_FILE_PATH.finditer(content):
        normalized = _normalize_path_reference(
            match.group(1), doc_dir, resolve_relative_to_doc=False,
        )
        if normalized:
            refs.add(normalized)

    return refs


# ---------------------------------------------------------------------------
# Topic extraction (retained for display/debugging only — no longer used for
# relevance matching; see extract_path_references above).
# ---------------------------------------------------------------------------

def extract_topics_from_doc(content: str) -> set[str]:
    """Extract topics (searchable terms) from markdown document content.

    Extracts:
    - Terms in backticks (e.g., `config.json`, `auth` module)
    - Heading text (from # ## ### etc.)
    - File paths mentioned (e.g., src/auth.py, docs/api.md)

    Args:
        content: The full markdown file content as a string.

    Returns:
        A set of topic strings, lowercased and deduplicated.
    """
    topics = set()

    # 1. Extract backtick-quoted terms
    # Matches `term` or `term-name` or `file.ext`
    backtick_pattern = r'`([^`]+)`'
    for match in re.finditer(backtick_pattern, content):
        term = match.group(1).strip().lower()
        if term:
            topics.add(term)

    # 2. Extract heading text (# Heading, ## Sub-heading, etc.)
    # Headings are typically key topics in documentation
    heading_pattern = r'^#+\s+(.+?)$'
    for match in re.finditer(heading_pattern, content, re.MULTILINE):
        heading = match.group(1).strip().lower()
        if heading:
            topics.add(heading)

    # 3. Extract file paths (src/file.ext, path/to/config.yaml, etc.)
    # Matches patterns like: path/to/file.ext or path/file or just module_name
    filepath_pattern = r'(?:^|\s)([a-zA-Z0-9_./\-]+\.(?:py|js|ts|json|yaml|yml|md|txt|conf|cfg|sh|rb|go|rs))'
    for match in re.finditer(filepath_pattern, content, re.MULTILINE):
        filepath = match.group(1).strip().lower()
        if filepath:
            topics.add(filepath)

    return topics


# ---------------------------------------------------------------------------
# Git utilities
# ---------------------------------------------------------------------------

def run_git(args: list[str], cwd: str) -> str:
    """Run a git command and return stdout.

    Args:
        args: List of arguments to pass to git.
        cwd: Working directory (the repository path).

    Returns:
        The stdout output as a string.

    Raises:
        SystemExit: If the git command fails.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"ERROR: git {' '.join(args)} failed:\n{result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)
    return result.stdout


def get_doc_last_modified(doc_path: str, repo_path: str) -> str | None:
    """Get the last modification date of a document via git log.

    Args:
        doc_path: Path to the document (relative to repo root).
        repo_path: Path to the Git repository.

    Returns:
        ISO 8601 date string (YYYY-MM-DD), or None if no history found
        (typically an untracked file).
    """
    # git log -1 --format=%ai returns date in format: 2026-04-13 15:30:00 +0000
    output = run_git(["log", "-1", "--format=%ai", "--", doc_path], repo_path)
    if output.strip():
        # Extract just the date portion (YYYY-MM-DD)
        return output.strip()[:10]
    return None


def get_doc_mtime_date(full_path: Path) -> str | None:
    """Get the file's last-modified date from the filesystem.

    Used as a fallback for untracked files (those with no Git history)
    when ``--include-untracked`` is enabled. Filesystem mtime is less
    reliable than Git's commit history — it reflects any touch to the
    file, including unrelated editor saves — but for work-in-progress
    branches it's the only signal available.

    Args:
        full_path: Absolute path to the file on disk.

    Returns:
        ISO 8601 date string (YYYY-MM-DD), or None if the file can't be
        statted (broken symlink, permission error, etc.).
    """
    try:
        mtime = full_path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")


def get_recent_code_commits(
    repo_path: str,
    since: str,
    docs_path: str,
) -> list[dict]:
    """Get recent commits that touched non-documentation code files.

    Excludes commits that only touch files under docs_path to focus on actual
    code changes rather than documentation changes.

    Args:
        repo_path: Path to the Git repository.
        since: Date string for filtering (e.g., '2026-03-13').
        docs_path: Path to documentation directory (for exclusion).

    Returns:
        List of commit dicts with keys: hash, date, subject, files.
    """
    # Build git log args to find commits after the since date
    # Use --format with delimiters to safely parse multi-line output
    delimiter = "<<|SEP|>>"
    log_format = f"%H{delimiter}%ai{delimiter}%s{delimiter}%n%n"

    log_args = [
        "log",
        f"--format={log_format}",
        f"--since={since}",
        "--no-merges",
    ]

    output = run_git(log_args, repo_path)

    commits = []
    records = output.split("\n\n")

    for record in records:
        record = record.strip()
        if not record:
            continue

        lines = record.split("\n")
        if not lines or delimiter not in lines[0]:
            continue

        # Parse header line
        header = lines[0]
        parts = header.split(delimiter)
        if len(parts) < 3:
            continue

        commit_hash = parts[0].strip()
        date_raw = parts[1].strip()
        subject = parts[2].strip()

        # Extract date (format: 2026-04-13 15:30:00 +0000)
        date_str = date_raw[:10] if date_raw else ""

        # Get list of changed files for this commit
        files = get_commit_files(commit_hash, repo_path, docs_path)

        # Only include commits that touched non-doc files
        if files:
            commits.append({
                "hash": commit_hash,
                "date": date_str,
                "subject": subject,
                "files": files,
            })

    return commits


def get_commit_files(commit_hash: str, repo_path: str, docs_path: str) -> list[str]:
    """Get list of non-documentation files changed in a commit.

    Filters out files within docs_path to focus on code changes.

    Args:
        commit_hash: The commit SHA.
        repo_path: Path to the Git repository.
        docs_path: Path to documentation directory (excluded from results).

    Returns:
        List of file paths (relative to repo root) that were changed.
    """
    # git diff-tree shows all changed files for a commit
    output = run_git(
        ["diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash],
        repo_path,
    )

    files = []
    # Normalize docs_path for comparison (remove trailing slash)
    docs_prefix = docs_path.rstrip("/") + "/"

    for line in output.strip().splitlines():
        filepath = line.strip()
        if filepath and not filepath.startswith(docs_prefix):
            files.append(filepath)

    return files


# ---------------------------------------------------------------------------
# Topic matching
# ---------------------------------------------------------------------------

def _path_overlaps(referenced: str, changed_file: str) -> bool:
    """Decide whether a commit-changed file is covered by a doc's reference.

    A "reference" here is a normalized repo-relative path from
    ``extract_path_references``. It may be either a file path
    (``core/skill/gateway.py``) or a directory path
    (``core/skill/``, trailing slash preserved).

    Matching rules:

    1. **Directory reference.** ``changed_file`` is under that directory
       (prefix match on the trailing-slash form).
    2. **File reference — exact.** ``changed_file`` equals the reference.
    3. **File reference — sibling.** ``changed_file`` lives in the same
       directory as the referenced file. This covers the common case where
       a doc names one module in a directory but the refactor touched a
       sibling (``core/skill/gateway.py`` referenced; commit touched
       ``core/skill/market.py``).

    Args:
        referenced: A normalized path from the doc (may end in ``/`` for a
                    directory; no leading ``./``).
        changed_file: A repo-relative path from a commit's changed files.

    Returns:
        True if the reference is a plausible ancestor or sibling of the
        changed file.
    """
    if not referenced or not changed_file:
        return False

    # Case 1: directory reference.
    if referenced.endswith("/"):
        return changed_file.startswith(referenced)

    # Case 2: exact file match.
    if referenced == changed_file:
        return True

    # Case 3: sibling match — both live in the same directory.
    # Example: referenced='core/skill/gateway.py',
    #          changed_file='core/skill/market.py' → True.
    ref_dir = referenced.rsplit("/", 1)[0] if "/" in referenced else ""
    changed_dir = changed_file.rsplit("/", 1)[0] if "/" in changed_file else ""

    # Require a non-empty common directory; otherwise anything in the repo
    # root would match anything else in the repo root.
    return bool(ref_dir) and ref_dir == changed_dir


def find_related_commits(
    doc_path_refs: set[str],
    commits: list[dict],
) -> list[dict]:
    """Find commits whose changed files overlap with paths the doc references.

    This is the post-2026-04-13 implementation. See
    ``docs/design/doc-freshness-relevance-filter.md`` for rationale. The
    old behaviour (substring matching over every backtick-quoted term and
    heading, plus unanchored matching against commit subjects) produced too
    many false positives. The new logic restricts matching to directory-
    prefix overlap between the doc's explicit path references and the
    commit's changed files.

    Args:
        doc_path_refs: Set of normalized, repo-relative paths the doc
                       references (from ``extract_path_references``).
        commits: List of commit dicts (from ``get_recent_code_commits``).

    Returns:
        List of commits that overlap on at least one path, each augmented
        with a ``matched_topics`` field listing the doc-referenced paths
        that matched. The field name is retained for output-schema
        compatibility; the values are now paths, not substrings.
    """
    related = []

    # No path references in the doc means nothing to match against. This is
    # a deliberate behaviour change: docs with no referenced paths will
    # always be classified as "fresh" (with the reasoning surfaced in the
    # recommendation text). If that turns out to miss cases, revisit.
    if not doc_path_refs:
        return related

    for commit in commits:
        matched_refs: set[str] = set()

        for changed_file in commit.get("files", []):
            for ref in doc_path_refs:
                if _path_overlaps(ref, changed_file):
                    matched_refs.add(ref)

        if matched_refs:
            commit_with_match = commit.copy()
            # `matched_topics` is preserved for schema stability; values are
            # now paths instead of lowercased substrings.
            commit_with_match["matched_topics"] = sorted(matched_refs)
            related.append(commit_with_match)

    return related


def classify_freshness(
    doc_path: str,
    doc_last_updated: str,
    related_commits: list[dict],
) -> tuple[str, str]:
    """Classify a document's freshness status and generate recommendation.

    Classification logic:
    - fresh: No related code changes, or doc updated after all changes
    - possibly_stale: Related changes exist but doc updated within 30 days
    - likely_stale: Related changes but doc hasn't been updated within 30 days

    Args:
        doc_path: Path to the document (for reporting).
        doc_last_updated: ISO 8601 date string (YYYY-MM-DD).
        related_commits: List of related commits from find_related_commits.

    Returns:
        Tuple of (status, recommendation_text).
    """
    if not related_commits:
        return "fresh", "No recent code changes detected in referenced topics."

    # Parse doc date
    doc_date = datetime.fromisoformat(doc_last_updated).date()

    # Find the most recent related code change
    most_recent_commit = max(related_commits, key=lambda c: c["date"])
    most_recent_date = datetime.fromisoformat(
        most_recent_commit["date"]
    ).date()

    days_since_doc_update = (datetime.now(timezone.utc).date() - doc_date).days
    days_since_code_change = (
        datetime.now(timezone.utc).date() - most_recent_date
    ).days
    days_between = (doc_date - most_recent_date).days

    # If doc was updated after the code change, it's fresh
    if doc_date >= most_recent_date:
        return "fresh", "Doc updated after most recent related code change."

    # If code changed but doc was updated within 30 days of that change
    if days_between >= -30:
        return (
            "possibly_stale",
            f"Related code changed {days_since_code_change} days ago, "
            f"but doc was updated {abs(days_between)} days after. "
            f"Verify if updates are needed.",
        )

    # Code changed and doc not updated within 30 days
    return (
        "likely_stale",
        f"Review — related code changed {days_since_code_change} days ago "
        f"but doc hasn't been updated in {days_since_doc_update} days.",
    )


# ---------------------------------------------------------------------------
# Main scanning logic
# ---------------------------------------------------------------------------

def scan_documentation(
    repo_path: str = ".",
    docs_path: str = "docs/",
    since: str = None,
    include_untracked: bool = False,
    min_priority: str = "low",
) -> dict:
    """Scan documentation directory and cross-reference against Git history.

    Args:
        repo_path: Path to Git repository root.
        docs_path: Path to documentation directory (relative to repo root).
        since: Date string for filtering code changes. If None, defaults to
               30 days ago.
        include_untracked: When True, documents that have no Git history
                           (e.g., brand-new files on a work-in-progress
                           branch) are included using filesystem mtime as
                           their last-modified date. A ``tracked`` boolean
                           field is added to each document record so
                           consumers can tell the two cases apart. When
                           False (default), untracked docs are skipped
                           silently — the original behaviour.
        min_priority: Filter the returned ``documents`` list to records at or
                      above this priority. One of ``"low"``, ``"medium"``,
                      ``"high"``. Default ``"low"`` passes everything
                      through (no filter). See MS-DES-0009 AC #5 / #6.
                      Summary counters recompute against the filtered list
                      so downstream consumers see consistent numbers.

    Returns:
        Dictionary matching the output format described in module docstring.
        Every document record gains ``importance_score`` (float in [0, 1])
        and ``priority`` (one of low/medium/high) per MS-DES-0009. The
        summary block gains ``priority_counts`` with the same three keys.
    """
    repo_path = Path(repo_path).resolve()
    docs_dir = repo_path / docs_path

    # Default to 30 days ago if not specified
    if since is None:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        since = thirty_days_ago.strftime("%Y-%m-%d")

    # Find all .md files in docs directory
    if not docs_dir.exists():
        print(f"WARNING: docs directory not found: {docs_dir}", file=sys.stderr)
        md_files = []
    else:
        md_files = sorted(docs_dir.rglob("*.md"))

    # -----------------------------------------------------------------------
    # MS-DES-0009: compute per-doc importance scores once, up front.
    # -----------------------------------------------------------------------
    # We score every .md file found on disk, not just those with Git history,
    # so an untracked-but-included doc gets a valid score. The scores dict
    # is keyed by POSIX-style path relative to the docs-tree root (not the
    # repo root); we translate at lookup time below.
    #
    # For a corpus with zero docs, compute_importance_scores returns an
    # empty dict and every lookup falls back to 0.0 / "low" — no error path.
    importance_scores = compute_importance_scores(docs_dir, md_files)

    # Get recent code commits (once, for all docs)
    recent_commits = get_recent_code_commits(
        str(repo_path),
        since,
        docs_path,
    )

    # Analyze each document
    documents = []
    status_counts = {"fresh": 0, "possibly_stale": 0, "likely_stale": 0}
    # MS-DES-0009: parallel counter keyed by priority bucket, computed
    # against the *post-filter* document list to match status_counts.
    priority_counts = {"high": 0, "medium": 0, "low": 0}

    for md_file in md_files:
        # Get path relative to repo root
        rel_path = md_file.relative_to(repo_path)

        # Get document's last modification date from Git history first.
        last_updated = get_doc_last_modified(str(rel_path), str(repo_path))
        tracked = last_updated is not None

        if not last_updated:
            # No Git history for this file (untracked, or never committed).
            if include_untracked:
                last_updated = get_doc_mtime_date(md_file)
                if not last_updated:
                    # Couldn't stat the file either — skip.
                    continue
            else:
                # Original behaviour: silently skip untracked files.
                continue

        # Read document content.
        content = md_file.read_text(encoding="utf-8", errors="ignore")

        # Primary signal for matching: explicit path references in the doc
        # (see docs/design/doc-freshness-relevance-filter.md).
        path_refs = extract_path_references(content, rel_path)

        # Legacy topic set retained for the `matched_topics` display field
        # fallback when the doc has no path references but we still want to
        # surface what it mentions. Not used for matching.
        topics = extract_topics_from_doc(content)

        # Find commits whose changed files overlap the doc's referenced paths.
        related_commits = find_related_commits(path_refs, recent_commits)

        # Classify freshness
        status, recommendation = classify_freshness(
            str(rel_path),
            last_updated,
            related_commits,
        )

        # Calculate days since update
        doc_date = datetime.fromisoformat(last_updated).date()
        days_since_update = (datetime.now(timezone.utc).date() - doc_date).days

        # MS-DES-0009: look up the doc's importance score. The importance
        # dict is keyed by path relative to docs_dir; our md_file is
        # absolute, so we translate once here. A missing key (shouldn't
        # happen — compute_importance_scores processes every md_file we
        # passed in) falls back to 0.0 / "low" for a belt-and-suspenders
        # safety net.
        try:
            importance_key = md_file.resolve().relative_to(docs_dir.resolve()).as_posix()
        except ValueError:
            importance_key = None
        importance_score = (
            importance_scores.get(importance_key, 0.0)
            if importance_key is not None
            else 0.0
        )
        priority = classify_priority(importance_score)

        # Build document record. The ``tracked`` flag tells downstream
        # consumers (the pipeline orchestrator, the feedback log, etc.)
        # whether ``last_updated`` came from Git history (authoritative)
        # or filesystem mtime (best-effort). ``importance_score`` and
        # ``priority`` are the MS-DES-0009 additions.
        doc_record = {
            "path": str(rel_path),
            "last_updated": last_updated,
            "days_since_update": days_since_update,
            "tracked": tracked,
            "status": status,
            "importance_score": round(importance_score, 4),
            "priority": priority,
            "related_code_changes": related_commits,
            "matched_topics": sorted(list(topics))[:10],  # Top 10 topics
            "recommendation": recommendation,
        }

        documents.append(doc_record)

    # -----------------------------------------------------------------------
    # MS-DES-0009: apply --min-priority filter post-hoc, then recompute all
    # summary counters against the filtered list so downstream consumers
    # never have to reconcile two different doc counts.
    # -----------------------------------------------------------------------
    # The ordinal ordering of the priority buckets is low < medium < high.
    # "low" passes everything through (default); "medium" keeps medium+high;
    # "high" keeps high only.
    _PRIORITY_ORDINAL = {"low": 0, "medium": 1, "high": 2}
    threshold = _PRIORITY_ORDINAL.get(min_priority, 0)
    if threshold > 0:
        documents = [
            d for d in documents
            if _PRIORITY_ORDINAL.get(d["priority"], 0) >= threshold
        ]

    # Recompute counters on the (possibly filtered) final document list.
    for d in documents:
        status_counts[d["status"]] += 1
        priority_counts[d["priority"]] += 1

    return {
        "scan_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "docs_path": docs_path,
        "since": since,
        "documents": documents,
        "summary": {
            "total_docs": len(documents),
            "fresh": status_counts["fresh"],
            "possibly_stale": status_counts["possibly_stale"],
            "likely_stale": status_counts["likely_stale"],
            "priority_counts": priority_counts,
        },
    }


# ---------------------------------------------------------------------------
# Output formatters (MS-DES-0009)
# ---------------------------------------------------------------------------


def format_priority_digest(scan_result: dict) -> str:
    """Emit a concise Markdown digest suitable for weekly review.

    The digest groups documents by priority bucket (high → medium → low),
    omits empty buckets, and shows a single line per doc with path, status,
    days-since-update, and a short reason. Full commit lists and full
    recommendation prose are omitted — JSON mode is still the right format
    for deep investigation.

    Args:
        scan_result: The dict returned by ``scan_documentation``.

    Returns:
        A Markdown string, newline-terminated.
    """
    lines: list[str] = []
    summary = scan_result.get("summary", {})
    priority_counts = summary.get("priority_counts", {"high": 0, "medium": 0, "low": 0})

    # Header with the scan's date range for context.
    lines.append(f"# Doc-freshness priority digest — {scan_result.get('scan_date', 'unknown')}")
    lines.append("")
    lines.append(
        f"Scanned since **{scan_result.get('since', 'unknown')}** — "
        f"{summary.get('total_docs', 0)} docs "
        f"(fresh: {summary.get('fresh', 0)}, "
        f"possibly stale: {summary.get('possibly_stale', 0)}, "
        f"likely stale: {summary.get('likely_stale', 0)})"
    )
    lines.append("")
    lines.append(
        f"Priority mix — high: {priority_counts.get('high', 0)}, "
        f"medium: {priority_counts.get('medium', 0)}, "
        f"low: {priority_counts.get('low', 0)}"
    )

    # Group docs by priority bucket. Iterate in fixed high → medium → low
    # order so the digest's reading order is stable regardless of how the
    # source dict is ordered.
    docs = scan_result.get("documents", [])
    buckets: dict[str, list[dict]] = {"high": [], "medium": [], "low": []}
    for d in docs:
        buckets.setdefault(d.get("priority", "low"), []).append(d)

    bucket_labels = {
        "high": "High priority",
        "medium": "Medium priority",
        "low": "Low priority",
    }
    for bucket in ("high", "medium", "low"):
        items = buckets.get(bucket, [])
        if not items:
            continue
        lines.append("")
        lines.append(f"## {bucket_labels[bucket]}")
        lines.append("")
        # Sort by status severity (likely_stale first) then by days-since.
        _status_ordinal = {"likely_stale": 0, "possibly_stale": 1, "fresh": 2}
        items = sorted(
            items,
            key=lambda d: (
                _status_ordinal.get(d.get("status", "fresh"), 3),
                -d.get("days_since_update", 0),
            ),
        )
        for d in items:
            path = d.get("path", "(unknown)")
            status = d.get("status", "fresh")
            days = d.get("days_since_update", 0)
            score = d.get("importance_score", 0.0)
            # One-liner per doc. Use a compact reason clause; the full
            # recommendation is still available in the JSON output.
            lines.append(
                f"- `{path}` — **{status}**, "
                f"updated {days}d ago, "
                f"importance {score:.2f}"
            )

    lines.append("")  # trailing newline
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Parse command-line arguments and run the doc freshness scanner."""
    parser = argparse.ArgumentParser(
        description="Scan documentation for staleness by cross-referencing Git history."
    )
    parser.add_argument(
        "--repo-path",
        default=".",
        help="Path to the Git repository (default: current directory)",
    )
    parser.add_argument(
        "--docs-path",
        default="docs/",
        help="Path to documentation directory relative to repo (default: docs/)",
    )
    parser.add_argument(
        "--since",
        help="Include code changes after this date (ISO 8601, default: 30 days ago)",
    )
    parser.add_argument(
        "--output",
        help="Write JSON to file (default: stdout)",
    )
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help=(
            "Include docs that have no Git history, using filesystem "
            "mtime as a fallback. Each document record gains a "
            "`tracked` boolean field. Useful on work-in-progress "
            "branches; less reliable than Git history."
        ),
    )
    # MS-DES-0009: new CLI surface for the weekly-habit use case.
    parser.add_argument(
        "--min-priority",
        choices=["low", "medium", "high"],
        default="low",
        help=(
            "Filter output to docs at or above this priority bucket. "
            "'low' (default) = no filter; 'medium' keeps medium+high; "
            "'high' keeps high only. Summary counters recompute against "
            "the filtered list. See MS-DES-0009 for scoring details."
        ),
    )
    parser.add_argument(
        "--format",
        choices=["json", "priority-digest"],
        default="json",
        help=(
            "Output format. 'json' (default) is the existing machine-"
            "readable output. 'priority-digest' emits a concise Markdown "
            "digest suitable for weekly review."
        ),
    )

    args = parser.parse_args()

    result = scan_documentation(
        repo_path=args.repo_path,
        docs_path=args.docs_path,
        since=args.since,
        include_untracked=args.include_untracked,
        min_priority=args.min_priority,
    )

    # Dispatch on --format. The JSON branch is byte-for-byte what every
    # prior consumer expects (modulo the new fields specified in AC #4 and
    # #8 of MS-DES-0009, which are purely additive).
    if args.format == "priority-digest":
        output = format_priority_digest(result)
    else:
        output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
