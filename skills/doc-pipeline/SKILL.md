---
name: doc-pipeline
description: Orchestrates an end-to-end documentation workflow — scans for staleness, generates drafts, writes changelogs, drafts release notes, and enforces style. Use this skill when the user says "update all the docs," "prepare docs for this release," "run the full doc pipeline," "docs are out of date — fix everything," or wants a comprehensive documentation pass across a project. Also use when a release is being prepared and docs need to be brought up to date as part of that process. This is the skill to reach for when multiple documentation tasks need to happen in sequence, not just one.
---

# Doc pipeline

## Overview

You are a documentation pipeline orchestrator. Your job is to run a multi-step documentation workflow that brings a project's docs up to date. You coordinate the work that the other doc skills handle individually — freshness scanning, generation, changelogs, release notes, and style checking — but run them as a unified sequence with a single summary at the end.

**Announce at start:** "I'm using the doc-pipeline skill to run a full documentation pass on your project."

## Why this skill exists

Individual doc skills solve individual problems. But a real documentation update — especially around a release — requires multiple steps in a specific order, where the output of one step feeds the next. Running `doc-freshness` tells you what's stale, which tells `doc-generator` what to regenerate, which feeds into `style-checker` for quality assurance. This skill encodes that sequence so you don't have to coordinate it manually.

## Important constraint

This skill **cannot directly invoke other skills.** Each step below describes what to do inline, referencing the logic and scripts from the other skills. If a step mentions a script (like `doc_freshness_scanner.py`), run it directly — don't try to call `execute_skill`.

The scripts you may need are located as siblings to this skill's directory:

- `../doc-freshness/scripts/doc_freshness_scanner.py`
- `../changelog-writer/scripts/git_log_parser.py`
- `../doc-generator/scripts/extract_signatures.py`

If a script isn't available, the step instructions include a fallback approach.

## Process

### Step 1 — Scope the pipeline

Before running anything, determine:

1. **Repository path:** Where is the code?
2. **Docs path:** Where do the docs live? (default: `docs/`)
3. **Source path:** Where does the source code live? (for doc generation)
4. **Release context:** Is this tied to a specific release/tag? Or a general freshness pass?
5. **Which steps to run:** The full pipeline or a subset?

Present the plan to the user before executing:

> "Here's what I'll do:
> 1. Scan docs for staleness (comparing against code changes since [date/tag])
> 2. Regenerate docs for any stale or missing components
> 3. Generate a changelog entry for [version/range]
> 4. Draft release notes from the changelog
> 5. Run the style checker on all generated and updated content
>
> Want me to proceed with all steps, or skip any?"

### Step 2 — Scan for staleness

Run the freshness scanner:

```bash
python ../doc-freshness/scripts/doc_freshness_scanner.py \
  --repo-path <repo> \
  --docs-path <docs> \
  --since <date-or-tag>
```

Parse the JSON output. Classify each document:
- **Likely stale** → Candidate for regeneration (Step 3)
- **Possibly stale** → Flag for review but don't auto-regenerate
- **Fresh** → Skip

**Fallback:** If the script isn't available, use `git log` to find docs that haven't been updated recently while related source files have changed.

Report to user: "Found N docs total — X fresh, Y possibly stale, Z likely stale. Proceeding to update the stale ones."

### Step 3 — Generate or update stale docs

For each likely-stale document:

1. Read the existing doc to understand its structure and scope
2. Identify which source files it covers (from the freshness scan's `matched_topics` and `related_code_changes`)
3. Run the signature extractor if the doc is an API reference:
   ```bash
   python ../doc-generator/scripts/extract_signatures.py <source-path>
   ```
4. Update the existing doc rather than replacing it wholesale — preserve the author's voice and any hand-written sections
5. Mark changes clearly with comments: `<!-- Updated by doc-pipeline: [date] -->`

For **missing docs** (source modules with no corresponding documentation):
- Generate a first draft using the doc-generator approach
- Flag it prominently: "This is a new auto-generated doc that needs review."

**Principle:** Be conservative with updates. Change what the code changes demand, but don't rewrite prose that's still accurate just because you can.

### Step 4 — Generate changelog

If the pipeline is tied to a release:

Run the Git log parser:

```bash
python ../changelog-writer/scripts/git_log_parser.py \
  --repo-path <repo> \
  [--from-tag <previous-tag>] \
  [--to-tag <current-tag>]
```

Categorize commits following Keep a Changelog conventions (see the changelog-writer skill for the full categorization logic). Write a changelog entry.

If a `CHANGELOG.md` exists, prepend the new entry. If not, create one.

**Fallback:** Run `git log --oneline --no-merges [range]` and categorize manually.

### Step 5 — Draft release notes

Transform the changelog entry into user-facing release notes:

1. Determine the audience (ask the user if not obvious)
2. Prioritize: breaking changes and new features first, bugfixes second, internal changes last
3. Write an overview paragraph (the "elevator pitch" for this release)
4. Expand the top 2-3 changes into short highlight paragraphs
5. Include migration notes if there are breaking changes

Reference the release-notes skill's `references/tone-examples.md` for audience-calibrated examples if you need calibration.

### Step 6 — Style check

Run through every file that was generated or modified in steps 2-5. For each file, apply the style guide rules from `../style-checker/references/style-guide.md`:

1. Read the style guide
2. Review each file against the rules
3. Auto-fix mechanical issues (heading case, code fence language tags, missing blank lines before lists)
4. Note but don't auto-fix judgment calls (voice, sentence structure, terminology)

### Step 7 — Present the summary

Produce a pipeline run report:

```markdown
## Doc pipeline summary

**Date:** [date]
**Scope:** [repo name], [tag range or date range]

### Freshness scan

| Status | Count |
|--------|-------|
| Fresh | N |
| Possibly stale | N |
| Likely stale | N |

### Documents updated

| File | Action | Notes |
|------|--------|-------|
| docs/api-reference.md | Updated | Synced with new auth module changes |
| docs/getting-started.md | No changes | Still fresh |
| docs/config-guide.md | Created | New — needs human review |

### Changelog

[Written / appended to CHANGELOG.md]

### Release notes

[Drafted — see release-notes.md]

### Style check

| File | Errors fixed | Warnings remaining |
|------|-------------|-------------------|
| docs/api-reference.md | 2 | 1 |
| docs/config-guide.md | 0 | 3 |
| CHANGELOG.md | 1 | 0 |

### Items needing human review

- [ ] `docs/config-guide.md` — newly generated, needs voice and accuracy review
- [ ] `docs/api-reference.md` — 1 warning remaining: terminology inconsistency
- [ ] Release notes — verify tone matches target audience
```

Offer next steps:
- "Want me to fix the remaining warnings?"
- "Should I commit these changes to a new branch?"
- "Want me to re-run any specific step?"

## When to run a partial pipeline

Not every situation needs all 7 steps. Common partial runs:

| Situation | Steps to run |
|-----------|-------------|
| "Just check what's stale" | Steps 1-2 only |
| "We're cutting a release" | All steps |
| "Generate docs for this new module" | Steps 1, 3, 6 |
| "Update the changelog" | Steps 1, 4 only |
| "Style-check everything" | Steps 1, 6 only |

Suggest the appropriate subset based on context. Don't run 7 steps when 2 will do.

## Feedback log

After each pipeline run, record a brief entry in `docs/.doc-pipeline-log.json` (create it if it doesn't exist):

```json
{
  "runs": [
    {
      "date": "2026-04-13",
      "scope": "v0.2.0 release",
      "docs_scanned": 6,
      "docs_updated": 2,
      "docs_created": 1,
      "style_errors_fixed": 3,
      "notes": "config-guide.md was newly generated and needed significant human edits"
    }
  ]
}
```

This log serves two purposes: it creates an audit trail of documentation changes, and it's the beginning of the feedback loop we'll build out later to track which generated content holds up and which consistently needs heavy editing.
