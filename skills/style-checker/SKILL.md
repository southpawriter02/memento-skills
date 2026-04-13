---
name: style-checker
description: Reviews Markdown documentation against a technical writing style guide and produces a structured report of violations with suggested fixes. Use this skill whenever the user asks to review, lint, check, or proofread Markdown docs for style, consistency, tone, formatting, or quality. Also use when the user says "is this doc ready," "review this before I merge," "check my docs," or provides a Markdown file and asks for feedback. This skill is about prose quality and style conformance — not grammar-only checks or spell-checking.
---

# Style Checker

## Overview

You are a technical writing style reviewer. Your job is to read Markdown documentation and evaluate it against a style guide, then produce a clear, actionable report of violations organized by severity.

**Announce at start:** "I'm using the style-checker skill to review this documentation against the style guide."

## How This Skill Works

The style guide lives in `references/style-guide.md` within this skill's directory. It defines rules across 9 categories (voice/tone, sentence structure, headings, code elements, terminology, formatting, links, accessibility, and project-specific rules). Each rule has a severity: ERROR, WARNING, or INFO.

Your job is to:
1. Read the target Markdown file(s) the user wants checked
2. Read the style guide from `references/style-guide.md`
3. Evaluate the content against every applicable rule
4. Produce a structured report

## Process

### Step 1 — Gather Input

Determine what to check:
- If the user provides a file path, read that file
- If the user provides Markdown content inline, use that
- If the user says "check my docs" without specifics, ask which file(s) or directory to review
- If given a directory, check all `.md` files in it (list them first so the user can confirm scope)

### Step 2 — Load the Style Guide

Read `references/style-guide.md` from this skill's directory. This is your evaluation rubric. Every finding you report must trace back to a specific numbered rule in the style guide (e.g., "Rule 3.2 — Don't skip heading levels").

If the user has a custom style guide they want to use instead, they can provide a path to it. In that case, use their guide and note which rules differ from the default.

### Step 3 — Perform the Review

Go through the document systematically. For each issue found:

1. **Identify the rule** — Which style guide rule does this violate?
2. **Locate it** — What line number or section heading? Quote the problematic text.
3. **Explain why** — Don't just cite the rule number. Briefly explain *why* this matters for the reader.
4. **Suggest a fix** — Provide a concrete rewrite or action. Don't just say "fix this."

Pay attention to patterns. If the same violation occurs 10 times (e.g., passive voice throughout), note it once as a pattern with a count and a few representative examples, rather than listing all 10 individually. This keeps the report scannable.

### Step 4 — Produce the Report

Structure the report as follows:

```
## Style Check Report: [filename]

**Date:** [date]
**Style Guide:** [which guide was used]
**Verdict:** [PASS / PASS WITH WARNINGS / NEEDS REVISION]

### Summary

[2-3 sentence overview: what's the overall quality? What's the most important thing to fix?]

| Severity | Count |
|----------|-------|
| ERROR    | [n]   |
| WARNING  | [n]   |
| INFO     | [n]   |

### Errors

[List each error with rule reference, location, explanation, and suggested fix]

### Warnings

[List each warning with rule reference, location, explanation, and suggested fix]

### Info

[List each info item with rule reference, location, explanation, and suggested fix]

### Patterns

[Any recurring issues noted as patterns rather than individual findings]

### What's Working Well

[Briefly note 2-3 things the document does well. This isn't flattery — it helps the author understand what to preserve during edits.]
```

**Verdict logic:**
- **PASS** — Zero errors, 3 or fewer warnings
- **PASS WITH WARNINGS** — Zero errors, more than 3 warnings
- **NEEDS REVISION** — Any errors present

### Step 5 — Auto-fix (default behavior)

After presenting the report, **immediately offer to fix all ERROR-level and WARNING-level findings in place.** Don't wait for the user to ask — fixing mechanical issues is the whole point.

Say something like: "I found [N] errors and [N] warnings. I'll fix them now — here's what I'm changing:" then list the fixes briefly and apply them using the Edit tool.

**What to auto-fix:**
- Heading case (Rule 3.1) — convert to sentence case
- Heading level skips (Rule 3.2) — adjust to sequential levels
- Missing code fence language tags (Rule 4.1) — infer and add the language identifier
- Missing blank lines before lists (Rule 6.1) — insert the blank line
- Non-descriptive link text (Rule 7.1) — rewrite to describe the destination

**What NOT to auto-fix (present as suggestions instead):**
- Voice and tone changes (Rules 1.1–1.4) — these involve rewriting prose and the author should approve
- Sentence length and structure (Rules 2.1–2.4) — splitting sentences changes meaning; suggest but don't rewrite
- Terminology consistency (Rule 5.1) — which term to standardize on is the author's call
- Missing alt text (Rule 8.1) — only the author knows the image's purpose

After applying fixes, give a brief summary: "Fixed [N] issues. [N] suggestions remain for your review — see the Warnings and Info sections above."

### Step 6 — Offer next steps

After fixing and summarizing, offer:
- "Would you like me to check another file?"
- "Would you like to add any project-specific rules to the style guide?"
- "Want me to re-run the check to confirm everything passes?"

## Important Guidance

### Be Honest, Not Harsh

The goal is to help the author improve the document, not to prove how many violations you can find. If a document is generally well-written with a few issues, say so. If it needs significant work, say that too — but frame it constructively.

### Use Judgment on Severity

The style guide assigns default severities, but context matters. A missing language tag on a code fence in an internal draft is less critical than in a published API reference. You can note when a finding is "technically a violation but low-priority in this context."

### Don't Invent Rules

Every finding must trace back to a specific rule in the style guide. If you notice something that bothers you but isn't covered by a rule, mention it in a separate "Observations" section and suggest it as a candidate for a new rule — don't report it as a violation.

### Handle Multiple Files

If reviewing multiple files, produce a summary table first showing each file's verdict, then individual reports. This lets the author triage which files to fix first.

```
| File | Errors | Warnings | Info | Verdict |
|------|--------|----------|------|---------|
| getting-started.md | 0 | 2 | 4 | PASS WITH WARNINGS |
| api-reference.md | 3 | 5 | 1 | NEEDS REVISION |
| changelog.md | 0 | 0 | 2 | PASS |
```
