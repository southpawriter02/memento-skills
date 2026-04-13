---
name: doc-freshness
description: Scan documentation against recent code changes to identify potentially stale content. Triggers on requests like "stale docs", "outdated documentation", "what docs need updating", "doc freshness", "are my docs up to date", etc.
---

## Overview

Documentation freshness is a persistent challenge: features get built, APIs change, configurations evolve—but the docs that describe them often lag behind. This skill combines an automated scanner with agent judgment to identify which documentation might be out of date and needs review.

The process works in stages:

1. **Determine scope** — Which repository and documentation directory to scan?
2. **Run the scanner** — Extract topics from markdown docs, cross-reference against Git history to find related code changes
3. **Interpret results** — Analyze the scanner output to understand what changed and why a doc might be stale
4. **Present findings** — Show a prioritized report highlighting the docs most likely to need updates
5. **Offer next steps** — Help take action: update the doc, flag an issue, create a task

## How the scanner works

The scanner (`scripts/doc_freshness_scanner.py`) performs these steps:

1. **Topic extraction** — For each markdown document, it extracts "topics":
   - Terms in backticks (e.g., `config.json`, `auth` module)
   - Heading text (from # ## ### headings)
   - File paths mentioned in the doc (e.g., src/auth.py, docs/api.md)

2. **Code change detection** — It queries Git for commits touching non-documentation code files since a specified date (default: 30 days ago). Each commit records which files changed and the commit subject.

3. **Cross-referencing** — For each document, the scanner checks:
   - Do any recent commits touch files that the doc mentions?
   - Do commit subjects contain topics the doc references?
   - Build a list of "related code changes" for each doc

4. **Freshness classification** — Based on the last update date of the doc and the most recent related code change:
   - **fresh**: No related code changes found, OR doc was updated after all related changes
   - **possibly_stale**: Related code changed, but doc was updated within 30 days of that change
   - **likely_stale**: Related code changed and doc hasn't been updated within 30 days of that change

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
  --output results.json
```

**Arguments:**

- `--repo-path` — Path to Git repository (default: current directory)
- `--docs-path` — Path to docs directory, relative to repo (default: `docs/`)
- `--since` — Date filter for code changes (ISO 8601, e.g. `2026-03-13`; default: 30 days ago)
- `--output` — Write results to JSON file (default: print to stdout)

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
      "recommendation": "Review — related code changed 12 days ago but doc hasn't been updated in 57 days"
    }
  ],
  "summary": {
    "total_docs": 10,
    "fresh": 6,
    "possibly_stale": 2,
    "likely_stale": 2
  }
}
```

## Limitations and considerations

- **Topic matching is heuristic** — The scanner looks for file paths and terms mentioned in docs, but may miss implicit references or architectural changes not reflected in filenames.
- **Binary files ignored** — The scanner works only with `.md` files; other documentation formats (RST, AsciiDoc, HTML, PDFs) are not scanned.
- **Merge commits excluded** — The scanner filters out merge commits to focus on actual code changes.
- **Docs-only commits** — Commits that only touch documentation files are excluded from the scan, so pure documentation updates don't trigger "staleness" flags.
- **Date precision** — The scanner uses day-level precision (YYYY-MM-DD). Time-of-day is not considered in comparisons.

