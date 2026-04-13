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

Output format:
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
            "likely_stale": 2
        }
    }

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


# ---------------------------------------------------------------------------
# Topic extraction
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
        ISO 8601 date string (YYYY-MM-DD), or None if no history found.
    """
    # git log -1 --format=%ai returns date in format: 2026-04-13 15:30:00 +0000
    output = run_git(["log", "-1", "--format=%ai", "--", doc_path], repo_path)
    if output.strip():
        # Extract just the date portion (YYYY-MM-DD)
        return output.strip()[:10]
    return None


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

def find_related_commits(
    doc_topics: set[str],
    commits: list[dict],
) -> list[dict]:
    """Find commits where changed files or subjects match doc topics.

    Checks each commit's file paths and subject line against the topics
    extracted from the documentation.

    Args:
        doc_topics: Set of topics extracted from the doc.
        commits: List of commit dicts (from get_recent_code_commits).

    Returns:
        List of commits that have topic matches, with added "matched_topics" field.
    """
    related = []

    for commit in commits:
        matched_topics = set()

        # Check if any commit files match doc topics
        for filepath in commit.get("files", []):
            # Check for exact matches and partial matches
            filepath_lower = filepath.lower()
            for topic in doc_topics:
                # Match if topic appears in filepath (e.g., "auth" in "src/auth.py")
                # or if filepath appears in topics (e.g., "src/auth.py" in doc)
                if topic in filepath_lower or filepath_lower in topic:
                    matched_topics.add(topic)

        # Check if any topics appear in the commit subject
        subject_lower = commit["subject"].lower()
        for topic in doc_topics:
            if topic in subject_lower:
                matched_topics.add(topic)

        if matched_topics:
            commit_with_match = commit.copy()
            commit_with_match["matched_topics"] = sorted(list(matched_topics))
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
) -> dict:
    """Scan documentation directory and cross-reference against Git history.

    Args:
        repo_path: Path to Git repository root.
        docs_path: Path to documentation directory (relative to repo root).
        since: Date string for filtering code changes. If None, defaults to
               30 days ago.

    Returns:
        Dictionary matching the output format described in module docstring.
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

    # Get recent code commits (once, for all docs)
    recent_commits = get_recent_code_commits(
        str(repo_path),
        since,
        docs_path,
    )

    # Analyze each document
    documents = []
    status_counts = {"fresh": 0, "possibly_stale": 0, "likely_stale": 0}

    for md_file in md_files:
        # Get path relative to repo root
        rel_path = md_file.relative_to(repo_path)

        # Get document's last modification date
        last_updated = get_doc_last_modified(str(rel_path), str(repo_path))
        if not last_updated:
            # If no git history, skip the doc
            continue

        # Read document content and extract topics
        content = md_file.read_text(encoding="utf-8", errors="ignore")
        topics = extract_topics_from_doc(content)

        # Find commits related to this doc's topics
        related_commits = find_related_commits(topics, recent_commits)

        # Classify freshness
        status, recommendation = classify_freshness(
            str(rel_path),
            last_updated,
            related_commits,
        )

        # Calculate days since update
        doc_date = datetime.fromisoformat(last_updated).date()
        days_since_update = (datetime.now(timezone.utc).date() - doc_date).days

        # Build document record
        doc_record = {
            "path": str(rel_path),
            "last_updated": last_updated,
            "days_since_update": days_since_update,
            "status": status,
            "related_code_changes": related_commits,
            "matched_topics": sorted(list(topics))[:10],  # Top 10 topics
            "recommendation": recommendation,
        }

        documents.append(doc_record)
        status_counts[status] += 1

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
        },
    }


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

    args = parser.parse_args()

    result = scan_documentation(
        repo_path=args.repo_path,
        docs_path=args.docs_path,
        since=args.since,
    )

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
