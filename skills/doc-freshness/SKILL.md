---
name: doc-freshness
description: Scan documentation against recent code changes to identify potentially stale content. Triggers on requests like "stale docs", "outdated documentation", "what docs need updating", "doc freshness", "are my docs up to date", etc.
---

## Overview

Documentation freshness is a persistent challenge: features get built, APIs change, configurations evolve—but the docs that describe them often lag behind. This skill combines an automated scanner with agent judgment to identify which documentation might be out of date and needs review.

The process works in stages:

1. **Determine scope** — Which repository and documentation directory to scan?
2. **Run the scanner** — Extract topics from markdown docs, cross-reference against Git history to find related code changes
    - **2a. Weekly-rhythm recommendation** — For a low-friction weekly review, run the scanner with a priority filter and the concise digest format (see below). This is the intended habitual use — much lighter than reading the full JSON every time
3. **Interpret results** — Analyze the scanner output to understand what changed and why a doc might be stale
4. **Present findings** — Show a prioritized report highlighting the docs most likely to need updates
5. **Offer next steps** — Help take action: update the doc, flag an issue, create a task

## How the scanner works

The scanner (`scripts/doc_freshness_scanner.py`) performs these steps:

1. **Path-reference extraction** — For each markdown document, the scanner builds a set of repo-relative paths the doc explicitly mentions. Sources:
   - Inline code spans that look like paths (`` `core/skill/gateway.py` ``, `` `skills/` ``) — treated as repo-relative.
   - Bare path-like tokens in prose (e.g., `src/auth.py`) — treated as repo-relative.
   - Markdown link targets that resolve to repo-relative paths — `../` and `./` segments are resolved against the doc's own directory, per CommonMark semantics.
   - External URLs (`http(s)://`, `mailto:`, `#anchor`) are ignored.
   - References shorter than three characters are dropped to avoid matching short generic strings like `io`.

2. **Code-change detection** — The scanner queries Git for commits touching non-documentation code files since a specified date (default: 30 days ago). Each commit records its hash, date, subject, and full list of changed files.

3. **Path-overlap matching** — For each document, the scanner flags a commit as related if at least one of the commit's changed files overlaps with at least one path the doc references. Overlap rules:
   - A referenced **directory** (trailing slash, e.g. `core/skill/`) matches any file underneath that directory.
   - A referenced **file** matches that exact file OR any sibling file in the same directory (common case: a doc names one module in a package but the change touched a neighbour).
   - Bare root-level filenames do not match other root-level files.
   - Commit subjects are **not** matched — subject-line substring matching was removed because it produced frequent false positives for generic terms like `skill` or `agent`. See `docs/design/doc-freshness-relevance-filter.md` for the rationale.

4. **Freshness classification** — Based on the last update date of the doc and the most recent related code change:
   - **fresh**: No related code changes found, OR doc was updated after all related changes
   - **possibly_stale**: Related code changed, but doc was updated within 30 days of that change
   - **likely_stale**: Related code changed and doc hasn't been updated within 30 days of that change

5. **Importance scoring (v2)** — In addition to freshness, each doc is assigned an `importance_score` in `[0.0, 1.0]` and a coarse `priority` bucket (`low`, `medium`, `high`). The score is a convex combination of two BM25-derived signals: *distinctive content density* (sum of each doc's top-`K` term IDFs, a proxy for "how much unique technical content does this doc carry?") and *inbound reference authority* (count of other docs that link to or mention the doc). Weights default to 60% intrinsic / 40% reference. Priority buckets use tertile-inspired cut-points at `0.33` and `0.66`. See `docs/design/doc-freshness-relevance-v2-bm25-weighting.md` (MS-DES-0009) for the full rationale.

**Deliberate tradeoff:** a doc that mentions no paths at all will always classify as `fresh` with zero related changes. The scanner is input to human judgment, not a gate; false negatives are preferred over false positives because false positives erode trust in the signal.

## Report template

When presenting results, organize findings into a summary table and prioritized recommendations:

### Summary

| File | Status | Days Since Update | Latest Related Change |
|------|--------|-------------------|-----------------------|
| docs/getting-started.md | likely_stale | 57 | 12 days ago |
| docs/api.md | possibly_stale | 25 | 20 days ago |
| docs/deployment.md | fresh | 5 | N/A |

### Detailed findings

For each doc marked as `possibly_stale` or `likely_stale`, provide:
- The doc path
- Last update date and days since update
- Related code changes (commit hashes, subjects, affected files)
- Matched topics from the doc
- Recommended action

### Prioritized recommendations

Order recommendations by risk:
1. **Likely stale** docs (greatest risk of incorrect content)
2. **Possibly stale** docs with high-impact changes (e.g., API breaking changes)
3. **Fresh** docs (no action needed)

## Next steps

After presenting the report, offer the user actionable options:

- **"Would you like me to update this doc?"** — Help rewrite content to match current code
- **"Should I create a GitHub issue to flag this?"** — Open an issue for manual review
- **"Want me to scan a different time range?"** — Re-run with different `--since` date
- **"Check a specific doc?"** — Focus the scanner on a particular documentation file

## Scanner command reference

Run the scanner manually with:

```bash
python scripts/doc_freshness_scanner.py \
  --repo-path /path/to/repo \
  --docs-path docs/ \
  --since 2026-03-13 \
  --include-untracked \
  --output results.json
```

**Arguments:**

- `--repo-path` — Path to Git repository (default: current directory)
- `--docs-path` — Path to docs directory, relative to repo (default: `docs/`)
- `--since` — Date filter for code changes (ISO 8601, e.g. `2026-03-13`; default: 30 days ago)
- `--include-untracked` — Also scan Markdown files that are not yet tracked by Git. When this flag is set, the scanner falls back to the filesystem's last-modified time (`mtime`) for the `last_updated` field of any untracked file, and each document record gains a `tracked` boolean so downstream consumers can tell which source produced the timestamp. Default: off.
- `--min-priority {low,medium,high}` — Filter the returned doc list to records at or above the given priority (v2). Default: `low` (pass-through). `medium` drops low-priority docs; `high` keeps only high-priority docs. The summary block recomputes against the filtered list so counts stay consistent.
- `--format {json,priority-digest}` — Output format (v2). Default: `json` (full record schema, unchanged from v1 except for the two new fields per doc). `priority-digest` emits a concise Markdown digest suitable for weekly review — one H2 per non-empty priority bucket and a single-line summary per doc, with no full commit listings.
- `--output` — Write results to JSON file (default: print to stdout)

**When to use `--include-untracked`.** The default mode reads timestamps from `git log`, which is correct and reproducible but blind to files that haven't been committed yet. On a working branch where you've just added a new doc, the default scan silently skips it. Turn this flag on during drafting to include those files; turn it off for release-time audits where only committed state matters.

**The weekly-rhythm recipe (recommended).** The v2 flags exist to support a low-friction weekly cadence:

```bash
python scripts/doc_freshness_scanner.py \
  --since "7 days ago" \
  --min-priority medium \
  --format priority-digest
```

This scans the last week of code changes, filters out low-priority docs (ones with little distinctive content and few inbound references), and prints a short Markdown digest. Read the digest, act on the top two or three, and move on. The idea is to turn "spend an hour reading the full JSON" into "skim a digest for a minute, update one or two docs, done" — and come back next week. See MS-DES-0009 for the design rationale behind this flow.

## JSON output structure

The scanner outputs JSON with this structure:

```json
{
  "scan_date": "2026-04-13",
  "docs_path": "docs/",
  "since": "2026-03-13",
  "documents": [
    {
      "path": "docs/getting-started.md",
      "tracked": true,
      "last_updated": "2026-02-15",
      "days_since_update": 57,
      "status": "likely_stale",
      "related_code_changes": [
        {
          "hash": "abc1234",
          "date": "2026-04-01",
          "subject": "refactor auth module",
          "files": ["src/auth.py"],
          "matched_topics": ["src/auth.py"]
        }
      ],
      "matched_topics": ["auth", "config.json"],
      "recommendation": "Review — related code changed 12 days ago but doc hasn't been updated in 57 days",
      "importance_score": 0.79,
      "priority": "high"
    }
  ],
  "summary": {
    "total_docs": 10,
    "fresh": 6,
    "possibly_stale": 2,
    "likely_stale": 2,
    "priority_counts": {
      "high": 2,
      "medium": 6,
      "low": 2
    }
  }
}
```

**v2 additions on each record:**

- `importance_score` — Float in `[0.0, 1.0]`. Continuous score; use it if you want finer-grained ordering than the three-bucket priority.
- `priority` — One of `"low"`, `"medium"`, `"high"`. Discretized for stable filtering and to avoid false-precision "rank 3 vs rank 4" misreads. See MS-DES-0009.

## Limitations and considerations

- **Path-overlap matching has blind spots** — If a doc describes a concept without naming any file or directory path, no commits will match and the doc will always classify as `fresh`. This is a deliberate tradeoff (see `docs/design/doc-freshness-relevance-filter.md`). Prose-only docs that describe code areas indirectly should be spot-checked by humans.
- **Renames not followed** — A file rename splits git history; `--follow` would stitch it back together but is not yet implemented. A doc that references the old path will stop matching once the file moves.
- **Binary files ignored** — The scanner works only with `.md` files; other documentation formats (RST, AsciiDoc, HTML, PDFs) are not scanned.
- **Merge commits excluded** — The scanner filters out merge commits to focus on actual code changes.
- **Docs-only commits** — Commits that only touch documentation files are excluded from the scan, so pure documentation updates don't trigger "staleness" flags.
- **Date precision** — The scanner uses day-level precision (YYYY-MM-DD). Time-of-day is not considered in comparisons.
- **Untracked docs are skipped by default** — Use `--include-untracked` during drafting if you want in-flight files scanned; those entries will appear with `tracked: false` and a filesystem `mtime`-derived `last_updated`.

