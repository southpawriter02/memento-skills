# Candidate 6 — phase 1 cycle-closure findings

- **Date:** 2026-04-15
- **Scope:** Phase 1 criterion closure for `doc-generator` and `release-notes` skills — the two skills still flagged as "needs ≥ 2 create → test → review → improve cycles with revisions" in the Phase 3 interim retrospective.
- **Fixtures:**
  - `doc-generator` — input `core/skill/retrieval/` (8 Python files, 8 classes, 50 methods, translation-mixed docstrings); output `docs/api/skill-retrieval.md`.
  - `release-notes` — input `CHANGELOG.md [Unreleased]` window (9 `Added` entries, 6 MS-DES-NNNN-anchored); output `docs/release-notes-unreleased-draft.md`.
- **Style-checker result (both artifacts, both cycles):** 0 findings.

> This note is the cycle-closure artifact — what each skill produced, what review surfaced, what the revision pass corrected. It is deliberately mechanical: the goal is to verify the skills can carry a real input through two cycles with a non-trivial revision delta, not to land new source code.

## Doc-generator cycle

### Cycle 1a — output

Generated `docs/api/skill-retrieval.md` (254 lines initial). Shape:

- Overview with ASCII architecture diagram (caller → `MultiRecall` → 4 strategies → `RecallCandidate`).
- Spec-cross-reference table (MS-DES-0004 local BM25, MS-DES-0010 remote BM25 pending).
- `RecallCandidate` full schema including MS-DES-0004 `bm25_score` / `vector_score` / `bm25_rank` / `vector_rank` additions.
- `BaseRecall` protocol table with required members.
- Per-strategy sections: `LocalFileRecall`, `LocalDbRecall`, `LocalBm25Recall`, `RemoteRecall`.
- `MultiRecall` fusion coordinator with core pipeline pseudocode, RRF math, tier rule, merge semantics.
- Translation summary (27 target / 11 non-target / 19 mixed / 9 empty / 0 unknown).
- Provenance block with exact reproducibility invocations.

Source signatures produced by `skills/doc-generator/scripts/extract_signatures.py` — both the full JSON dump (`--output`) and the translation-only triage mode (`--translation-summary-only`) were exercised.

### Cycle 1b — findings

Style checker: clean, 0 findings. Accuracy spot-checks against `core/skill/retrieval/*.py` verified every quoted constant and method name:

- `RRF_K = 60` ✓ (present in both `multi_recall.py:57` and `local_bm25_recall.py:82` — duplicate noted, see below)
- `BM25_K1 = 1.2`, `BM25_B = 0.75` ✓
- `W_NAME = 4`, `W_DESC = 2`, `W_BODY = 1` ✓
- `_stamp_rank`, `_apply_fusion`, `_merge_into_existing`, `_rerank_candidates` ✓ (names stable)
- Tier-rule sort key `(0 if c.source == "local" else 1, -c.score)` ✓
- `also_available_remote` metadata breadcrumb ✓
- `RemoteRecall` `certifi` TLS, `trust_env=False`, `embedding_ready` property, `from_config` returning `None` when unset ✓
- Two-term RRF formula `1 / (RRF_K + bm25_rank) + 1 / (RRF_K + vector_rank)` ✓

Five genuine findings surfaced by prose review:

1. **Header-hierarchy bug** — `### MultiRecall (fusion coordinator)` was nested under `## Concrete strategies`, but `MultiRecall` is the coordinator, not a strategy. Wrong level.
2. **k-default inconsistency** — the `BaseRecall` table stated `k: int = 10`, but `LocalFileRecall.search(..., k=0)` and `RemoteRecall.search(..., k=5)` override it. The doc covered the `RemoteRecall` default in its public-surface table but never explained why `LocalFileRecall` uses `k=0`.
3. **Self-contradictory merge bullet** — "silently dropped at the tier level; a `metadata["also_available_remote"]` flag is stashed for diagnostics." The bullet calls the drop silent, then immediately documents a breadcrumb. Rewrite needed.
4. **Port-claim overreach** — `LocalBm25Recall` bullet said the stdlib-only design "can be ported to `doc_importance.py` (MS-DES-0009)". But `doc_importance.py` was built as a *separate* implementation — the two are independent, not a shared port. Soften.
5. **Tech-debt observation (not fixed)** — `RRF_K = 60` is declared in two modules. Real duplication, but out of scope for a doc cycle.

### Cycle 2a — revisions

- Promoted `MultiRecall` from `###` to `##` and added a clarifying sentence: "Not a concrete strategy — it does not implement `BaseRecall`; instead it *composes* several `BaseRecall` instances."
- Added a paragraph after the `BaseRecall` translation note explaining the two intentional k-default divergences — `LocalFileRecall.search()` uses `k=0` because it is an enumerator that always returns everything; `RemoteRecall.search()` uses `k=5` because remote round-trips are billed.
- Rewrote the remote-into-local merge bullet to be internally consistent: "the remote candidate itself is dropped (the local entry wins on the tier rule), but a `metadata["also_available_remote"]` breadcrumb is stashed on the surviving local entry so downstream code can surface 'this skill is also installable from the Market' without a second fetch."
- Softened the port-claim to describe the two implementations as independent, with a shared-primitives consolidation called out as a future MS-DES.

Final line count: 256 (+2 from cycle 1a). Style-checker: still 0 findings post-revision.

### Doc-generator verdict

**Phase 1 criterion met.** Two create → test → review → improve cycles completed with substantive revisions in both major families the skill is expected to handle: structural (header level) and semantic (k-default explanation, self-contradictory prose, over-reach). Style-checker passed clean on both cycles. Translation-summary mode was exercised — 30 docstrings flagged as needing a non-target or mixed-script translation pass, which is the next action for the retrieval-layer subtree but deliberately out of scope for this exercise.

## Release-notes cycle

### Cycle 1a — output

Generated `docs/release-notes-unreleased-draft.md` (~160 lines) from the `CHANGELOG.md [Unreleased]` window. Shape:

- DRAFT front-matter explicitly flagging this is not a version stamp — no `pyproject.toml` edit, file will be regenerated and renamed when the real cut happens.
- "At a glance" summary with six highlight bullets.
- "What's new" with six grouped sections (doc-freshness v2, pipeline-log analyzer + backlog fix, Rule 3.1 hardening + style-guide meta-fix + Market widening, changelog-writer scope surfacing, release-version drift checker, remote BM25 design-space spec).
- "Upgrade notes" — additive-only changes, backlog-accessor behavior change called out.
- "Known issues and deferred work" — MS-DES-0010 blocker, BM25 shared-primitives consolidation, translation-pass backlog.
- "References" listing the MS-DES and baseline files.

### Cycle 1b — findings

Style checker: clean, 0 findings. Prose review:

1. **Count inaccuracy** — summary said "Eight substantive changes, six of which are anchored to a `MS-DES-NNNN` design-spec." Actual `Added` entry count in the `[Unreleased]` window is nine (MS-DES-0005/0006/0007/0008/0009/0010 + `Market` PROPER_NOUNS widening + MS-ANA-0002 analyzer backlog fix + style-guide meta-fix sweep). The "six MS-DES" count is correct; the "eight" total was off.
2. **Grouping** — release notes collapse `Market` widening into the Rule 3.1 section and style-guide meta-fix alongside it. Both are PROPER_NOUNS / style work; collapsing reads better than listing them as separate top-level groups. Keep the grouping.
3. **38% utilization claim** — verified against the source CHANGELOG entry ("target the `doc-freshness` skill's 38% utilization (run #13 scorecard)"). ✓
4. **Cumulative test count for PROPER_NOUNS section** — "Forty-eight" tracks MS-DES-0007's 45 + meta-fix's +2 + Market's +1 = 48. ✓

### Cycle 2a — revisions

Reworded the at-a-glance summary to reflect nine total changes and name the two non-MS-DES items plus the standalone meta-fix: "Nine substantive changes shipped — six anchored to a `MS-DES-NNNN` design-spec that landed before the code, two follow-up fixes that surfaced while style-cleaning or running the newly-built analyzer (the `Market` PROPER_NOUNS entry and the `current_warnings_backlog` accessor correction), and one standalone style-guide meta-fix sweep."

Style-checker: still 0 findings post-revision.

### Release-notes verdict

**Phase 1 criterion met.** Two create → test → review → improve cycles completed with a genuine revision in cycle 2 (count correction). The cycle also surfaced and validated the correct editorial choice to group related changelog entries into narrative sections rather than mirroring the changelog's flat `Added` structure.

## Cross-cycle observations

- **Style-checker remained clean on all four artifact + cycle combinations.** This is partial evidence that the MS-DES-0007 Rule 3.1 hardening and the MS-DES-0010 `Market` widening are doing their job on freshly-authored prose. The previous session's MS-DES-0010 draft needed 8 autofix applications; both of these artifacts needed 0.
- **Reviewing your own output surfaces genuinely different bugs than reviewing someone else's.** The five `doc-generator` findings split into: 1 structural (header level), 1 completeness (missing k-default explanation), 2 prose-quality (self-contradiction, overreach), 1 tech-debt observation (not fixed). The one `release-notes` finding was a counting error. Pattern: generator output tends to have accuracy / completeness holes; release-note output tends to have glosses and summary-level slips.
- **Tech-debt backlog grew by one observation** — `RRF_K` is duplicated across `multi_recall.py` and `local_bm25_recall.py`. Not addressed in this cycle. If the shared-primitives consolidation MS-DES happens, this should consolidate too.
- **Translation-pass backlog** remains — 30 non-target / mixed-script docstrings in `core/skill/retrieval/`. The generator's translation-summary mode gives a reliable triage signal and was exercised against this fixture.

## Artifacts produced

- `docs/api/skill-retrieval.md` — doc-generator cycle 1a + 2a output.
- `docs/release-notes-unreleased-draft.md` — release-notes cycle 1a + 2a output. Clearly labeled DRAFT / not a version stamp.
- This findings note at `docs/analysis/candidate-6-cycle-closure.md`.

## Phase 1 closure statement

Both `doc-generator` and `release-notes` have now completed two create → test → review → improve cycles with substantive revisions and a documented findings trail. Per the Phase 3 interim retrospective's Phase 1 criterion, both skills are considered Phase-1 complete. Remaining Phase 3 work beyond this cycle is MS-DES-0011 (remote BM25 implementation, gated on Market-owner decision) and the translation-pass backlog on `core/skill/retrieval/`.
