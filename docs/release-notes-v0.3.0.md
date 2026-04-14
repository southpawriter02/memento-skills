# Memento-Skills v0.3.0 release notes

**Release date:** 2026-04-14
**Audience:** Developers and integrators building on Memento-Skills.

<!-- Drafted by the release-notes skill on 2026-04-14 from CHANGELOG.md. -->

## Overview

Memento-Skills v0.3.0 is an internal-tooling release. The architectural
baseline from v0.2.0 — bounded contexts, the three-layer config, the Skill
Market, and the IM Gateway — carries over unchanged. What moves in this
release sits one layer down: skill retrieval now runs lexical BM25 alongside
the existing vector pipeline and fuses the two rank lists via reciprocal rank
fusion (RRF), and a six-skill tech-writing suite (plus an orchestrator) lands
with its own design-spec convention and a persistent pipeline feedback log.

No imports moved. No config schema changes. Every pre-existing call into the
retrieval subsystem keeps working because the new BM25 fields on
`RecallCandidate` are optional and additive. If you have been ignoring
retrieval internals, the upgrade is free — your queries will just surface
lexically-obvious matches that the vector pipeline was quietly missing.

## Highlights

### BM25 lexical retrieval, fused with vectors via RRF

`core/skill/retrieval/local_bm25_recall.py` is a third local recall strategy
that runs a pure-Python BM25 search over skill names, descriptions, and full
SKILL.md bodies. It uses canonical BM25 parameters (`k1=1.2`, `b=0.75`), an
NFKC-normalized Unicode-aware tokenizer, a ~30-word English stopword set, and
field-weighting by token repetition (`W_NAME=4`, `W_DESC=2`, `W_BODY=1`). The
index lives in memory, rebuilds lazily on the first query after construction,
and auto-invalidates when the skills directory's signature changes.

When the same skill surfaces in both the BM25 and the vector strategy's
output, `MultiRecall._rerank_candidates` fuses the two per-strategy ranks
into a single score via
`RRF(skill) = 1/(60 + rank_bm25) + 1/(60 + rank_vec)` (Cormack, Clarke &
Büttcher 2009). RRF was chosen over linear-combination fusion because it
needs no score normalization and no tunable `α`. The local-before-remote tier
rule is preserved: remote candidates can never rank above any local
candidate, regardless of fused score. Hybrid hits are tagged with
`match_type="hybrid"` for diagnostics. The design walk-through lives at
[`docs/design/bm25-retrieval-layer.md`](design/bm25-retrieval-layer.md).

### Tech-writing skill suite

Six Cowork-format skills land together as a coherent documentation toolchain,
plus an orchestrator that runs them end-to-end:

- **`style-checker`** reviews Markdown against a 30-rule style guide and
  auto-fixes the six mechanical rules (3.1 section-heading capitalization,
  3.2 title-case rejection, 3.6 no trailing colons on headings, 4.1 list
  punctuation, 6.1 code-fence language tags, 7.1 link-text sentence case).
- **`changelog-writer`** parses conventional-commit git history and drops
  entries into Keep a Changelog sections.
- **`doc-freshness`** scans a `docs/` tree against git history and classifies
  each file as fresh / possibly_stale / likely_stale. The relevance filter
  was rewritten in this release to use directory-prefix path overlap rather
  than the fuzzy-substring heuristic that had been producing false positives.
- **`doc-generator`** extracts signatures from Python (AST-based), C#, and
  TypeScript (regex-based), with reference, configuration, and
  getting-started templates. New in this release: every docstring is
  classified by Unicode script and annotated with `docstring_language`
  (`target` / `non_target` / `mixed` / `empty` / `unknown`), so translation
  gaps are visible from the extractor output without re-reading source.
- **`release-notes`** is the knowledge skill behind the document you are
  reading right now. It calibrates tone for developer / end-user / ops /
  executive audiences from the same CHANGELOG entries.
- **`doc-pipeline`** is the orchestrator — it runs the other five in sequence
  against a repo, logs results to `docs/.doc-pipeline-log.json`, and works
  around the framework's no-skill-to-skill-invocation constraint by invoking
  sibling scripts directly.

### Docs-first delivery convention

This release formalizes a docs-first working rhythm for all design-scale
changes. Each of the six tech-writing items listed above, plus the BM25
layer, shipped behind a numbered design spec (MS-DES-0001 through
MS-DES-0004) under `docs/design/`. Every pipeline run appends a dated entry
to `docs/.doc-pipeline-log.json` — a persistent record of what changed, what
the checkers flagged, and how long the run took, suitable for later
utility-scoring analysis.

## Breaking changes and migration notes

**None.** v0.3.0 is additive. `RecallCandidate`'s four new fields
(`bm25_score`, `vector_score`, `bm25_rank`, `vector_rank`) all default to
`None`; callers that only read `name` / `score` keep working. The
`docstring_language` / `docstring_scripts` fields emitted by the
`doc-generator` extractor are additive too — existing consumers that only
read signature text see no change.

If you never looked under `core/skill/retrieval/` before, you still don't
have to. If you did — and you were subclassing `MultiRecall` or
instantiating recall strategies directly — see
[`docs/design/bm25-retrieval-layer.md`](design/bm25-retrieval-layer.md) §6 for
the updated construction contract.

## What's also in this release

Beyond the headlines, v0.3.0 ships two new style-guide rules (3.6 no
trailing colons on headings, auto-fixed; 9.1 MDX front-matter title +
description, flagged but not synthesized); an `--include-untracked` mode on
the doc-freshness scanner for drafting passes against uncommitted Markdown;
a module-level docstring extractor pass in `doc-generator` that was
previously missing file-level prose; and a `--translation-summary-only` CLI
flag for fast audits of multilingual codebases.

On the test side: 28 new unit tests for the `doc-generator` translation
classifier, 34 for the `style-checker` auto-fix, 17 for the doc-freshness
relevance filter, and a full unit-test suite for `LocalBm25Recall` and the
fusion stage of `MultiRecall` at `tests/test_skills/retrieval/`. All pass
against a real Python 3.12 interpreter with the full dependency graph, not
just the isolated smoke-test harness used during development.

## Upgrade checklist

1. Pull v0.3.0 and re-run your skill test suite — nothing should break, but
   if it does the failure is almost certainly in a caller that was reading a
   `RecallCandidate` field by index rather than by name.
2. Delete any cached BM25 indices from dev branches. The index is in-memory
   and rebuilds on the first query, so there is nothing on disk to migrate,
   but stray pickles from pre-release builds will confuse cold-start timing.
3. If you run the `doc-generator` against a non-Latin codebase, pass
   `--target-script` to match your primary script (e.g. `--target-script
   han` for a Chinese-primary repo). The default is `latin`.
4. If you were tracking style-checker output, expect new findings under
   Rules 3.6 and 9.1. Run `skills/style-checker/scripts/style_autofix.py
   --check` over `docs/` once to see the new baseline before editing.
5. Browse `docs/.doc-pipeline-log.json` after your first local pipeline run
   — the format is intentionally append-only so you can diff runs over time.

## Thanks

Thanks to everyone who exercised the BM25 layer and the tech-writing skills
against real repos during the pre-release window, and to the folks who
pushed for docs-first delivery as a house convention. Keep the feedback
coming — the pipeline log is literally the dataset we will use to tune the
next pass.
