# Doc-freshness relevance v2 — BM25-weighted importance scoring

## Document control

| Field               | Value                                                            |
| :------------------ | :--------------------------------------------------------------- |
| **Document ID**     | MS-DES-0009                                                      |
| **Feature Name**    | Doc-freshness relevance v2 — per-doc importance scoring + priority-digest output |
| **Module Scope**    | `skills/doc-freshness/scripts/doc_importance.py` (new), `skills/doc-freshness/scripts/doc_freshness_scanner.py`, `skills/doc-freshness/SKILL.md` |
| **Status**          | Draft                                                            |
| **Author**          | Ryan (via Claude / Cowork mode)                                  |
| **Date**            | 2026-04-14                                                       |
| **Reviewers**       | Ryan                                                             |
| **Est. Hours**      | ~full day (port + scoring + scanner wiring + tests + SKILL.md + pipeline-log entry) |
| **Parent Document** | [docs/phase-3-interim-retrospective.md](../phase-3-interim-retrospective.md) — candidate #8 |
| **Related**         | [MS-DES-0003 — relevance v1](./doc-freshness-relevance-filter.md) · [MS-DES-0004 — BM25 retrieval layer](./bm25-retrieval-layer.md) |

## Problem statement

The `doc-freshness` skill's utilization sat at 38% at run #13 in the pipeline-log scorecard — it was invoked in runs #2, #3, and #4 during the Phase 2 relevance-filter v1 cycle (MS-DES-0003), then not again. The Phase 3 interim retrospective characterizes this as "ran it once and stopped." Goal for v2: lift the skill toward "ran it weekly and acted on output."

The v1 filter (MS-DES-0003) solved the primary false-positive problem — directory-prefix overlap replaced fuzzy substring matching, and the two clearly-spurious pre-v1 matches (`agent_execution_flow.md`, `llm_tool_call_compatibility.md`) stopped surfacing. But v1 treats every stale doc the same. A run that reports "three possibly-stale, five likely-stale" hands the agent eight equally-weighted items, and the agent has to read each one to decide which matter. That's enough friction to keep the skill out of a weekly rhythm.

Three observable symptoms of the v2 gap:

1. **No prioritization signal.** The JSON output has `status` (fresh / possibly_stale / likely_stale) and `days_since_update`, but no signal for "this doc is referenced by the rest of the tree" vs "this doc is a one-off note nobody links to." Eight unranked stale docs is harder to act on than two ranked ones.
2. **No concise digest format.** Every existing output mode emits full commit lists and full recommendation prose. Useful for deep investigation, noisy for a weekly glance.
3. **No threshold flag.** A user who wants "just show me the top few things to look at" has to pipe through `jq` or read the whole JSON.

The retrospective's proposed lever — BM25-weighted scoring reusing the index machinery from MS-DES-0004 — attacks symptom #1 directly. Symptoms #2 and #3 are additive low-cost wins that compound the utilization gain once the signal exists.

## Proposed solution

Three concentric changes, all additive (the existing CLI surface, JSON schema, and `--include-untracked` semantics are preserved):

1. **New `doc_importance.py` module.** A sibling script that builds a one-shot BM25 index over the docs tree using a port of `Bm25Index` + `_tokenize` from `core/skill/retrieval/local_bm25_recall.py`, and exposes a single entry point `compute_importance_scores(docs_root, doc_paths) -> dict[str, float]`. The port is stdlib-only (no `rank_bm25`, no `whoosh`) and preserves the tuning constants from MS-DES-0004 (`BM25_K1=1.2`, `BM25_B=0.75`, `MIN_TOKEN_LENGTH=2`, same stopword set).
2. **Scanner integration.** `doc_freshness_scanner.py` computes importance scores once at the top of the scan pass, attaches `importance_score` (float in [0, 1]) and `priority` (string in `{low, medium, high}`) to every doc record, and includes a corresponding breakdown in the summary block.
3. **Two new CLI flags for the weekly-habit use case:**
   - `--min-priority {low,medium,high}` (default: `low`) — filters the returned doc list to records at or above the given priority. `low` is pass-through (every doc returned, same as today); `medium` and `high` shrink the output.
   - `--format {json,priority-digest}` (default: `json`) — adds a new concise Markdown-digest output mode suitable for weekly review. The existing JSON mode is unchanged.

Plus one SKILL.md addition: a new "Step 2a — weekly-rhythm recommendation" sub-step between Step 2 (run the scanner) and Step 3 (interpret the results), describing the intended weekly workflow: `--since "7 days ago" --min-priority medium --format priority-digest` → read the digest → act on the top two or three → repeat next week.

### Importance scoring formula

The per-doc importance score is a normalized convex combination of two BM25-derived signals:

```python
intrinsic_score(doc) = sum(idf(term) for term in top_K_distinctive_terms(doc)) / max_intrinsic_in_corpus
reference_score(doc) = inbound_reference_count(doc) / max_inbound_in_corpus
importance_score(doc) = W_INTRINSIC * intrinsic_score(doc) + W_REFERENCE * reference_score(doc)
```

With:

- `top_K_distinctive_terms(doc)` — the doc's own `top_K=10` terms ranked by per-token IDF (a term that appears in many docs gets lower weight; a term that appears in few docs gets higher weight). This is the "distinctive content density" proxy. A doc heavy on boilerplate boilerplate has a low intrinsic score; a doc with distinctive technical terminology has a high one.
- `inbound_reference_count(doc)` — the count of other Markdown files in the docs tree that link to or mention `doc`'s path via Markdown links, inline-code spans, or bare prose paths (reuses the existing `extract_path_references` code in `doc_freshness_scanner.py`).
- `W_INTRINSIC = 0.6` and `W_REFERENCE = 0.4` — deliberately weighted toward the BM25 signal the retrospective called for, with reference authority as a secondary stabilizer. Both weights are module-level constants in `doc_importance.py`, exposed for future tuning but not (yet) CLI flags.
- Both component scores are max-normalized against the scanned corpus so a doc with no distinctive terms and no inbound references scores `0.0`, and the top doc on both axes scores `1.0`. If the corpus is empty (no other docs) the denominator fallbacks to `1.0` to avoid division by zero.

### Priority buckets

`priority` is a three-level discretization of `importance_score` for easy filtering and stable bucket-based output:

| Priority | Criterion                                |
|:---------|:-----------------------------------------|
| `high`   | `importance_score >= 0.66`               |
| `medium` | `0.33 <= importance_score < 0.66`        |
| `low`    | `importance_score < 0.33`                |

The 0.33 / 0.66 cut-points are tertile-inspired defaults. They're module-level constants in `doc_importance.py` for future tuning, but no CLI flag exposes them — priority is a three-bucket filter, not a continuous knob.

### Why a ported BM25 module and not a direct import of `core/skill/retrieval/local_bm25_recall.py`

Every other script under `skills/*/scripts/` is self-contained stdlib Python that runs by `python scripts/<script>.py` without a `sys.path` dance. Importing `core.skill.retrieval.local_bm25_recall` would require the scanner to know the repo-root layout, or to push the repo root onto `sys.path` at runtime — both introduce a coupling between a user-level skill and the host application's module hierarchy.

The reusable surface from `local_bm25_recall.py` is small: `_tokenize` (~40 lines), `Bm25Index` (~180 lines of class body), and six tuning constants. Porting them into `skills/doc-freshness/scripts/doc_importance.py` is a one-time copy with comments indicating the upstream source, and it buys back the self-contained-script invariant. A follow-up work item (post-v2) could consolidate both copies behind a shared `_bm25_primitives.py` in a tools directory, but that consolidation is itself the kind of cross-skill dependency the current single-file-script pattern is trying to avoid.

### Why a three-bucket priority and not a continuous ranking

An ordinal `priority_rank` integer (1..N) would give finer-grained ordering but introduces two costs: (a) it makes the output order-sensitive — a single new doc landing higher shuffles every other doc's rank — and (b) it invites misreading ("doc A is rank 3, doc B is rank 4, therefore A is meaningfully more important than B"), when the underlying scores may be within 0.01 of each other. Three discrete buckets (low / medium / high) give the same filtering power (`--min-priority medium` is the exact ask) without those downsides. The continuous `importance_score` is still in the JSON for anyone who wants it.

## Alternatives considered

### Alternative A — log-driven retrieval frequency

The retrospective's exact phrasing was "weighting retrieval-frequency of each doc." The most literal reading would be: instrument the doc-search / doc-lookup path to log which docs are retrieved over time, then weight a doc by observed retrieval count. Rejected because (a) no such log exists today — there's no "doc retrieval" event stream, the closest is the skill-retrieval path which indexes SKILL.md files, not the `docs/` tree; (b) bootstrapping a log produces zero signal for the first N weeks; (c) a BM25-derived "distinctive content density" + "inbound reference count" pair is a reasonable static proxy for the same intuition — highly distinctive, highly-referenced docs are the ones that would also show high retrieval frequency under load. If a real retrieval log emerges later, it can feed `importance_score` as a third signal without changing the output schema.

### Alternative B — extend the existing skill-BM25 index to also index docs

`LocalBm25Recall` already builds an in-memory BM25 index over skills. We could widen its corpus to include `docs/` as well and have a single unified retrieval layer. Rejected because (a) the skill index is tuned for skill-retrieval (field weighting by name/description/body is wrong for docs, which don't have "name" vs "description" structure); (b) it would couple the doc-freshness skill to a core application module's lifecycle (index rebuild, invalidation, query surface); (c) v2's goal is static per-doc importance scoring, not live doc-retrieval — if doc-retrieval-as-a-feature materializes later it should be its own design note.

### Alternative C — precompute importance scores offline into a cached file

Build `docs/.doc-importance.json` as a checked-in cache that the scanner reads at runtime, refreshed by a separate `refresh-doc-importance` tool. Rejected because (a) it introduces a second source of truth that can drift from the docs tree; (b) the scanner already walks the docs tree for path extraction, so computing importance scores during that same pass costs tens of milliseconds for typical corpora (measured on the repo's current 58-doc tree during prototyping); (c) a cache invalidation strategy adds more code and test surface than a one-shot rebuild saves runtime.

### Alternative D — just add a sort-by-date flag and skip the BM25 work entirely

`--sort-by-staleness` would let the weekly-rhythm user see the oldest docs first without any scoring machinery. Rejected because (a) date is already the classification signal — sorting by days-since-update within the `likely_stale` bucket gives no new information; (b) the retrospective explicitly called out BM25-weighted scoring as the v2 story, and this alternative ignores the stated lever; (c) it doesn't differentiate between "forgotten doc nobody references" (probably OK to stay stale) and "central doc many docs depend on" (definitely worth fixing) — that differentiation is the actual utility v2 adds.

### Alternative E — continuous `priority_rank` integer instead of three-bucket priority

Covered in the proposed-solution rationale above. Rejected for order-sensitivity and false-precision reasons.

## Acceptance criteria

1. New module `skills/doc-freshness/scripts/doc_importance.py` exists and exports `compute_importance_scores(docs_root: Path, doc_paths: list[Path]) -> dict[str, float]`. Given an empty corpus (no docs) the function returns an empty dict without error.
2. The returned scores are floats in `[0.0, 1.0]`. The maximum observed score in a non-empty corpus is `1.0` (max-normalization lock-in) and the minimum is `>= 0.0`.
3. Port invariants: the tokenizer in `doc_importance.py` produces the same token stream as `core/skill/retrieval/local_bm25_recall._tokenize` on three fixture strings — an English sentence, a CJK sentence, and a mixed-script sentence — locked in by unit test to guard against accidental divergence.
4. Scanner integration: every record in the scanner's output `docs[]` array gains two new fields — `importance_score` (float) and `priority` (one of `"low"`, `"medium"`, `"high"`) — and the top-level `summary` block gains `priority_counts` (a dict with keys `high`, `medium`, `low` counting docs in each bucket). No existing field is removed or renamed.
5. `--min-priority medium` filters the returned `docs[]` list to records with priority `medium` or `high`. `summary.total_docs`, `summary.fresh` / `possibly_stale` / `likely_stale`, and `summary.priority_counts` all recompute against the filtered list so numbers stay consistent.
6. `--min-priority high` filters to high-only. `--min-priority low` is pass-through (equivalent to omitting the flag).
7. `--format priority-digest` emits a concise Markdown digest: a top-level heading with the corpus date range, an H2 for each priority bucket present (omitting empty buckets), and a bulleted list under each — one line per doc with its path, status, days-since-update, and a short reason clause. No full commit listings or recommendation prose.
8. `--format json` is the default and byte-for-byte identical to today's JSON output *except* for the two new fields on each record and `priority_counts` in summary. Any script currently consuming the JSON will still work.
9. SKILL.md gains a "Step 2a — weekly-rhythm recommendation" sub-step describing the `--since "7 days ago" --min-priority medium --format priority-digest` workflow.
10. All new behavior covered by unit tests. Target: at least 18 new tests split across a new `test_doc_importance.py` (tokenizer parity, BM25 math, importance formula, max-normalization edge cases, empty-corpus edge case) and the existing `test_relevance.py` (scanner integration: new fields present, `--min-priority` filtering, `priority-digest` formatter, summary recompute). All existing 20 tests in `test_relevance.py` continue to pass unchanged.

## Error handling

- **Empty docs tree.** `compute_importance_scores` returns `{}`. Scanner emits an empty `docs[]` list and `priority_counts: {"high": 0, "medium": 0, "low": 0}`. No error.
- **Single-doc corpus.** Max-normalization denominator is the single doc's own score; that doc scores `1.0` trivially. This is a mathematical curiosity, not a bug — a one-doc tree genuinely has no relative importance signal.
- **`--min-priority` unknown value.** argparse `choices=["low", "medium", "high"]` rejects anything else with a standard argparse error before scanner code runs. No custom error path needed.
- **`--format` unknown value.** Same — argparse `choices=["json", "priority-digest"]`.
- **Non-UTF-8 file.** The port preserves upstream `local_bm25_recall.py`'s handling: tokenizer skips non-decodable bytes silently, same as today's behavior. Documented in the port's module docstring.
- **Doc references a path outside the docs tree.** Reference-count denominator unchanged. The out-of-tree reference is simply ignored (the existing `extract_path_references` already filters these).

## Out of scope

- Live doc-retrieval feature (Alternative B). Separate MS-DES if it materializes.
- A doc-retrieval log or event stream (Alternative A's prerequisite). Would be a separate design note.
- Persisted `docs/.doc-importance.json` cache (Alternative C). Revisit if scan time grows past ~500ms on realistic corpora.
- Changes to the freshness classification thresholds (30-day boundary stays as-is per MS-DES-0003).
- `--weight-intrinsic` / `--weight-reference` CLI flags. Module-level constants for now; promote to flags only if a tuning case emerges.
- Consolidating `doc_importance.py` and `core/skill/retrieval/local_bm25_recall.py` into a shared primitives module. Deferred to post-v2; the two copies diverge slowly enough that the duplication is cheaper than premature abstraction.
- `release-notes` skill or `changelog-writer` skill integration. Neither depends on this.
