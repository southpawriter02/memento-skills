# Design note — tightening the `doc-freshness` relevance filter

> **Status:** Accepted, 2026-04-13
> **Owner:** Ryan (tech-writing skill suite)
> **Scope change:** `skills/doc-freshness/scripts/doc_freshness_scanner.py`
> **Referenced by:** `docs/phase-1-retrospective.md` § Phase 2 candidates, item 1

## Problem

On pipeline run #2 (recorded in `docs/.doc-pipeline-log.json`, 2026-04-13), the
freshness scanner flagged `docs/agent_execution_flow.md` and
`docs/llm_tool_call_compatibility.md` as `possibly_stale`. Both flags were
false positives. The trigger was commit `c41aa41` — a meta-commit that added
the tech-writing skill suite under `skills/` — with the subject line
"Added new skills relating to tech writing."

Neither design doc references `skills/` or anything that commit touched. So
why did the scanner match?

## Root cause

Two pieces of `find_related_commits` are too permissive:

1. **Topic extraction is too broad.** `extract_topics_from_doc` pulls every
   backtick-quoted term and every heading into the topic set, lowercased. For
   design docs, that set ends up full of generic English words — "agent,"
   "skill," "tool," "overview," "summary." Any of those, substring-matched
   against a commit's file paths or subject line, fires.

2. **Commit-subject matching is unanchored substring matching.**
   `if topic in subject_lower:` matches "skill" in "**skill**s." That was the
   specific pathway that lit up both false positives, because both docs have
   headings containing the word "skill."

The bidirectional filepath test (`topic in filepath or filepath in topic`)
compounds the problem: a two-character topic like "io" will match any path
containing "io" (which is most of them).

## Goal

Flag a commit as related to a doc only when the commit's changed files
plausibly belong to the same code area the doc describes. Fewer flags
overall, at the cost of occasionally missing a commit whose relevance is
communicated only in the subject line.

This is the correct tradeoff: the scanner is input to human judgment, not a
gate. False positives make humans stop trusting the signal; false negatives
just mean a human has to catch the occasional drift themselves — which they
were already doing before the scanner existed.

## Design

Replace the current fuzzy substring heuristic with a **path-overlap** test.
Two new concepts:

### 1. Path references, not topics

Introduce `extract_path_references(content)` returning a set of normalized
paths the doc actually mentions. Sources:

- Inline code with path-looking content:
  `` `core/skill/gateway.py` ``, `` `docs/design/` ``, `` `skills/` ``
- File paths detected by the existing regex (already in the codebase).
- Markdown link targets that point at repo-relative paths:
  `[SkillGateway](../../core/skill/gateway.py)` → `core/skill/gateway.py`.

Normalization steps:

- Strip leading `./` and resolve `../` segments relative to the doc's own
  directory.
- Lowercase is **not** applied — paths are case-sensitive on many filesystems.
- Drop any reference shorter than 3 characters.

### 2. Directory-prefix matching

A commit is related to a doc if **at least one of the commit's changed files
is a descendant of at least one path the doc references**, using directory
prefix matching.

Rules:

- If the doc references a file path (`core/skill/gateway.py`), match
  commits that touched exactly that file OR any sibling file in its
  directory (`core/skill/*`).
- If the doc references a directory path (`core/skill/`), match any file
  under that directory.
- If the doc contains only bare module names with no path separator (e.g.,
  just `gateway`), skip — too ambiguous.

### 3. Commit-subject matching is dropped

No more `topic in subject_lower`. It was the loudest source of false
positives, and the path-overlap test subsumes the legitimate cases (a commit
that refactored `auth.py` will appear in the changed-files list regardless of
how its subject line is phrased).

## Backward compatibility

The output schema is unchanged. The `matched_topics` field is kept but now
reports **which doc-referenced paths matched the commit's files**, not which
lowercased terms matched a substring. Downstream consumers that read the
schema (currently: just the doc-pipeline orchestrator and the feedback log)
don't need to change.

The old `extract_topics_from_doc` function is kept but no longer called from
the matching path. We keep it for the `matched_topics` display fallback and
because it's occasionally useful for debugging.

## Testing

Add `skills/doc-freshness/scripts/test_relevance.py` with three cases:

1. **Regression case** — reconstruct the false positive: a doc that mentions
   "skill" and "agent" in headings, a commit that touched only
   `skills/new-thing/SKILL.md`. **Expected:** no match.
2. **True positive** — a doc that references `core/skill/gateway.py` and
   a commit that touched `core/skill/gateway.py`. **Expected:** match.
3. **Directory-level match** — a doc that references `core/skill/` and a
   commit that touched `core/skill/market.py`. **Expected:** match.

Tests use plain `assert` statements and are runnable via
`python test_relevance.py` — no pytest dependency.

## What this does not change

- The `fresh` / `possibly_stale` / `likely_stale` classification thresholds.
- The `--since` default of 30 days.
- The doc's last-modified source (still `git log`, still blind to untracked
  files — that's Phase 2 item 2).
- The scanner's behavior on docs that reference no paths: they will show as
  `fresh` with zero related changes, same as before.

## Known follow-ups

- **Whole-word subject matching (revisited).** If we start seeing legitimate
  cases being missed because a commit touched a directory the doc doesn't
  name but the subject line does, we could add a conservative word-boundary
  match (`\bgateway\b` in subject) on specific identifiers. Not doing that
  now — wait for evidence.
- **`git log --follow` for renames.** If a file gets renamed, the history
  splits. `--follow` would stitch it back together. Out of scope for this fix.
