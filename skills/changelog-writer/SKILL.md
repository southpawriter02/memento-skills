---
name: changelog-writer
description: Generates structured changelogs from Git commit history following Keep a Changelog conventions. Use this skill when the user asks to write a changelog, generate release notes from commits, summarize what changed between versions or tags, document recent changes, or prepare a CHANGELOG.md update. Also triggers on "what changed since [tag/date]," "write up the changes for this release," "changelog for v[X]," or when the user provides a Git tag range and wants a human-readable summary.
---

# Changelog writer

## Overview

You generate structured, human-readable changelogs from Git commit history. Your output follows [Keep a Changelog](https://keepachangelog.com/) conventions, which groups changes into categories: Added, Changed, Deprecated, Removed, Fixed, and Security.

**Announce at start:** "I'm using the changelog-writer skill to generate a changelog from your Git history."

## How this skill works

This skill combines a deterministic script (for extracting and parsing Git history) with your judgment (for categorizing ambiguous commits and writing clear descriptions). The script lives at `scripts/git_log_parser.py` within this skill's directory.

The workflow is:

1. **Extract** — Run the parser script to get structured commit data as JSON
2. **Categorize** — Map each commit to a Keep a Changelog category
3. **Write** — Produce a well-formatted changelog entry
4. **Review** — Present the draft and offer to refine

## Process

### Step 1 — Determine scope

Ask the user (or infer from context) what range of commits to include:

- **Tag range:** "What changed between v0.1.0 and v0.2.0?" → use `--from-tag v0.1.0 --to-tag v0.2.0`
- **Date range:** "What changed this month?" → use `--since 2026-04-01`
- **All history:** "Generate a changelog for this project" → no range filters
- **Path-scoped:** "What changed in the docs folder?" → use `--path-filter docs/`

If the user isn't specific, default to all commits since the most recent tag. Find the latest tag with:

```bash
git describe --tags --abbrev=0 2>/dev/null || echo "no tags found"
```

If no tags exist, include all commits.

### Step 2 — Extract commit data

Run the parser script. The script path is relative to this skill's directory:

```bash
python <skill-directory>/scripts/git_log_parser.py \
  --repo-path <path-to-repo> \
  [--from-tag <tag>] \
  [--to-tag <tag>] \
  [--since <date>] \
  [--until <date>] \
  [--path-filter <path>]
```

The script outputs JSON with full commit details including conventional commit parsing. Read the output — it's your raw material.

If the script isn't available or fails, fall back to running `git log` directly:

```bash
git log --format="%h|%an|%ai|%s" [range] --no-merges
```

This gives you less detail (no file stats or body text) but is enough to produce a basic changelog.

### Step 3 — Categorize commits

Map each commit to a Keep a Changelog category. Use this decision logic:

**If the commit follows conventional commit format** (the parser detects this automatically):

| Conventional type | Changelog category |
|-------------------|-------------------|
| `feat` | **Added** |
| `fix` | **Fixed** |
| `docs` | Omit from changelog (unless docs-focused project) |
| `refactor` | **Changed** |
| `perf` | **Changed** (note it's a performance improvement) |
| `test` | Omit from changelog |
| `style` | Omit from changelog |
| `chore` | Omit from changelog |
| `ci` | Omit from changelog |
| `build` | Omit from changelog (unless it affects users) |
| `revert` | Categorize based on what was reverted |
| `BREAKING CHANGE` | **Changed** with a prominent "BREAKING" prefix |

**If the commit is uncategorized** (no conventional prefix), read the subject and body to make a judgment call. Look for signal words:

- "add," "new," "introduce," "support" → **Added**
- "change," "update," "modify," "refactor," "improve" → **Changed**
- "deprecate," "obsolete" → **Deprecated**
- "remove," "delete," "drop" → **Removed**
- "fix," "bug," "patch," "resolve," "correct" → **Fixed**
- "security," "vulnerability," "CVE" → **Security**

**Commits to omit:** Skip merge commits, version bumps that only change a version number, and purely internal changes (CI config, linter config, test-only changes) unless the user specifically asks for a complete log.

### Step 4 — Write the changelog entry

Format the output as a Keep a Changelog entry:

```markdown
## [version or Unreleased] - YYYY-MM-DD

### Added

- Description of new feature or capability ([commit-hash])
- Another addition with enough context for a reader who wasn't involved ([commit-hash])

### Changed

- What changed and why it matters to the user ([commit-hash])

### Fixed

- What was broken and how it's fixed now ([commit-hash])
```

**Writing guidelines for each entry:**

- **Lead with what changed for the user**, not what you did to the code. "API responses now include pagination metadata" is better than "Added pagination fields to response serializer."
- **One line per logical change.** If three commits all contribute to the same feature, combine them into one entry and reference all three hashes.
- **Include the short commit hash** in parentheses or brackets at the end of each entry so readers can trace back to the code.
- **Omit empty categories.** If there are no "Deprecated" entries, don't include the heading.
- **Order categories:** Added → Changed → Deprecated → Removed → Fixed → Security. This is the Keep a Changelog convention.
- **Breaking changes get special treatment.** Prefix the entry with **BREAKING:** and add a brief migration note if possible.

### Step 5 — Handle edge cases

**Very few commits (1-3):** Don't over-structure. A simple bulleted list under a version heading is fine.

**Very many commits (50+):** Group related changes under sub-headings within each category if needed. Summarize minor changes ("Various bug fixes and performance improvements") and list only the significant ones individually.

**No conventional commits at all:** That's fine — most real-world repos don't use them. Categorize by reading the commit messages. Call out to the user if any commits are truly ambiguous: "I wasn't sure how to categorize 'update stuff' (abc1234) — is this a feature addition or a bugfix?"

**Mixed release and non-release commits:** If the user asks for "what changed since the last release" but there are also version-bump commits in the range, skip the version bumps.

### Step 6 — Present and offer next steps

Show the draft changelog to the user and offer:

- "Would you like me to append this to your existing CHANGELOG.md?" (if one exists)
- "Would you like me to create a new CHANGELOG.md?" (if none exists)
- "Want me to adjust the level of detail? I can make it more concise or more detailed."
- "Should I also generate release notes from this?" (hand off to the release-notes skill if available)

If the user asks you to write to CHANGELOG.md, **prepend** the new entry after any existing header/preamble but before any existing version entries. Keep a Changelog puts the newest version at the top.

## References

### Keep a Changelog format

The full spec is at [keepachangelog.com](https://keepachangelog.com/). The key conventions:

- Changelogs are for **humans**, not machines
- Every version gets its own section
- Most recent version comes **first**
- Dates use **ISO 8601** format (YYYY-MM-DD)
- Group changes by type: Added, Changed, Deprecated, Removed, Fixed, Security
- Use an **[Unreleased]** section for changes not yet in a tagged release

### Conventional commits reference

The conventional commits spec is at [conventionalcommits.org](https://www.conventionalcommits.org/). The format:

```text
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Common types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`, `build`, `revert`.
