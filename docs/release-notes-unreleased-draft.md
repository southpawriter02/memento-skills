---
Status: DRAFT — generated from the `[Unreleased]` window in `CHANGELOG.md` as a Phase 3 Candidate 6 exercise on 2026-04-15. **Not a version stamp.** No `pyproject.toml` edit has been performed. When the real cut happens, this file will be regenerated from the then-current `[Unreleased]` and renamed to `docs/release-notes-vX.Y.Z.md`.
Audience: mixed (developer + operator).
Source: `CHANGELOG.md` lines under `## [Unreleased]` at HEAD.
---

# Release notes — unreleased window

## At a glance

This is a Phase 3 working-window release. Nine substantive changes shipped — six anchored to a `MS-DES-NNNN` design-spec that landed before the code, two follow-up fixes that surfaced while style-cleaning or running the newly-built analyzer (the `Market` PROPER_NOUNS entry and the `current_warnings_backlog` accessor correction), and one standalone style-guide meta-fix sweep. The docs-first discipline held across every design-spec-anchored item. The theme is **pipeline observability, style discipline, and weekly-rhythm doc-health tooling**, with one deliberately design-only entry (MS-DES-0010 remote BM25) parked against a cross-system dependency.

Highlights:

- **Doc-freshness grew a priority lens** (MS-DES-0009): stdlib-only BM25-weighted importance scoring plus a `priority-digest` CLI output mode designed for a weekly five-minute review pass. Targeted at the 38% utilization number the skill was stuck at in the run #13 scorecard.
- **Pipeline runs are now measurable** (MS-DES-0006): a read-only analyzer against `docs/.doc-pipeline-log.json` emits per-skill utility scorecards in human, JSON, or Markdown form.
- **Rule 3.1 sentence-case stopped over-correcting** (MS-DES-0007): `PROPER_NOUNS` roughly doubled, multi-sentence headings now respect sentence boundaries, and the style guide itself was swept in a single pass.
- **Changelog-writer surfaces conventional-commit scopes** (MS-DES-0008): `scopes_used` in the summary, `--filter-scope` on the CLI, and a SKILL.md step showing how to group a changelog by scope.
- **Release-version drift has a guardrail** (MS-DES-0005): a stdlib script that checks ten known call sites against the canonical `pyproject.toml [project].version`, exits non-zero on drift.
- **Remote BM25 fusion is specced, not coded** (MS-DES-0010): the three plausible Market-side surface shapes are enumerated with client-side deltas for each; implementation is deferred until the Market-owner answers the blocking question.

## What's new

### Doc-freshness relevance v2 (MS-DES-0009)

New module `skills/doc-freshness/scripts/doc_importance.py` exports `compute_importance_scores(docs_root, doc_paths) -> dict[str, float]`. Each doc gets an `importance_score` that combines *distinctive content density* (sum of top-`K=10` term IDFs, weight `0.6`) with *inbound reference authority* (number of other docs linking to it, weight `0.4`), max-normalized to `[0.0, 1.0]`. A `classify_priority` helper discretizes this into `high` / `medium` / `low` at tertile-inspired cut-points (`0.66`, `0.33`).

Scanner integration is additive — every `docs[]` record gains `importance_score` and `priority` sibling fields, and the summary gains `priority_counts`. No existing field is removed or renamed, so any JSON consumer keeps working unchanged.

Two new CLI flags: `--min-priority {low,medium,high}` (default `low` = pass-through) and `--format {json,priority-digest}` (default `json`). The intended weekly flow is captured in a new SKILL.md **Step 2a** — run `--since "7 days ago" --min-priority medium --format priority-digest`, read the digest, act on the top two or three, repeat next week.

Covered by 26 new unit tests (`test_doc_importance.py`) against the 20 pre-existing `test_relevance.py` tests, all passing in ~53ms. The BM25 core is ported from `core/skill/retrieval/local_bm25_recall.py` with matching `BM25_K1=1.2`, `BM25_B=0.75`, and stopword set; the ports are independent modules today, with a shared-primitives consolidation left as a future MS-DES.

### Pipeline-log analyzer (MS-DES-0006)

New read-only script `skills/doc-pipeline/scripts/analyze_pipeline_log.py`. Classifies each logged run by which underlying skill was invoked (conservative attribution via a top-level `ATTRIBUTION_RULES` dict), then emits per-skill utility scorecards grouped into three metric families: per-skill (utilization rate, coverage, runs-invoked list), skill-specific numerics (style-checker errors-fixed, doc-freshness scan totals, release-notes creates, etc.), and overall (docs-first discipline rate from `MS-DES-NNNN` references, release cadence, longest gap).

Three output modes via `--format {human,json,markdown}`. Forty-eight unit tests cover attribution per skill, metric arithmetic, all three formatters, and the empty-log edge case. Baseline against the real 11-run log captured at `docs/analysis/pipeline-log-baseline-2026-04-14.md`.

A follow-up fix (MS-ANA-0002) corrected a subtle bug where the `current_warnings_backlog` accessor would skip over explicit-zero runs — it now respects the last attributed style-checker run's value even when that value is `0`, so the analyzer correctly reports `backlog: 0` after a cleanup sweep.

### Rule 3.1 sentence-case hardening (MS-DES-0007)

`PROPER_NOUNS` widened from ~30 to ~60 entries, organized by category, with the style guide now explicitly pointing at the dict as the authoritative source. Additions include `OpenClaw`, `SQLite`, `PostgreSQL`, `MySQL`, `iOS`, `Flet`, `Briefcase`, `Pydantic`, `SQLAlchemy`, plus a whole acronym block (`API`, `CLI`, `SDK`, `UI`, `IDE`, `GUI`, `OSS`, `BSD`, `MIT`, `TLS`, `HTTP`, `HTTPS`, `URL`, `AST`, `NFKC`, `RRF`).

Subsequent widenings landed as sub-work when each surfaced a real gap in practice:

- **HTML heading tags** (`h1`…`h6`) — the `_is_acronym` helper only detects pure-alpha all-caps, so digit-containing tokens were being lowercased.
- **Language and locale adjectives** (`Latin`, `American`, `English`, `British`, `Unicode`) — not acronyms but still proper nouns.
- **`Market`** — the Skill Market service, referenced throughout MS-DES-0004 and MS-DES-0010 (surfaced while style-cleaning MS-DES-0010).

`_sentence_case_heading` now threads an `at_sentence_start` state variable that flips `True` after a token whose trailing punctuation is exactly `.`, `!`, or `?` — excluding ellipses and technical identifiers (`v0.3.0`, `config.json`). Multi-sentence headings like `## One Repo. One Learning Agent.` now correctly produce `## One repo. One learning agent.`

Forty-eight unit tests in `test_style_autofix.py`, all passing. The style guide itself was swept in a single pass (44 of its own headings were failing Rule 3.1 — a visible embarrassment documented in the Phase 3 interim retrospective), leaving only three intentional findings that are example content, not real violations.

### Changelog-writer scope surfacing (MS-DES-0008)

The parser already extracted conventional-commit scopes but never surfaced them. Three narrow changes close that gap:

1. The `summary` block gains a sorted `scopes_used` list (always present, may be `[]`).
2. A new repeatable `--filter-scope <scope>` CLI flag (and `filter_scopes=` kwarg on `parse_git_log`) narrows the commit list to matching scopes, case-insensitive and exact-match, with OR-semantics across repeats. All summary counters recompute against the filtered list so downstream consumers never see inconsistent numbers.
3. SKILL.md gains a **Step 3a — Scope-based grouping** sub-step showing how to use `scopes_used` to organize a changelog with bolded-scope bullets under each Keep a Changelog category.

Fourteen new unit tests (`test_git_log_parser.py`), all passing via stdlib `unittest` + `unittest.mock.patch.object`. No real git repo required.

### Release-version drift checker (MS-DES-0005)

New stdlib script `build_scripts/check_release_versions.py`. Reads the canonical version from `pyproject.toml [project].version` and verifies every other place the version appears in the repo matches — ten known call sites (three `pyproject.toml` entries including the Flet and Briefcase packagers, `version.py`, `middleware/config/system_config.json`, and five hard-coded Python-literal fallbacks). Emits human-readable or `--json` drift reports; exits `0` clean, `1` on drift, `2` on usage error. Twelve unit tests against tmp-dir fixture repos.

### Remote BM25 fusion design-space spec (MS-DES-0010)

**Docs-only.** No client-side or server-side code shipped in this cycle.

The blocking question — "does the Market have a BM25 index surface?" — is a cross-system design decision that needs sign-off from whoever owns the `skill_retrieval_api` service. Rather than invent a Market-side schema to unblock ourselves, this MS-DES enumerates the three plausible surface shapes and walks through the concrete client-side deltas each would require in `RemoteRecall`, `MultiRecall._stamp_rank`/`_apply_fusion`, and `RecallCandidate`:

- **Shape A** — `strategy` parameter on the existing `/api/v1/search` endpoint.
- **Shape B** — new sibling `/api/v1/search_bm25` endpoint.
- **Shape C** — multi-field response shape returning per-strategy `bm25_score` / `bm25_rank` / `vector_score` / `vector_rank`.

Five rejected alternatives are locked in (dual-remote client shim, reusing the opaque remote `score` as a BM25 proxy, dropping the local-before-remote tier rule, mirroring the remote catalog locally, waiting indefinitely). Six open questions are tagged for Market-owner resolution — including a `bm25_ready` health signal analogous to today's `embedding_ready`, and whether remote-BM25 and local-BM25 should fuse as one merged signal or as two independent terms in the RRF sum.

Conditional recommendation: Shape C is lowest long-run client complexity if the Market team owns both sides and can ship a breaking schema rev; Shape A is the minimum-invasiveness path otherwise. A follow-up MS-DES-0011 will nail down the implementation once a shape is chosen.

## Upgrade notes

No breaking changes in this window. Every change is additive:

- JSON schemas for `doc-freshness` scans and `changelog-writer` parses gain optional fields; existing consumers reading `name` and `score` or iterating a commit list keep working.
- The two new `doc-freshness` CLI flags default to prior behavior (`--min-priority low`, `--format json`).
- `--filter-scope` defaults to "no filter" when the flag is absent.
- Style-checker `PROPER_NOUNS` additions only *prevent* incorrect lowercasing; they do not change any text that was already correct.

If you were relying on the `current_warnings_backlog` accessor returning the last *non-zero* value, update callers — the accessor now returns the last attributed run's actual value including explicit `0`. The old behavior was a bug, not a feature.

## Known issues and deferred work

- **MS-DES-0010 implementation is blocked** on a Market-owner decision between Shapes A / B / C. Once resolved, MS-DES-0011 will land the client-side implementation.
- **BM25 shared-primitives consolidation** — `doc_importance.py` and `local_bm25_recall.py` each carry their own `_tokenize` and a local `DocBm25Index` / `_BM25Index` implementation. The ports are deliberate (self-contained-script invariant under `skills/*/scripts/`), but a future MS-DES could factor out a shared primitive.
- **Translation-pass backlog** — `core/skill/retrieval/` still has 30 docstrings flagged as non-target or mixed-script under the current `target_script=latin` convention. Not in-scope for this window; surfaced by the doc-generator translation-summary mode.

## References

- `CHANGELOG.md` — full per-entry history for the window, with per-test counts.
- `docs/design/doc-freshness-relevance-v2-bm25-weighting.md` — MS-DES-0009.
- `docs/design/pipeline-log-analyzer.md` — MS-DES-0006.
- `docs/design/rule-3-1-proper-nouns-and-sentence-boundaries.md` — MS-DES-0007.
- `docs/design/changelog-writer-scope-extraction.md` — MS-DES-0008.
- `docs/design/release-checklist-script.md` — MS-DES-0005.
- `docs/design/remote-bm25-fusion.md` — MS-DES-0010.
- `docs/analysis/pipeline-log-baseline-2026-04-14.md` — first analyzer baseline.
- `docs/analysis/pipeline-log-baseline-2026-04-14-readme-swept.md` — post-sweep baseline.
