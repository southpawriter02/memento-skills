# BM25 retrieval layer: design specification

## Document control

| Field               | Value                                                                |
| :------------------ | :------------------------------------------------------------------- |
| **Document ID**     | MS-DES-0004                                                          |
| **Feature Name**    | BM25 retrieval layer for the skill library                           |
| **Module Scope**    | `core/skill/retrieval/`, touching `core/skill/gateway.py`            |
| **Status**          | Draft                                                                |
| **Author**          | Ryan (via Claude / Cowork mode)                                      |
| **Date**            | 2026-04-14                                                           |
| **Reviewers**       | Ryan                                                                 |
| **Est. Hours**      | ~1 day (design + strategy class + fusion + tests + pipeline wiring)  |
| **Parent Document** | [docs/phase-1-retrospective.md](../phase-1-retrospective.md) — candidate #6 |
| **Related Specs**   | None — this is the first retrieval-layer design note in `docs/design/`. |

## Problem statement

The skill discovery pipeline inside `SkillGateway.discover()` and `.search()` currently has exactly one local recall strategy that does any ranking: `LocalDbRecall`, which runs a single-vector cosine-similarity query against a SQLite table maintained by the `sqlite-vec` extension. The other local strategy, `LocalFileRecall`, returns every installed skill at a flat score of `1.0` — it is an enumeration, not a ranker. The remote strategy, `RemoteRecall`, delegates to the Skill Market's `/api/v1/search` endpoint and the gateway has no control over how the Market ranks results.

Two consequences follow.

**First**, the local ranker only sees `name + description`. The `to_embedding_text()` helper on `SkillManifest` concatenates exactly those two fields — the skill's full SKILL.md content is stored on disk but never indexed. A skill whose body explains "good for technical writing and changelog generation" but whose one-line description says "writes release artifacts" will miss a query for "changelog writer" unless the embedding model happens to bridge the gap semantically. Lexical matches on the body are unreachable.

**Second**, dense vector retrieval is a poor fit for some of the queries this system actually sees. Queries like `"style-checker"`, `"doc-freshness"`, or `"MS-DES-0003"` — exact names, tool identifiers, document IDs — need lexical precision. A vector model trained on prose semantics is an unnecessary lossy step when a literal string match is what the user wants. The retrospective flagged this explicitly under candidate #6: *"BM25 index over skill library. Past ~20 skills, the current semantic-only ranker will start missing exact-name queries."*

**The concrete gap:** the pipeline has no lexical retrieval layer at all. Every local recall decision is either "return everything" (`LocalFileRecall`) or "run a dense vector query over name+description" (`LocalDbRecall`). There is no room for a middle ground where a BM25 score over the full body text can either (a) surface a skill the embedding missed, or (b) reinforce a skill the embedding and BM25 agree on.

**Scope boundary.** This spec proposes adding a **third local recall strategy** — `LocalBm25Recall` — plus a fusion step so `MultiRecall` can combine BM25 and vector scores into a single ranked list. It does **not** replace the vector pipeline; both run, and the fusion stage decides the final order. It also does **not** touch `RemoteRecall` — the Market's ranker is out of scope here, and whatever scores it returns continue to flow into the existing tier rule (local-before-remote).

## Proposed solution

Four-part change, all additive.

1. **New strategy class `LocalBm25Recall`** living at `core/skill/retrieval/local_bm25_recall.py`. Implements the same async `recall(query, k)` interface the other strategies expose, returning `list[RecallCandidate]` with `match_type="bm25"` and a normalized BM25 score.

2. **Pure-Python BM25 index.** Stdlib-only, no third-party dependency. Built over a tokenized corpus of `name + description + body` for every locally-installed skill, with field-level boosts so name hits rank above description hits rank above body hits. The index lives in memory, rebuilt on `SkillStore.add_skill()` / `remove_skill()`, and seeded at `SkillStore.from_config()` time.

3. **Score fusion in `MultiRecall._rerank_candidates()`.** Extend `RecallCandidate` with two optional fields — `bm25_score: float | None` and `vector_score: float | None` — populated by the respective strategies. When the same skill appears in both result lists, `_rerank_candidates()` merges them and computes a fused score via reciprocal rank fusion (RRF). The existing `score` field becomes the fused result; the per-strategy scores are retained for debugging and for the `match_type` tag.

4. **Registration and wiring.** `MultiRecall.__init__()` receives `LocalBm25Recall` as a third constructor-arg strategy alongside the existing pair. `SkillGateway.from_config()` builds it automatically. The `.discover()` / `.search()` surfaces do not change — callers opt into the new behavior transparently because the strategy set expands under the hood.

No new CLI surface. No configuration knob required to *turn it on* — it is on whenever `MultiRecall` is constructed. Tuning knobs (`k1`, `b`, field weights, RRF `k`) are defined as module-level constants with inline comments; the open-questions section below calls out which of those we may want to promote into `SkillConfig` eventually.

## Architecture

### High-level flow

```text
     query ──▶ SkillGateway.discover(strategy=MULTI_RECALL)
                              │
                              ▼
                    MultiRecall.search()
                 ┌────────────┼────────────────┐
                 ▼            ▼                ▼
         LocalFileRecall  LocalDbRecall   LocalBm25Recall   (+ RemoteRecall)
           (enumerate)    (vector)        (lexical)
                 │            │                │
                 └────────────┼────────────────┘
                              ▼
               _rerank_candidates()  ──┐
                                       │  merges by name,
                                       │  fuses bm25_score + vector_score
                                       │  via RRF, then applies
                                       │  local-before-remote tier rule
                                       ▼
                         ranked list[SkillManifest]
```

### BM25 index internals

`LocalBm25Recall` owns an instance of a private `Bm25Index` class (same file). The index is a plain Python dict-of-dicts — no external data structure beyond what the stdlib offers.

Core fields on the index:

| Field                | Type                         | Purpose                                                     |
| :------------------- | :--------------------------- | :---------------------------------------------------------- |
| `documents`          | `dict[str, list[str]]`       | Skill name → tokenized body (post-tokenizer, post-lowercase). |
| `name_tokens`        | `dict[str, list[str]]`       | Skill name → tokens from the `name` field only.             |
| `description_tokens` | `dict[str, list[str]]`       | Skill name → tokens from the `description` field only.      |
| `body_tokens`        | `dict[str, list[str]]`       | Skill name → tokens from full SKILL.md body.                |
| `doc_lengths`        | `dict[str, int]`             | Document length used in the BM25 length-normalization term. |
| `avg_doc_length`     | `float`                      | Corpus average, recomputed on rebuild.                      |
| `term_freqs`         | `dict[str, dict[str, int]]`  | Skill name → term → raw frequency in the merged document.   |
| `doc_freqs`          | `dict[str, int]`             | Term → number of documents containing the term.             |
| `n_docs`             | `int`                        | Corpus size.                                                |

Scoring is the canonical BM25 formula:

```text
score(q, d) = Σ_t∈q  IDF(t) * ((f(t, d) * (k1 + 1)) / (f(t, d) + k1 * (1 - b + b * |d|/avgdl)))
```

with `k1 = 1.2` and `b = 0.75` as module defaults. Field boosts are applied **pre-scoring** by concatenating each field's tokens with a repetition factor: the name tokens are repeated `W_NAME = 4` times, description tokens `W_DESC = 2` times, and body tokens `W_BODY = 1` time before being merged into the scoring corpus. This is the simplest weighting scheme that doesn't require a multi-field BM25F implementation.

### Tokenization

Module-level `_tokenize(text: str) -> list[str]`:

1. Normalize to NFKC (handles full-width punctuation etc.).
2. Lowercase.
3. Split on any character that is not a Unicode letter or digit (`re.findall(r"[^\W_]+", text, re.UNICODE)`).
4. Drop tokens shorter than 2 characters.
5. Filter against a small inline stopword list (~30 English function words; call it out in the Open Questions section for review).

This is intentionally language-naive. Memento-Skills' skill corpus is already mostly English; CJK skills (if any arrive) will still tokenize into character runs via the regex and score reasonably under BM25 without stemming. We are not introducing `nltk`, `spacy`, or any lemmatizer — the architectural value of stdlib-only, in the style of MS-DES-0002 and MS-DES-0003, matters more here than marginal recall gains.

### Score fusion — reciprocal rank fusion (RRF)

Given two ranked result lists from `LocalBm25Recall` (length `n_bm25`) and `LocalDbRecall` (length `n_vec`), a skill's fused score is:

```text
RRF(skill) = 1 / (k + rank_bm25(skill)) + 1 / (k + rank_vec(skill))
```

with `k = 60` (the standard default from the original Cormack/Clarke/Büttcher paper). Skills present in only one list contribute that one term; skills missing from both never reach the fusion step. The constant `k` suppresses the tail of each list and prevents a single-list rank-1 from drowning out a cross-list agreement.

RRF was picked over linear combination (`α * bm25 + (1-α) * vec`) for two reasons. (1) It requires no score normalization — raw BM25 scores and cosine similarities live on different scales, and picking a fair `α` would be an ongoing tuning task. (2) It is monotonic in each input rank, which makes debugging easier: if the user sees the wrong result, the per-strategy ranks are human-readable even when the scores aren't.

### Invocation path

No changes to `SkillGateway.discover()` or `.search()` signatures. The only wiring change is inside `SkillGateway.from_config()`:

```python
# Before
multi_recall = MultiRecall(
    strategies=[LocalFileRecall(store), LocalDbRecall(store, llm)],
)

# After
multi_recall = MultiRecall(
    strategies=[
        LocalFileRecall(store),
        LocalDbRecall(store, llm),
        LocalBm25Recall(store),
    ],
)
```

And inside `MultiRecall._rerank_candidates()`, the merge-and-fuse logic replaces the current "sort by `score` desc, local before remote" one-liner. Tier rules stay: remote candidates are never promoted above any local candidate, regardless of fused score.

## Data contract

### `RecallCandidate` — extended

```python
@dataclass
class RecallCandidate:
    name: str
    description: str = ""
    source: Literal["local", "remote"] = "local"
    score: float = 0.0                         # Fused score after _rerank_candidates.
    match_type: str = ""                       # "embedding" | "fulltext" | "exact" | "remote" | "bm25" | "hybrid"
    skill: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # NEW — populated by individual strategies, consumed by fusion step.
    bm25_score: float | None = None
    vector_score: float | None = None
    bm25_rank: int | None = None               # Set during fusion.
    vector_rank: int | None = None             # Set during fusion.
```

Backward compatibility: existing consumers read only `name`, `description`, `source`, `score`, `skill`. New fields default to `None`; adding them cannot break any existing caller.

### `LocalBm25Recall` public API

```python
class LocalBm25Recall(BaseRecall):
    def __init__(self, store: SkillStore) -> None: ...

    async def recall(
        self,
        query: str,
        k: int = 10,
    ) -> list[RecallCandidate]: ...

    def rebuild(self) -> None:
        """Rebuild the in-memory BM25 index from the current skill store contents."""

    def _on_skill_added(self, skill: Skill) -> None: ...
    def _on_skill_removed(self, skill_name: str) -> None: ...
```

`rebuild()` is idempotent and cheap (hundreds of skills, sub-second). The two `_on_*` hooks are wired by `SkillStore` via a lightweight observer callback registry — proposed signature on `SkillStore`:

```python
def add_index_listener(self, listener: Callable[[Literal["add", "remove"], Skill | str], None]) -> None: ...
```

## Constraints

| Constraint                                                                 | Rationale                                                              |
| :------------------------------------------------------------------------- | :--------------------------------------------------------------------- |
| **Stdlib-only in the retrieval strategy**                                  | Matches the precedent from `style_autofix.py` and `doc_freshness_scanner.py`. Pulls in no `rank_bm25`, `whoosh`, `lucene-*`, or `sklearn`. |
| **Pure-Python scoring**                                                    | Corpus size is ~tens to low hundreds of skills. No need for a C-accelerated index. Keeps the dependency graph inspectable. |
| **In-memory index, lazy first-query rebuild acceptable**                   | Startup-time rebuild is ~10ms per skill; first query pays the cost if not yet built. No disk persistence in v1. |
| **No breaking changes to `SkillGateway.discover()` / `.search()` signatures** | External callers must not be forced to opt in. The behavior shift is transparent. |
| **Local-before-remote tier rule preserved**                                | A local skill is always preferable to a remote Market hit, even when the Market's score is higher. Non-negotiable. |
| **Deterministic given the same corpus + query**                            | No randomness in ranking. Makes tests reproducible and user behavior predictable. |
| **Idempotence on rebuild**                                                 | Calling `rebuild()` twice in a row produces the same index. Matches the annotation-walker invariant from MS-DES-0003. |

## Alternatives considered

### Alternative A: third-party `rank_bm25` package

Swap the whole pure-Python implementation for `rank_bm25` (the de-facto lightweight BM25 library on PyPI). Would save ~200 lines of code and some minor correctness risk.

**Rejected.** The Memento-Skills retrieval layer has a clear stdlib-first convention and the BM25 math is short and testable. Introducing a runtime dependency on a third-party lib for something this small doesn't pay its keep, and `rank_bm25` has had two years of little maintenance. The house convention wins.

### Alternative B: built-in FTS5 full-text index

`sqlite-vec` is already loaded; `sqlite3` also ships FTS5 support on every Python we target. Could back the lexical layer on FTS5's built-in BM25 ranker (`rank MATCH bm25()`), keeping the entire retrieval stack inside one SQLite connection.

**Rejected for v1, but worth revisiting.** FTS5's BM25 is well-optimized and real, but: (1) it doesn't expose field-level weighting without schema acrobatics or the `bm25(..., weights)` function with a fixed column count; (2) FTS5's tokenizer is Unicode-but-not-quite — customizing it requires the `fts5` tokenizer C callback, which defeats the stdlib-only stance; (3) keeping the lexical index tightly coupled to SQLite ties the whole pipeline to one storage backend when the store abstraction is explicitly designed to allow others. The pure-Python index is portable across any `SkillStore` implementation. If the corpus grows past a few thousand skills and scoring time becomes a bottleneck, FTS5 is the obvious migration target — flagged under Open Questions.

### Alternative C: keep vector-only retrieval

Do nothing. Rely on embeddings to catch exact-name queries too (modern embedding models are surprisingly good at near-lexical matching).

**Rejected.** The retrospective specifically called this out as the degrading axis past ~20 skills. Dense models drift on rare terms (skill names, doc IDs, slugs) and have no path to surface a body-text keyword that doesn't appear in name+description. The BM25 layer is the standard remedy for exactly this failure mode, and it is cheap. Skipping it defers the fix and guarantees retrieval quality regression as the library grows.

### Alternative D: linear-combination score fusion instead of RRF

`final = α * bm25_norm + (1-α) * vec_norm`, with per-strategy min/max normalization to bring both onto `[0, 1]`.

**Rejected.** Two reasons: (a) requires picking and maintaining `α`; every change to the embedding model or BM25 parameters re-opens the tuning question. (b) min/max normalization is fragile at small corpus sizes — a single outlier skill can compress every other skill's score into a narrow band, which is exactly the "many skills, few results" regime this feature is built for. RRF sidesteps both problems.

## Error handling

| Scenario                                                         | Behavior                                                                  |
| :--------------------------------------------------------------- | :------------------------------------------------------------------------ |
| Empty query (`""`)                                               | `recall()` returns `[]` immediately. No index work.                       |
| Query with only stopwords / only punctuation                     | Tokens list is empty → return `[]`. Matches the empty-query path.         |
| Zero skills in the store                                         | Index rebuild is a no-op. `recall()` returns `[]`.                        |
| Skill with a blank body (SKILL.md is just the YAML front matter) | Name + description still indexed; body contributes zero tokens.           |
| Duplicate skill names (should be prevented upstream)             | Later `add_skill` overwrites the earlier index entry. Log a warning via the store's existing logger. |
| `rebuild()` raises mid-rebuild                                   | Swap-in pattern: build the new index into a local variable first, then atomic-assign. A partial build never becomes the live index. |
| BM25 score is NaN or infinite                                    | Defensive clamp to `0.0` and log at `ERROR`. Should never happen with finite integer term frequencies, but we guard anyway. |
| RRF fusion sees a skill in only one list                         | Contribute the single term. Not an error — the single-list-only skill still ranks, just with a smaller fused score than a cross-list agreement. |
| `_on_skill_added` fires before the strategy is instantiated      | Listener registration is guarded by `if self.bm25_strategy is not None`.  |

## Performance

Ballpark figures on a laptop-class machine, Python 3.11, with the current repo's skill count (~20 skills, roughly 8k tokens of indexable text total):

| Operation                              | Expected cost                                                |
| :------------------------------------- | :----------------------------------------------------------- |
| Cold index rebuild                     | <50 ms for 50 skills; <250 ms for 500 skills.                |
| `recall()` at k=10                     | <5 ms. Dominated by dict lookups and the IDF accumulator.    |
| Incremental add/remove                 | O(1) for the per-document term map; O(V) where V is the skill's token count for the corpus-level `doc_freqs` update. |
| Memory footprint                       | ~200 bytes per indexed term per document. ~8 KB for 50 skills. |

The fusion step is O(n_bm25 + n_vec) per `discover()` call — negligible next to either of the two retrieval passes.

## Acceptance criteria

1. A new file `core/skill/retrieval/local_bm25_recall.py` exists and exports `LocalBm25Recall`.
2. `LocalBm25Recall` subclasses `BaseRecall` and implements `async def recall(query, k=10) -> list[RecallCandidate]`.
3. Every returned `RecallCandidate` has `match_type == "bm25"`, `source == "local"`, and a populated `bm25_score`.
4. `MultiRecall.__init__()` accepts the new strategy positionally without breaking any existing constructor call; the default in `SkillGateway.from_config()` now wires all three local strategies.
5. `RecallCandidate` gains optional fields `bm25_score`, `vector_score`, `bm25_rank`, `vector_rank`. Existing dataclass equality and serialization behavior is preserved (all new fields default to `None`).
6. `MultiRecall._rerank_candidates()` merges candidates by `name`, fuses scores via RRF with `k=60`, and writes the fused score back to the `score` field. `match_type` is updated to `"hybrid"` when a candidate was present in both BM25 and vector results.
7. The local-before-remote tier rule remains in effect: no remote candidate ranks above any local candidate, regardless of fused score.
8. An empty query returns `[]` from `LocalBm25Recall.recall()` without touching the index.
9. Adding a skill via `SkillStore.add_skill()` causes the BM25 index to include that skill on the next `recall()` call. Removing a skill causes it to disappear.
10. Calling `rebuild()` twice in a row produces byte-identical index state (idempotence).
11. Querying for a skill's exact name returns that skill with rank 1 in the BM25 strategy's output.
12. A body-only keyword (a term that appears in SKILL.md body but not in name or description) surfaces the matching skill in the BM25 strategy's top-5 for a corpus of ≤100 skills.
13. Field weighting works as documented: a skill whose name matches the query ranks strictly above a skill where only the body matches, all else equal.
14. Fusion test: a skill present in both BM25 rank-3 and vector rank-3 ranks strictly above a skill present only at BM25 rank-1 for realistic `k=60` RRF scoring (because `1/63 + 1/63 > 1/61`).
15. A new test module at `tests/test_skills/retrieval/test_local_bm25_recall.py` contains at least 15 tests covering: tokenization, empty-query, single-doc corpus, multi-doc ranking, field weighting, add/remove hooks, idempotent rebuild, deterministic output, stopword filtering, NFKC normalization, and fusion behavior.
16. All existing tests under `tests/test_skills/retrieval/` continue to pass unchanged.
17. The style-checker autofix passes cleanly on any new Markdown touched by this change (primarily the design spec and the CHANGELOG entry).
18. `CHANGELOG.md` `[Unreleased]` gains an entry linking to this spec and summarizing the new capability.
19. `docs/.doc-pipeline-log.json` gains a run entry documenting the delivery, mirroring the format used for MS-DES-0002 and MS-DES-0003.
20. The `doc-freshness` scanner, when run after the change lands, classifies every touched doc as fresh.

## Open questions

1. **Tokenization sophistication.** Current proposal: NFKC normalize, lowercase, split on non-letter-or-digit, drop length-1 tokens, drop a ~30-word English stopword list. Alternative: skip stopwords entirely (BM25's IDF term naturally downweights them). *Recommendation: ship with the small stopword list — it keeps rank output cleaner for human inspection during the "is this working?" phase, and removing stopwords later is a one-line change.*

2. **Stopword list source.** If we keep one, where does it live? Inline constant? Sibling `.txt`? *Recommendation: inline module-level `frozenset` with a comment linking to its source (NLTK's english corpus, manually curated). 30 words is small enough that hiding it in a data file costs more in indirection than it saves in line count.*

3. **Field-weighting factors (`W_NAME=4`, `W_DESC=2`, `W_BODY=1`).** Gut-feel defaults. Does the team want a tuning CLI or a config knob? *Recommendation: ship as module-level constants in v1 with an inline comment explaining the intuition (name is the densest signal, body is the weakest per-token). Promote to `SkillConfig` only if real-world queries start landing the wrong way.*

4. **BM25 `k1` / `b` parameters.** Proposed `k1=1.2`, `b=0.75` — the defaults from the canonical paper. *Recommendation: ship with these defaults, module-level constants, documented. No tuning CLI for v1.*

5. **RRF `k` constant.** Proposed `k=60` (Cormack et al.). *Recommendation: ship as-is. This is the single most-used default in the fusion literature and we gain nothing by varying it at small corpus sizes.*

6. **Index persistence (disk-backed vs. in-memory).** In-memory means a ~50 ms startup cost per process that loads the skill store. Disk-backed means a shelf-ish cache file under the user's skill directory and a staleness check on load. *Recommendation: in-memory for v1. Disk persistence is a premature optimization at our corpus size; revisit if cold-start latency becomes a complaint.*

7. **Index rebuild trigger.** Proposed: startup plus add/remove hooks. Alternative: purely lazy — first `recall()` call triggers build, `add_skill` just invalidates. *Recommendation: lazy-with-eager-option. Build is cheap; don't pay the cost during import, but offer an explicit `rebuild()` for callers that want warm-start latency.*

8. **Exposing `bm25_score` / `vector_score` in `SkillManifest` output.** Currently these live on `RecallCandidate`, not on the manifest returned from `discover()`. Some callers (tests, UIs) might want them. *Recommendation: no — `discover()` returns `list[SkillManifest]` by contract, and exposing per-strategy scores in the public return would re-couple the gateway to retrieval internals. Callers who need scores can call the `MultiRecall` directly.*

9. **Future FTS5 migration path.** If corpus growth pushes us past pure-Python's reasonable range, the migration should be a drop-in replacement behind the same `LocalBm25Recall` interface. *Recommendation: document this explicitly in the SKILL's module docstring so the next maintainer sees the intended upgrade path.*

10. **CLI shim for pre-computing or inspecting the index.** A diagnostic `python -m core.skill.retrieval.local_bm25_recall inspect <query>` would help debug rank anomalies. *Recommendation: skip for v1, add under a `tools/` script if and when a rank-debugging need shows up.*

## Deliverable checklist

- [ ] `docs/design/bm25-retrieval-layer.md` — this document, promoted from `Draft` to `Accepted`.
- [ ] `core/skill/retrieval/local_bm25_recall.py` — new strategy class with inline documentation.
- [ ] `core/skill/retrieval/schema.py` — extended `RecallCandidate` with the four new optional fields.
- [ ] `core/skill/retrieval/multi_recall.py` — updated `_rerank_candidates()` with RRF fusion and preserved tier rule.
- [ ] `core/skill/gateway.py` — `SkillGateway.from_config()` wires the third strategy.
- [ ] `core/skill/store/…` — add `add_index_listener()` observer hook (or equivalent), wired by `LocalBm25Recall`.
- [ ] `tests/test_skills/retrieval/test_local_bm25_recall.py` — ≥15 tests, all passing.
- [ ] `tests/test_skills/retrieval/test_multi_recall.py` — extended with at least 3 fusion-behavior tests.
- [ ] `CHANGELOG.md` — `[Unreleased] / Added` entry linking back to this spec.
- [ ] `docs/.doc-pipeline-log.json` — new run entry summarizing the change.
- [ ] `style-checker --check` — clean pass on every touched Markdown file.

## Document history

| Date       | Author | Change                                                                  |
| :--------- | :----- | :---------------------------------------------------------------------- |
| 2026-04-14 | Ryan (via Claude) | Initial draft. Status: Draft. Awaiting review before implementation. |
