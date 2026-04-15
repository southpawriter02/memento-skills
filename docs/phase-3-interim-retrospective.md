# Phase 3 interim retrospective — three closures of six candidates

> **Date:** 2026-04-14
> **Phase 3 window (so far):** 2026-04-14 (single working day, continuing after the v0.3.0 cut the same morning)
> **Author:** Ryan Goodrich (with Claude)
> **Status:** Interim. Three of the six Phase 2 candidates are closed; three remain open. This document exists so a future session can rehydrate project state from a single file read rather than from chat history.

## Why this is an interim doc rather than a phase-close retrospective

[Phase 2](./phase-2-retrospective.md) enumerated six Phase 3 candidates (§"Phase 3 candidate changes"). Rather than close Phase 3 as a whole sprint the way Phase 2 was, the candidates are being picked off individually inside Cowork sessions. This is the first retrospective written mid-Phase. It covers what shipped between the v0.3.0 release cut (run #9) and run #13 of the pipeline log, and captures the state needed to resume the sequence in a new session without chat context.

## Scope recap

Three candidates shipped; three remain. The original effort-ordered list from Phase 2 is reproduced below with current status and the run where the work was verified:

| # | Candidate | Status | Design spec | Pipeline run |
|---|-----------|--------|-------------|--------------|
| 1 | Widen `PROPER_NOUNS` + teach Rule 3.1 sentence-boundary capitalization | **Shipped** | [`rule-3-1-proper-nouns-and-sentence-boundaries.md`](./design/rule-3-1-proper-nouns-and-sentence-boundaries.md) (MS-DES-0007) | Run #13 |
| 2 | README baseline-cleanup pass | **Shipped as part of #1** | — (no separate spec — mechanical consequence of #1) | Run #13 |
| 3 | Pipeline-log utility-scoring analyzer | **Shipped** | [`pipeline-log-analyzer.md`](./design/pipeline-log-analyzer.md) (MS-DES-0006) | Run #12 |
| 4 | Remote BM25 strategy for Skill Market fusion | Open | — | — |
| 5 | Auto-release checklist script (version-drift checker) | **Shipped** | [`release-checklist-script.md`](./design/release-checklist-script.md) (MS-DES-0005) | Run #11 |
| 6 | Phase 1 criterion closure: `doc-generator` and `release-notes` second cycles on non-trivial fixtures | Open | — | — |

Candidate #2 was originally sized as its own hour of cleanup. In practice it became the natural verification step for candidate #1, since the two README bugs (`OpenClaw` allowlist gap and `One Repo. One Learning Agent.` sentence-boundary failure) were exactly what was blocking the cleanup. Closing #1 made #2 a single `style_autofix.py README.md` command. No separate design spec was warranted.

## What we actually ran

### Candidate 5 — release-version drift checker (run #11, MS-DES-0005)

**Problem:** the v0.3.0 cut (run #9) had ten canonical version references to bump across nine files. No tool existed to verify the ten references stayed in sync; missing one would ship a mismatch.

**Fix:** `build_scripts/check_release_versions.py` reads the canonical version from `pyproject.toml [project].version`, walks a declarative `CALL_SITES` tuple covering all ten known references, and exits `0` on clean / `1` on drift / `2` on usage error. Stdlib-only (`tomllib` from 3.11+), human-readable or `--json` output. Covered by 12 unit tests (plain `unittest`, no pytest, isolated tmp-dir fixtures).

**Design note:** the ten call sites are hard-coded in a tuple rather than discovered via grep because the point of the checker is "the list is the spec" — adding a new fallback requires editing the tuple, which is also the governance surface. Discovery-by-grep would fail open the first time a developer added an unrelated occurrence of the version string.

### Candidate 3 — pipeline-log utility-scoring analyzer (run #12, MS-DES-0006)

**Problem:** after eleven structured runs of `docs/.doc-pipeline-log.json`, there was enough data to compute per-skill utility metrics — but no tool did. The log was a narrative, not a measurement.

**Fix:** `skills/doc-pipeline/scripts/analyze_pipeline_log.py` reads the log and emits a per-skill scorecard in three formats (human / JSON / Markdown). Attribution uses six declarative rules (one per underlying skill) keyed in a single `ATTRIBUTION_RULES` dict, so "why did run #N count toward skill X?" is answerable from one function body. Covered by 48 unit tests across four classes.

**Story:** the first end-to-end run against the real log surfaced a false positive — `release_cut_runs` reported `[9, 11]` because run #11's scope contained "release-version drift checker," which substring-matched `"release"`. The regex was tightened to require either a version literal directly followed by `release` (e.g. `v0.3.0 release`) or the exact phrase `release cut`. A regression test (`test_release_cut_rejects_incidental_release_mentions`) locks the rejection against three specific decoy strings. The lesson lives in MS-DES-0006 §Overall metrics.

**Baseline produced:** [MS-ANA-0001](./analysis/pipeline-log-baseline-2026-04-14.md). Captures the 11-run scorecard with interpretation notes on the bursty log window (77 runs/week is a two-calendar-day artifact), midway docs-first adoption, and the note-only attribution of run #8.

### Candidate 1 — rule 3.1 sentence-case hardening (run #13, MS-DES-0007)

**Problem:** Phase 2 surfaced two concrete `style_autofix.py` failure modes (documented in phase-2-retrospective.md §"Frictions"). Together they made it unsafe to apply the fixer to `README.md`, which held 22 Rule-3.1 findings — the largest tracked piece of documentation debt.

**Fix:** two targeted changes in `skills/style-checker/scripts/style_autofix.py`.

1. `PROPER_NOUNS` widened from ~30 to ~60 entries, organized with category comments. Added `OpenClaw`, `SQLite`, `PostgreSQL`, `MySQL`, `iOS`, `Flet`, `Briefcase`, `Pydantic`, `SQLAlchemy`, and the acronym block (`API`, `CLI`, `SDK`, `UI`, `IDE`, `GUI`, `OSS`, `BSD`, `MIT`, `TLS`, `HTTP`, `HTTPS`, `URL`, `AST`, `NFKC`, `RRF`).
2. `_sentence_case_heading` now threads an `at_sentence_start` state variable that flips after any token whose trailing punctuation is exactly `.`, `!`, or `?`. Ellipses (length-3 trailing) and technical identifiers (caught by the existing `_is_technical_identifier` helper) do not flip state. The rewrite adds one bool of state and one 10-line helper — explicitly not a rewrite of the sentence-case pass.

**Scope discipline:** three alternatives rejected in the design spec and worth not re-litigating: (A) extracting `PROPER_NOUNS` to a config file, (B) multi-word proper nouns via tokenizer look-ahead, (C) plug-in ML sentence-boundary detector. The common thread: at the repo's current size, PR-based governance of a ~60-entry dict, a backtick-wrap escape hatch for multi-word cases, and a 10-line regex helper all dominate the fancier alternatives.

**Verification:** 12 new unit tests (45 total, no regressions), single `style_autofix.py README.md` pass produced 21 heading fixes, `--check` now reports clean. Baseline re-captured at [MS-ANA-0002](./analysis/pipeline-log-baseline-2026-04-14-readme-swept.md).

## Metrics delta between phase 2 close (run #9) and run #13

| Metric | At run #9 (v0.3.0 cut) | At run #13 (now) | Delta |
| :----- | --------------------: | ---------------: | ----: |
| Total pipeline runs | 9 | 13 | +4 |
| Docs-first discipline rate | ~55% (pre-MS-DES-NNNN) | 62% | +7pp |
| `style-checker` total errors fixed | 20 | 41 | +21 |
| README Rule-3.1 backlog | 22 findings | 0 findings | −22 |
| Design specs shipped | MS-DES-0001 … MS-DES-0004 | + MS-DES-0005, 0006, 0007 | +3 |
| Baseline reports | 0 | 2 (MS-ANA-0001, MS-ANA-0002) | +2 |

The docs-first rate jump reflects Phase 3's convention of writing a numbered design spec before touching code. All three shipped candidates followed MS-DES-NNNN before any implementation.

## Follow-ups surfaced in phase 3 (not worth their own specs yet)

- **Analyzer `current_warnings_backlog` accessor quirk.** `analyze_pipeline_log.py:317-323` returns the most recent **non-zero** `style_warnings_remaining`, so run #13's explicit `0` is skipped and the post-sweep headline still reads "backlog: 22" even though the README is clean. Fix is a ~30-minute switch to a `backlog_snapshot: {count, source}` object + most-recent-present semantics. Waiting for a second reason to touch the file before spending an MS-DES number on it.
- **Style guide doesn't follow its own rules.** `skills/style-checker/references/style-guide.md` has 48 Rule-3.1 findings (45 title-case headings + 3 demonstration strings inside `**Bad:**` examples). The headings are a genuine debt; the demonstration strings are intentional. Would be a 15-minute meta-fix (apply the autofixer to itself) except for the need to preserve the `**Bad:**` demonstrations verbatim, which means the fixer would need a no-fix marker inside those blocks. Not urgent.
- **Spec-to-retro link density.** Phase 2's retrospective table links each candidate to its design spec and pipeline run. Phase 3 is accumulating the same shape but without a sprint-end moment to write the retrospective. This interim doc is an attempt to not let that state go stale.
- **The autofixer's own limitations, as revealed by this retrospective.** Writing this document surfaced three autofixer edge cases worth collecting before they become their own MS-DES: (a) "Phase 2" / "Phase 3" as project-phase references get lowercased mid-heading because `Phase` is a common noun — probably correct behavior, but an argument could be made for a configurable project-phase allowlist; (b) multi-word product names like `Skill Market` get partially lowercased because the single-token PROPER_NOUNS lookup can't span tokens — same root cause as the MS-DES-0007 alternative B rejection, escape hatch is `` `Skill Market` `` in backticks; (c) abbreviation periods like `vs.`, `etc.`, `e.g.`, `i.e.` falsely trigger `_ends_sentence` state flips, which means headings containing `vs.` can over-capitalize the next token. The first two are documented edge cases; the third (`vs.`) is a genuine bug to fix in the next Rule 3.1 touch — an abbreviations allowlist checked before the single-terminator test would close it.

## Remaining phase 2 retrospective candidates

Three of six shipped. Three open:

### Candidate 4 — remote BM25 strategy for skill-market fusion (~1 week)

**What it is:** the current RRF fusion in `MultiRecall._rerank_candidates` fuses local-BM25 with local-vector. The Skill Market's remote recall is a separate tier. A remote BM25 index on the Market side would let the RRF framework fuse three lists while honoring the local-before-remote tier rule.

**Why it's still open:** this is the only Phase 2 retrospective candidate sized larger than a single-day slot. It needs Market-side schema changes, which means coordinating with whatever owns the Market today. An MS-DES-0008 would be the right shape but the design question "does the Market have a BM25 index surface?" is the blocker before writing it.

### Candidate 6 — phase 1 criterion closure (~half day each)

**What it is:** `doc-generator` and `release-notes` both hit two cycles in Phase 2 on small inputs (one Python module; one-release CHANGELOG). A genuine "2+ cycles with revisions" pass would run each against a larger input and log the findings.

**Why it's still open:** not time-pressured. It's a bookkeeping criterion from Phase 1, and the skills are working. Gets folded into regular doc work as non-trivial inputs arrive.

### Plus two newer candidates surfaced by this session's work

5 (already shipped — MS-DES-0005 closed candidate 5 above).

- **Candidate 7 — `changelog-writer` conventional-commit scope extraction (~half day).** Pull the `feat(scope):` prefix into a structured `scope` field on each parsed entry, so downstream categorizers can filter by module without relying on prose keywords. Smallest of the open items.
- **Candidate 8 — `doc-freshness` relevance filter v2 with BM25-weighted scoring (~full day).** Phase 2 item #2 retired the most obvious false-positive pattern via directory-prefix overlap. The next refinement is weighting retrieval-frequency of each doc using the BM25 index from MS-DES-0004 — high-traffic docs going stale is a bigger signal than low-traffic docs going stale. Needs its own MS-DES-0009.

## Decision for next step

Recommendation, in priority order for the next session:

1. **Candidate 7** (changelog-writer scope extraction) as a palette-cleanser — half day, a clear MS-DES, no external coordination.
2. **The style-guide meta-fix** — 15 minutes, mechanical, closes a visible embarrassment.
3. **The analyzer backlog-accessor quirk** — 30 minutes, probably rolled into the next pipeline-log cycle rather than its own spec.
4. **Candidate 8** (doc-freshness relevance v2) — full day, worth it because it lifts `doc-freshness` utilization (38% at run #13) from "ran it once and stopped" toward "ran it weekly and acted on output."
5. **Candidate 4** (remote BM25) — waiting on Market-side design input. Not next.
6. **Candidate 6** (Phase 1 cycle closure) — rolls in opportunistically.

## Artifacts produced in phase 3 so far

| File | Purpose |
|------|---------|
| `docs/design/release-checklist-script.md` (MS-DES-0005) | Design spec for the version-drift checker. |
| `docs/design/pipeline-log-analyzer.md` (MS-DES-0006) | Design spec for the analyzer. |
| `docs/design/rule-3-1-proper-nouns-and-sentence-boundaries.md` (MS-DES-0007) | Design spec for the Rule 3.1 hardening. |
| `build_scripts/check_release_versions.py` | Stdlib version-drift checker (~200 lines). |
| `build_scripts/test_check_release_versions.py` | 12-test suite. |
| `skills/doc-pipeline/scripts/analyze_pipeline_log.py` | Stdlib pipeline-log analyzer (~650 lines). |
| `skills/doc-pipeline/scripts/test_analyze_pipeline_log.py` | 48-test suite. |
| `skills/style-checker/scripts/style_autofix.py` (modified) | PROPER_NOUNS widened; sentence-boundary awareness added. |
| `skills/style-checker/scripts/test_style_autofix.py` (extended) | 45 tests (12 new). |
| `skills/style-checker/references/style-guide.md` (extended) | Rule 3.1 prose extended with multi-sentence and proper-nouns subsections. |
| `docs/analysis/pipeline-log-baseline-2026-04-14.md` (MS-ANA-0001) | Pre-sweep baseline scorecard. |
| `docs/analysis/pipeline-log-baseline-2026-04-14-readme-swept.md` (MS-ANA-0002) | Post-sweep baseline scorecard with deltas. |
| `README.md` (swept) | 21 headings canonicalized to sentence case. |
| `CHANGELOG.md` (extended) | `[Unreleased]` stamped for all three shipped candidates. |
| `docs/.doc-pipeline-log.json` (extended) | Runs #10 through #13. |
| `docs/phase-3-interim-retrospective.md` | This document. |

## How the next session picks up

One file read puts the next session in context: this document. From there:

- To reproduce the current scorecard: `python3 skills/doc-pipeline/scripts/analyze_pipeline_log.py --log-path docs/.doc-pipeline-log.json --format markdown`.
- To verify test suites: `python3 skills/style-checker/scripts/test_style_autofix.py` and `python3 skills/doc-pipeline/scripts/test_analyze_pipeline_log.py` and (on a 3.11+ interpreter) `python3 build_scripts/test_check_release_versions.py`.
- To verify the README stays clean: `python3 skills/style-checker/scripts/style_autofix.py --check README.md`.
- To pick up the next candidate: see §"Decision for next step" above.
