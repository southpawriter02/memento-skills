# BM25 shared primitives — canonical RRF_K and a cross-module parity tripwire — MS-DES-0013

- **Status:** Proposed — 2026-08-06
- **Supersedes:** —
- **Superseded-by:** —
- **Related:** MS-DES-0004 (local BM25 retrieval layer — introduced both copies of `RRF_K`), MS-DES-0009 (doc-freshness relevance v2 — introduced the deliberate tokenizer port), MS-DES-0011 (reserved: remote BM25 implementation — will extend the RRF sum to more terms).
- **Surfaced in:** `docs/analysis/candidate-6-cycle-closure.md` §"Cross-cycle observations" (the `RRF_K` duplicate-constant observation, logged as cycle-1b finding 5 and left unfixed as out of scope for a doc cycle), and `docs/design/rule-3-1-abbreviation-non-terminators.md` §"Out of scope" line 129, which defers it explicitly to "a future BM25 shared-primitives consolidation MS-DES."

## Problem

The BM25 surface has two duplications. They look alike and are not alike, and the difference determines the fix.

### Problem 1 — `RRF_K` is declared twice, and the copy documented as canonical is dead

`core/skill/retrieval/local_bm25_recall.py:82` declares the constant with this comment:

> Reciprocal Rank Fusion constant (Cormack, Clarke, Büttcher 2009). Not used by this module directly — exposed here so `multi_recall.py` can import a single canonical value.

`core/skill/retrieval/multi_recall.py:57` declares it again:

> Reciprocal Rank Fusion constant. Mirrors the value in `local_bm25_recall.py` — imported indirectly rather than via star-import to keep module-boundary dependencies explicit.

Neither comment describes the code. There is no import in either direction; both files bind an independent integer literal. A repo-wide grep for consumers of `local_bm25_recall.RRF_K` returns nothing:

- it is not read anywhere in its own module (the comment says so outright),
- it is not re-exported by `core/skill/retrieval/__init__.py`, which exports only the five strategy and schema classes,
- it is not imported by any test.

The only live constant is `multi_recall.RRF_K`, read twice inside `_apply_fusion` (`multi_recall.py:394` and `:396`) and imported directly by three tests in `tests/test_skills/retrieval/test_multi_recall.py` (lines 224, 234, 247).

**The failure mode is specific.** A maintainer retuning fusion damping reads `local_bm25_recall.py`, finds a constant whose comment declares it the single canonical value, edits `60` to something else — and observes no behavior change whatsoever, with the entire suite still green. The defect is the comment; the duplicate literal is only how it hides. Documented-but-false single-sourcing is worse than visible duplication, because it actively directs the reader to the wrong file.

Ownership is inverted as well. Reciprocal rank fusion is a property of the fusion stage, not of the lexical strategy. A constant used only by `MultiRecall` living in `LocalBm25Recall` was already an odd placement in MS-DES-0004; the dead declaration makes it indefensible.

### Problem 2 — the `doc_importance` port is guarded only against its own drift, not upstream's

MS-DES-0009 deliberately ported `_tokenize`, `_TOKEN_RE`, `STOPWORDS`, `BM25_K1`, `BM25_B`, and `MIN_TOKEN_LENGTH` from `local_bm25_recall.py` into `skills/doc-freshness/scripts/doc_importance.py` rather than importing them, to preserve the invariant that scripts under `skills/*/scripts/` are stdlib-only and importable in isolation. **That decision stands and this document does not reopen it.**

What does not stand is the claimed guard. `skills/doc-freshness/scripts/test_doc_importance.py` opens with:

> `_tokenize` parity with `core/skill/retrieval/local_bm25_recall._tokenize` (AC #3) — we test against the upstream canary strings to guard against accidental divergence as either copy evolves.

and the class `TestTokenizerParity` is named for the same claim. But every assertion in that class compares `doc_importance._tokenize` against a hardcoded literal list. The upstream module is never imported, so "as either copy evolves" is exactly the case the tests cannot see.

Concretely: add one word to `local_bm25_recall.STOPWORDS`, or change `MIN_TOKEN_LENGTH` from `2` to `3`, and all 26 `doc_importance` tests pass, the retrieval suite passes, and the two tokenizers now disagree. Doc importance scores drift away from skill retrieval scores with no signal anywhere.

Deliberate duplication does not need consolidating. It needs an alarm.

## Constraints

- **Stdlib only** under `skills/*/scripts/`, per the house rule.
- **`doc_importance.py` stays importable in isolation** (MS-DES-0009 invariant). The tripwire therefore *cannot* live in `test_doc_importance.py`, because that file must never import `core.*`.
- **No behavior change.** `RRF_K` remains `60`; fusion output must be bit-identical before and after.
- **Additive.** No existing test is modified or deleted.
- **The tripwire must name its own remedy.** A failure four months from now should tell the reader what to do without requiring them to reconstruct this document.
- **No new module for one constant.** House style rejects indirection at this repo size — see MS-DES-0004 open question 2 (stopword list stays inline) and MS-DES-0007 rejected alternative A (`PROPER_NOUNS` stays in-module).

## Proposed solution

Two independent changes, deliberately shipped together because they are the same observation at two altitudes: a shared value with no enforcement of its sharing.

### Part 1 — make `multi_recall.py` the canonical home for `RRF_K`

Delete the dead declaration from `local_bm25_recall.py` and leave a pointer in its place:

```python
#: Reciprocal Rank Fusion is a property of the fusion stage, not of this
#: strategy. The canonical ``RRF_K`` lives in ``multi_recall.py``; this
#: module does not consume it. See MS-DES-0013.
```

Correct the comment in `multi_recall.py` to describe what the code actually does:

```python
#: Reciprocal Rank Fusion constant (Cormack, Clarke & Büttcher 2009).
#: Canonical and sole declaration — see MS-DES-0013. ``_apply_fusion`` is
#: the only consumer; tests import it from here.
RRF_K: int = 60
```

**Direction of the fix.** The existing comments point the other way (strategy owns it, fusion imports it), so it is worth stating why the direction is reversed:

1. `MultiRecall` is the only consumer, and the tests already import from `multi_recall`. Reversing would require editing three passing tests for no gain.
2. `local_bm25_recall` importing from `multi_recall` would be circular. `multi_recall` imports `LocalBm25Recall` lazily *inside* `from_config` (`multi_recall.py:98`) precisely to avoid that cycle; a module-level back-import would reintroduce it.
3. RRF is fusion vocabulary. When MS-DES-0011 lands remote BM25, the RRF sum grows more terms — all of them in `_apply_fusion`, none of them in a strategy module.

`docs/api/skill-retrieval.md` §"Key constants" documents `RRF_K` without saying where it lives; it gains a canonical-home pointer in the same change, so the next reader looking for the constant is sent to the one file that binds it.

`docs/analysis/candidate-6-cycle-closure.md` — where the duplication was originally observed — is deliberately **not** edited. It is a dated findings record of what a review cycle surfaced on 2026-04-15, and rewriting it to say the finding is closed would falsify the record. Closure is recorded forward, in the CHANGELOG and the pipeline log, not backward.

### Part 2 — a parity tripwire in the pytest suite

New file `tests/test_skills/retrieval/test_bm25_parity.py`. It lives in the pytest suite rather than the skill's stdlib suite because it is the one place that may legitimately import both sides: `tests/` already has the repo root importable and pytest available, while `skills/*/scripts/` may not reach into `core/`.

It puts `skills/doc-freshness/scripts` on `sys.path`, imports both modules, and asserts three things.

**Group 1 — tuning-constant parity.** Five shared symbols, one assertion each:

| Symbol | Upstream | Port | Contract |
|--------|----------|------|----------|
| `BM25_K1` | `local_bm25_recall` | `doc_importance` | equal |
| `BM25_B` | `local_bm25_recall` | `doc_importance` | equal |
| `MIN_TOKEN_LENGTH` | `local_bm25_recall` | `doc_importance` | equal |
| `STOPWORDS` | `local_bm25_recall` | `doc_importance` | equal as sets |
| `_TOKEN_RE.pattern` | `local_bm25_recall` | `doc_importance` | equal |

**Group 2 — tokenizer output parity.** A single shared corpus, table-driven, asserting `local_bm25_recall._tokenize(s) == doc_importance._tokenize(s)` element-for-element for at least twelve strings spanning: plain English, stopword-heavy English, CJK runs, mixed Latin/CJK, underscore splitting, hyphenation, version literals (`v0.3.0`), dotted file paths, an `MS-DES-NNNN` identifier, single-character tokens, the empty string, and `None`.

The corpus is shared rather than duplicated per side — the assertion compares two live functions on one input, which is the property the hardcoded canaries cannot express.

**Group 3 — one declaration of `RRF_K`.** A regression guard that reads the two source files and asserts exactly one binding assignment of `RRF_K` exists across `core/skill/retrieval/`, so Part 1 cannot silently regress.

**What is explicitly not asserted.** Scoring parity between `Bm25Index` and `DocBm25Index` is *out of contract*, and the test file says so in a module docstring paragraph. The port is a deliberate simplification: `DocBm25Index` has no field weighting (`W_NAME` / `W_DESC` / `W_BODY` do not exist there), and the corpus unit is a Markdown document rather than a `SKILL.md` triple. Asserting score equality would either fail on the first run or force the two implementations to converge — which is precisely the consolidation this document rejects. The contract is narrow and deliberate: **same tokens in, same tuning constants; the scoring layers above them may differ.**

**Failure messages.** Every assertion carries a message naming both file paths and the two legitimate remedies — sync the port, or amend the contract table in this document in the same commit. That makes intentional divergence a reviewable act rather than a silent one.

## Rejected alternatives

1. **Collapse `DocBm25Index` and `Bm25Index` into a shared module imported by both.** The obvious reading of "shared-primitives consolidation," and wrong. It reopens MS-DES-0009's decision, breaks the stdlib-only self-contained invariant for `skills/*/scripts/`, and makes a documentation skill depend on the agent framework's retrieval internals. The duplication is a deliberate purchase; this document buys the missing insurance rather than returning the goods.
2. **Move `RRF_K` and the BM25 constants to a new `core/skill/retrieval/constants.py`.** A whole module for one live constant. Consistent with neither MS-DES-0004 open question 2 nor MS-DES-0007 alternative A, both of which rejected indirection at this size. Revisit only if a second constant genuinely needs sharing.
3. **Keep `RRF_K` in `local_bm25_recall` and have `multi_recall` import it.** Honors the existing comments, but leaves fusion vocabulary owned by a strategy module, forces edits to three currently-passing tests, and points a module-level import at a module that is deliberately imported lazily to avoid a cycle.
4. **Have `doc_importance` try to import from `core`, falling back to its local copy on `ImportError`.** Worst of both: two code paths, behavior dependent on `sys.path`, and the fallback path — the one that actually runs in the isolated case the invariant exists to protect — is exactly the one that drifts unobserved.
5. **Put the tripwire in `test_doc_importance.py` with a `sys.path` walk up to the repo root.** Breaks the skill suite's isolation guarantee: running `python skills/doc-freshness/scripts/test_doc_importance.py` outside a full checkout would start failing on imports of `pydantic` and friends, pulled in transitively by `core.skill.loader`.
6. **Generate the ported constants into `doc_importance.py` from upstream at build time.** There is no build step. Adding one to synchronize about twenty lines of constants is a large new moving part bought with a small problem.
7. **Do nothing; rely on code review to catch drift.** The `RRF_K` observation has now been written down twice — in the candidate-6 cycle-closure findings and in MS-DES-0012's out-of-scope list — and survived both. Two logged observations and no fix is the evidence that review is not the mechanism that closes this.

## Acceptance criteria

- `local_bm25_recall.py` no longer declares `RRF_K`; a pointer comment names `multi_recall.py` as canonical and cites MS-DES-0013.
- `multi_recall.py` comment states sole ownership. Value unchanged at `60`.
- Exactly one binding assignment of `RRF_K` remains under `core/`.
- New `tests/test_skills/retrieval/test_bm25_parity.py` with **at least 8 tests**.
- Constant-parity assertions cover all five symbols in the Part 2 contract table.
- Tokenizer-parity assertions cover **at least 12 shared corpus strings**, compared function-to-function rather than against literals.
- A regression test guards the single-declaration property from Part 1.
- Scoring parity is explicitly documented as out of contract in the test module docstring.
- Existing suites pass unchanged: `tests/test_skills/retrieval/` (pytest), 26 `test_doc_importance.py`, 55 `test_style_autofix.py`.
- Fusion behavior is unchanged — `test_multi_recall.py`'s three RRF arithmetic tests pass without edits.
- `docs/api/skill-retrieval.md` §"Key constants" gains a canonical-home pointer for `RRF_K`.
- `docs/analysis/candidate-6-cycle-closure.md` left unedited — closure is recorded forward, not by rewriting a dated findings record.
- Style-checker `--check` reports 0 findings on this spec.
- CHANGELOG `[Unreleased]` gains an Added entry naming MS-DES-0013 and citing the test count.
- Pipeline log gains a run entry.

## Path forward after this MS-DES

MS-DES-0011 (remote BM25) extends the RRF sum to three or four terms depending on which Market surface shape is chosen. Single-sourcing `RRF_K` first means that work adds terms to one arithmetic site instead of negotiating with a second stale copy — a small precondition, but one that gets more expensive to establish later.

The Part 2 contract table is the amendment surface. If a future change makes the two tokenizers legitimately diverge — say `doc-freshness` wants a docs-specific stopword list — the correct move is to edit the table and the tripwire in the same commit as the divergence. That converts a silent drift into a reviewed decision, which is the entire point.

If a *second* constant ever needs sharing across `core/` and `skills/*/scripts/`, rejected alternative 2 becomes worth revisiting on its own merits.

## Out of scope

- Consolidating the two BM25 index implementations (rejected alternative 1). The MS-DES-0009 port decision stands.
- Adding field weighting to `DocBm25Index`. It is simplified on purpose.
- Retuning `RRF_K`, `BM25_K1`, or `BM25_B`. MS-DES-0004 open questions 3 through 5 stand: ship the canonical defaults, promote to config only when real queries land wrong.
- Remote BM25 fusion (MS-DES-0010 / MS-DES-0011). Still blocked on the Market-owner surface-shape decision; unaffected by this change beyond the precondition noted above.
- The translation-pass backlog on `core/skill/retrieval/` (30 non-target or mixed-script docstrings). Adjacent to these files but a separate piece of work.
