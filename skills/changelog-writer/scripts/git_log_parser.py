#!/usr/bin/env python3
"""git_log_parser.py — Extract structured commit data from a Git repository.

This script is part of the changelog-writer skill. It parses Git history
into a JSON structure that the agent can use to write changelogs.

Usage:
    python git_log_parser.py [OPTIONS]

Options:
    --repo-path PATH        Path to the Git repository (default: current directory)
    --since DATE            Only include commits after this date (ISO 8601, e.g. 2026-01-01)
    --until DATE            Only include commits before this date (ISO 8601)
    --from-tag TAG          Start range at this tag (exclusive)
    --to-tag TAG            End range at this tag (inclusive, default: HEAD)
    --path-filter PATH      Only include commits touching files under this path
    --filter-scope SCOPE    Only include commits whose conventional-commit scope matches
                            (case-insensitive, exact match). Repeatable for OR-semantics:
                            --filter-scope auth --filter-scope api returns commits in
                            either scope. Summary counters recompute against the filtered
                            list. See docs/design/changelog-writer-scope-extraction.md
                            (MS-DES-0008) for rationale.
    --output PATH           Write JSON to this file (default: stdout)

Output format:
    {
        "repository": "repo-name",
        "range": { "from": "v0.1.0", "to": "HEAD" },
        "generated_at": "2026-04-13T12:00:00Z",
        "commits": [
            {
                "hash": "abc1234",
                "hash_short": "abc1234",
                "author": "Name <email>",
                "date": "2026-04-13",
                "message": "full commit message",
                "subject": "first line of commit message",
                "body": "remaining lines (if any)",
                "files_changed": 5,
                "insertions": 120,
                "deletions": 30,
                "files": ["path/to/file1.py", "path/to/file2.md"],
                "conventional": {
                    "type": "feat",
                    "scope": "auth",
                    "breaking": false,
                    "description": "add JWT token validation"
                }
            }
        ],
        "summary": {
            "total_commits": 15,
            "authors": ["Name1", "Name2"],
            "date_range": { "earliest": "2026-03-01", "latest": "2026-04-13" },
            "scopes_used": ["api", "auth"]
        }
    }

The "scopes_used" field is a sorted list of unique non-null, non-empty
conventional-commit scope strings across all returned commits. It is always
present; if no commit has a scope it is an empty list.

The "conventional" field is populated by parsing conventional commit prefixes
(feat, fix, docs, refactor, chore, test, style, perf, ci, build, revert).
If a commit message doesn't follow the conventional format, the "conventional"
field will have type: "uncategorized" and the full subject as the description.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Conventional commit parser
# ---------------------------------------------------------------------------

# Matches patterns like:
#   feat: description
#   feat(scope): description
#   feat!: breaking change
#   feat(scope)!: breaking change with scope
CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|docs|refactor|chore|test|style|perf|ci|build|revert)"
    r"(?:\((?P<scope>[^)]+)\))?"
    r"(?P<breaking>!)?"
    r":\s*(?P<description>.+)$",
    re.IGNORECASE,
)


def parse_conventional(subject: str) -> dict:
    """Attempt to parse a commit subject as a conventional commit.

    Args:
        subject: The first line of the commit message.

    Returns:
        A dict with keys: type, scope (or None), breaking (bool), description.
        If the subject doesn't match conventional format, type is "uncategorized".
    """
    match = CONVENTIONAL_RE.match(subject.strip())
    if match:
        return {
            "type": match.group("type").lower(),
            "scope": match.group("scope"),
            "breaking": match.group("breaking") is not None,
            "description": match.group("description").strip(),
        }
    # Check for "BREAKING CHANGE" in the subject even without conventional prefix
    breaking = "BREAKING CHANGE" in subject.upper() or "BREAKING-CHANGE" in subject.upper()
    return {
        "type": "uncategorized",
        "scope": None,
        "breaking": breaking,
        "description": subject.strip(),
    }


# ---------------------------------------------------------------------------
# Git log extraction
# ---------------------------------------------------------------------------

# Delimiter that's extremely unlikely to appear in commit messages.
# Used to split fields in the git log output.
FIELD_SEP = "<<|FIELD|>>"
RECORD_SEP = "<<|RECORD|>>"

# git log format string: hash, short hash, author, date, subject, body
LOG_FORMAT = FIELD_SEP.join(["%H", "%h", "%an <%ae>", "%ai", "%s", "%b"]) + RECORD_SEP


def run_git(args: list[str], cwd: str) -> str:
    """Run a git command and return stdout.

    Args:
        args: List of arguments to pass to git (e.g., ["log", "--oneline"]).
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
        print(f"ERROR: git {' '.join(args)} failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def get_changed_files(commit_hash: str, cwd: str) -> tuple[list[str], int, int]:
    """Get the list of files changed in a commit, plus insertion/deletion counts.

    Args:
        commit_hash: The full SHA of the commit.
        cwd: Path to the Git repository.

    Returns:
        A tuple of (file_paths, total_insertions, total_deletions).
    """
    # --numstat gives us insertions/deletions per file
    raw = run_git(["diff-tree", "--no-commit-id", "-r", "--numstat", commit_hash], cwd)
    files = []
    insertions = 0
    deletions = 0
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            ins = int(parts[0]) if parts[0] != "-" else 0
            dels = int(parts[1]) if parts[1] != "-" else 0
            insertions += ins
            deletions += dels
            files.append(parts[2])
    return files, insertions, deletions


def parse_git_log(
    repo_path: str,
    since: str | None = None,
    until: str | None = None,
    from_tag: str | None = None,
    to_tag: str | None = None,
    path_filter: str | None = None,
    filter_scopes: list[str] | None = None,
) -> dict:
    """Parse git log into a structured dictionary.

    Args:
        repo_path: Path to the Git repository root.
        since: Include commits after this date (ISO 8601).
        until: Include commits before this date (ISO 8601).
        from_tag: Start of tag range (exclusive).
        to_tag: End of tag range (inclusive). Defaults to HEAD.
        path_filter: Only include commits touching this path.
        filter_scopes: If set, include only commits whose ``conventional.scope``
            matches (case-insensitive, exact match) any of the listed scopes.
            OR-semantics across the list. An empty list is treated the same as
            ``None`` (no filter). Implements MS-DES-0008 AC #6.

    Returns:
        A dictionary matching the output format described in the module docstring.
        The ``summary`` block always contains ``scopes_used`` — a sorted list of
        unique non-null, non-empty scope strings across the (post-filter) commits.
    """
    # Build the git log command
    log_args = ["log", f"--format={LOG_FORMAT}"]

    # Tag range takes precedence over date range
    if from_tag:
        range_spec = f"{from_tag}..{to_tag or 'HEAD'}"
        log_args.append(range_spec)
    elif to_tag:
        log_args.append(to_tag)

    if since:
        log_args.append(f"--since={since}")
    if until:
        log_args.append(f"--until={until}")

    if path_filter:
        log_args.append("--")
        log_args.append(path_filter)

    raw = run_git(log_args, repo_path)

    # Parse records
    commits = []
    records = raw.split(RECORD_SEP)
    for record in records:
        record = record.strip()
        if not record:
            continue
        fields = record.split(FIELD_SEP)
        if len(fields) < 5:
            continue

        commit_hash = fields[0].strip()
        hash_short = fields[1].strip()
        author = fields[2].strip()
        date_raw = fields[3].strip()
        subject = fields[4].strip()
        body = fields[5].strip() if len(fields) > 5 else ""

        # Parse date to ISO format (just the date portion)
        date_str = date_raw[:10]  # "2026-04-13" from "2026-04-13 15:30:00 -0700"

        # Get file stats
        files, insertions, deletions = get_changed_files(commit_hash, repo_path)

        # Parse conventional commit
        conventional = parse_conventional(subject)

        full_message = f"{subject}\n\n{body}".strip() if body else subject

        commits.append({
            "hash": commit_hash,
            "hash_short": hash_short,
            "author": author,
            "date": date_str,
            "message": full_message,
            "subject": subject,
            "body": body,
            "files_changed": len(files),
            "insertions": insertions,
            "deletions": deletions,
            "files": files,
            "conventional": conventional,
        })

    # -----------------------------------------------------------------------
    # Apply --filter-scope (MS-DES-0008 AC #6 & #7)
    # -----------------------------------------------------------------------
    # The filter is applied *after* commits are built so the same parser pass
    # powers both filtered and unfiltered output. We normalize the filter
    # values to lowercase once, then do case-insensitive exact-match comparison
    # against each commit's conventional.scope. Commits whose scope is None
    # (unscoped feat/fix, or an uncategorized subject) never match — they're
    # dropped when a filter is active.
    #
    # An empty filter list is treated as "no filter" so callers can pass
    # ``filter_scopes=[]`` without it silently zeroing their results.
    if filter_scopes:
        needles = {s.lower() for s in filter_scopes}
        commits = [
            c for c in commits
            if c["conventional"]["scope"] is not None
            and c["conventional"]["scope"].lower() in needles
        ]

    # -----------------------------------------------------------------------
    # Build summary
    # -----------------------------------------------------------------------
    # All summary counters are computed against the *post-filter* commit list
    # so downstream consumers never have to reconcile two different commit
    # counts. If a filter eliminated every commit, authors/dates fall out to
    # empty/None naturally — the caller sees a consistent empty-result shape.
    authors = sorted(set(c["author"].split(" <")[0] for c in commits))
    dates = [c["date"] for c in commits]
    repo_name = Path(repo_path).name

    # Aggregate unique conventional-commit scopes. Per MS-DES-0008 AC #5 this
    # field is always present (never missing), always a sorted list, and skips
    # any commit whose scope is None or an empty string. We use a set to
    # deduplicate and sort at the end for stable JSON output.
    scopes_used = sorted({
        c["conventional"]["scope"]
        for c in commits
        if c["conventional"]["scope"]  # truthy — skips None and ""
    })

    return {
        "repository": repo_name,
        "range": {
            "from": from_tag or (since or "beginning"),
            "to": to_tag or "HEAD",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commits": commits,
        "summary": {
            "total_commits": len(commits),
            "authors": authors,
            "date_range": {
                "earliest": min(dates) if dates else None,
                "latest": max(dates) if dates else None,
            },
            "scopes_used": scopes_used,
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Parse command-line arguments and run the Git log parser."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract structured commit data from a Git repository."
    )
    parser.add_argument(
        "--repo-path", default=".",
        help="Path to the Git repository (default: current directory)",
    )
    parser.add_argument("--since", help="Only commits after this date (ISO 8601)")
    parser.add_argument("--until", help="Only commits before this date (ISO 8601)")
    parser.add_argument("--from-tag", help="Start range at this tag (exclusive)")
    parser.add_argument("--to-tag", help="End range at this tag (inclusive, default: HEAD)")
    parser.add_argument("--path-filter", help="Only commits touching this path")
    # --filter-scope is repeatable: argparse's action="append" gives us
    # a list of all values the user passed (or None if they passed none).
    # See MS-DES-0008 for the rationale on OR-semantics + exact-match.
    parser.add_argument(
        "--filter-scope",
        action="append",
        dest="filter_scopes",
        metavar="SCOPE",
        help=(
            "Only include commits whose conventional-commit scope matches "
            "(case-insensitive, exact match). Repeatable for OR-semantics."
        ),
    )
    parser.add_argument("--output", help="Write JSON to file (default: stdout)")

    args = parser.parse_args()

    result = parse_git_log(
        repo_path=args.repo_path,
        since=args.since,
        until=args.until,
        from_tag=args.from_tag,
        to_tag=args.to_tag,
        path_filter=args.path_filter,
        filter_scopes=args.filter_scopes,
    )

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
