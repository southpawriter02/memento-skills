# Phase 1 retrospective — tech-writing skill suite

> **Date:** 2026-04-13
> **Phase 1 window:** 2026-04-13 (single-day sprint, compressed)
> **Author:** Ryan Goodrich (with Claude)
> **Status:** Phase 1 closed. Phase 2 candidates captured in the final section.

## Scope recap

Phase 1 of [`tech-writing-adaptation-plan.md`](./tech-writing-adaptation-plan.md) set out to build six Cowork-format skills for technical-writing work, shake them out on real input, and produce a candidate list of improvements for Phase 2. The six skills:

| Skill | Kind | Purpose |
|-------|------|---------|
| `style-checker` | Knowledge | Reviews Markdown against a 30-rule style guide; auto-fixes mechanical issues. |
| `changelog-writer` | Hybrid (knowledge + script) | Parses conventional-commit git history; produces Keep-a-Changelog output. |
| `doc-freshness` | Hybrid | Scans a `docs/` tree against git history; classifies as fresh / possibly-stale / likely-stale. |
| `doc-generator` | Hybrid | Extracts Python / C# / TypeScript signatures; produces first-pass API reference drafts. |
| `release-notes` | Knowledge | Drafts audience-calibrated release notes from a changelog. |
| `doc-pipeline` | Orchestrator | Runs the other five in sequence; maintains a feedback log. |

## Success criteria from the plan

The plan specified three exit conditions for Phase 1. Here's where each stands:

| Criterion | Status | Evidence |
|-----------|--------|----------|
| 2+ "create → test → review → improve" cycles per skill | **Partial** — Every skill was built and exercised at least once against real input. `style-checker` and `changelog-writer` saw full cycles including revisions (auto-fix added to `style-checker` after first review; `changelog-writer` tested against both all-history and `--from-tag` paths). The other four saw a single build-and-exercise cycle each. | See git log; see `docs/.doc-pipeline-log.json`. |
| Written log of wins and frustrations | **Complete** | This document plus `docs/.doc-pipeline-log.json`. |
| 3+ changes identified for Phase 2 | **Complete** — Six candidates captured below. | Final section. |

Realistically we ran a compressed version of Phase 1 — one day instead of the planned multi-week rollout. Calling this "Phase 1a" and treating Phase 1b as any further hardening we do before Phase 2 starts is a reasonable framing. The criterion we didn't fully hit (two full cycles per skill) is the natural follow-up.

## What we actually ran

Three real exercises against external input, in chronological order:

### Exercise 1 — full pipeline against the repo itself (run #1)

**Scope:** no pre-existing `CHANGELOG.md` or release notes. All history through the `v0.2.0` release treated as one window.

**Outcome:**

- Freshness scan: 6 docs, all fresh. Nothing to remediate.
- Changelog generation: ran against 4 commits, none in conventional-commit format. The script's git-log parsing was correct; categorization was hand-done.
- Release notes: drafted `docs/release-notes-v0.2.0.md` at developer-audience tone from the generated changelog.
- Style check: both new files passed with zero ERRORs.

**Notable friction:** untracked files were invisible to the freshness scanner (the tool reads `git log` timestamps). This is correct behavior for a tracked-file tool, but was surprising on a work-in-progress branch. Resolved after the user committed the new work.

### Exercise 2 — full pipeline after commit (run #2)

**Scope:** same repo, scan since the `v0.2.0` tag.

**Outcome:**

- Freshness scan: 8 docs. Two flagged as `possibly_stale`.
- **Finding:** both flags were false positives. The scanner treats any commit newer than the doc's last-modified timestamp as a "related code change," so the meta-commit that added `skills/` tripped two unrelated design docs (`agent_execution_flow.md`, `llm_tool_call_compatibility.md`).
- Changelog: appended an `[Unreleased]` section. The `--from-tag` path worked on first try.
- No new release notes (no version cut).

**Win:** two back-to-back pipeline runs appended cleanly to the log without state leaking between runs. The "call sibling scripts directly" workaround for the no-skill-to-skill-invocation constraint is durable.

### Exercise 3 — style-checker on an external fixture

**Input:** a user-uploaded Finder column-view reference doc (`columnviewwidth.mdx`, 283 lines).

**Findings caught:** 3 errors, 3 warnings, 2 info items. The three errors were all mechanical (sentence case, code fence language tags, blank lines before lists) and were auto-fixed. The warnings were judgment calls and left as suggestions.

**Win:** the rule-by-rule walk caught exactly what a careful human reviewer would catch on a first pass. Sentence-case conversion across 22 headings is tedious enough by hand that the skill paid for itself on a single document.

**Gaps surfaced:**

- No rule for trailing colons on headings.
- No rule for MDX-specific concerns (embedded JSX, front-matter).
- Rule 1.1 (second person) misfires on reference-style docs that legitimately have no direct address.

### Exercise 4 — doc-generator on `core/skill/gateway.py`

**Input:** 503-line Python module, 1 public class, 7 methods.

**Outcome:** clean extraction of signatures, docstrings, decorators, async/property flags. Produced [`docs/api/skill-gateway.md`](./api/skill-gateway.md) as a first-pass reference doc.

**Win:** the AST path is reliable. All 7 methods came through with correct parameter lists, type annotations (where present), and decorator info. The empty-top-level-functions case was handled cleanly.

**Gap surfaced:** most of this module's docstrings are in Chinese. The extractor preserves them verbatim — as it should — but that means English-first generated docs need a translation pass. Not a skill bug; a workflow gap.

## What worked

Three patterns are worth keeping:

- **Hybrid skills (script + prose judgment)** hit the right level of automation. The scripts handle the tedious parts (git log parsing, AST walking, path-matching) and the skill's narrative guidance handles the judgment (categorization, prose tone, severity calibration). Neither alone would be as useful.
- **The "mechanical vs. judgment-call" split in `style-checker`'s Step 5** held up. I genuinely didn't want to auto-flip the numbered list to bullets in the MDX exercise without asking — the rule says "semantic change, suggest instead," and that's the right call.
- **The feedback log (`docs/.doc-pipeline-log.json`)** is already earning its keep. After two runs we have a concrete false-positive pattern documented; after ten runs we'll have something resembling a utility score.

## What didn't

Three things to fix or accept:

- **False positives in `doc-freshness`.** The "related code changes" heuristic is too loose. A commit that only touches `skills/` shouldn't flag a design doc about `core/`. The fix is to filter related commits by path overlap with directories the doc references (via its Markdown links or inline-code paths).
- **Categorization is still manual for non-conventional-commit repos.** `changelog-writer`'s script saves the parsing, but when commits read like "update readme" or "Added new skills relating to tech writing," the categorization falls back to me reading the release body. On a repo that uses conventional commits religiously, the skill would be close to zero-effort; on this one it's maybe 60% saved.
- **`style-checker` has no auto-fix script.** Step 5 works by having the agent apply Edit operations following the rules, which is fine for a single document but won't scale to a directory of 50 Markdown files. A real script implementation (probably using a Markdown AST parser like `mistune` or `markdown-it-py`) would turn this from "nice to have" into "run it in CI."

## Phase 2 candidate changes

Six candidates, in rough effort order:

1. **Tighten `doc-freshness` relevance heuristic.** Filter "related code changes" by path overlap with the doc's referenced modules (Markdown links and inline-code paths), not by any commit that touches the repo. ~half day including a unit test. Highest-value fix because the false positive is already documented.

2. **Add `--include-untracked` flag to `doc-freshness`.** Lets the scanner consider untracked files using filesystem mtime as a fallback. Small, useful on work-in-progress branches. ~1 hour.

3. **Add trailing-colon and MDX-front-matter rules to the style guide.** Two new rules (Rule 3.6, Rule 9.1-equivalent). ~1 hour writing plus whatever time it takes to shake them out on real input.

4. **Build an auto-fix script for `style-checker`.** Use `markdown-it-py` or similar to parse, transform, and re-serialize. Starts with the four mechanical rules currently in Step 5. ~1 day. Biggest leverage long-term because it turns the skill into a CI-ready linter.

5. **Add an optional translation pass to `doc-generator`.** When a docstring is in a non-target language, call an LLM to translate it (with the original preserved as a comment for review). ~half day. Would have saved manual work on the `SkillGateway` doc.

6. **Start the Phase 2 retrieval layer (BM25 index over skill library).** The adaptation plan's headline Phase 2 item. ~1 week. Does not block the above; the above make it more valuable when it ships.

## Decision for next step

Recommendation: do item 1 (the `doc-freshness` fix) first. It's small, the bug is documented, and shipping it closes the loop on the most concrete piece of evidence Phase 1 produced. Items 2-3 can ride along in the same commit. Items 4-5 are multi-hour projects worth scheduling individually. Item 6 is a project in its own right.

## Artifacts produced in Phase 1

| File | Purpose |
|------|---------|
| `docs/tech-writing-adaptation-plan.md` | Two-phase plan. |
| `CHANGELOG.md` | Keep-a-Changelog history for the repo. |
| `docs/release-notes-v0.2.0.md` | Developer-audience v0.2.0 release notes. |
| `docs/api/skill-gateway.md` | First-pass API reference for `SkillGateway`. |
| `docs/.doc-pipeline-log.json` | Pipeline run log (2 entries). |
| `docs/phase-1-retrospective.md` | This document. |
| `test-fixtures/columnviewwidth.mdx` | Style-checker fixture (post-fix). |
| `skills/style-checker/` | Skill + 30-rule style guide. |
| `skills/changelog-writer/` | Skill + git-log parser script. |
| `skills/doc-freshness/` | Skill + freshness scanner script. |
| `skills/doc-generator/` | Skill + multi-language signature extractor. |
| `skills/release-notes/` | Skill + tone examples. |
| `skills/doc-pipeline/` | Orchestrator skill. |
