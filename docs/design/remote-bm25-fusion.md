# Remote BM25 fusion — design-space exploration

## Document control

| Field               | Value                                                            |
| :------------------ | :--------------------------------------------------------------- |
| **Document ID**     | MS-DES-0010                                                      |
| **Feature Name**    | Remote BM25 strategy for three-list skill-market RRF fusion      |
| **Module Scope**    | `core/skill/retrieval/remote_recall.py`, `core/skill/retrieval/multi_recall.py`, `core/skill/retrieval/schema.py` (client side); Skill Market `skill_retrieval_api` service (server side — out of our control) |
| **Status**          | Draft — design-space only, not yet approved for implementation   |
| **Author**          | Ryan (via Claude / Cowork mode)                                  |
| **Date**            | 2026-04-15                                                       |
| **Reviewers**       | Ryan; pending Market-owner sign-off (see open questions)         |
| **Est. Hours**      | Spec-only for this cycle (~half day drafting). Implementation size depends on which surface shape the Market adopts: ~1 day for Shape A, ~1.5 days for Shape B, ~2 days for Shape C (breaking-change migration included). |
| **Parent Document** | [docs/phase-3-interim-retrospective.md](../phase-3-interim-retrospective.md) — candidate #4 |
| **Related**         | [MS-DES-0004 — local BM25 retrieval layer](./bm25-retrieval-layer.md) (parent of all RRF fusion work) |

## Scope of this document

This is deliberately a **design-space** spec, not an implementation spec. The Phase 3 interim retrospective called out Candidate #4 as the only open item larger than a single-day slot, and identified *"does the Market have a BM25 index surface?"* as the blocker preventing an implementation-ready MS-DES from being written. Rather than invent a Market-side schema to unblock ourselves, this document enumerates the three plausible surface shapes, walks through the client-side consequences of each, and captures the Market-owner decision points as explicit open questions.

The deliverable here is **the decision, not the code**. Once a surface shape is chosen, a follow-up MS-DES (likely MS-DES-0011) will nail down the concrete client-side changes, test plan, and rollout. Everything in the "client-side implications" subsections below is scaffolding for that follow-up, not a commitment.

## Problem statement

The RRF fusion added in MS-DES-0004 combines two local recall strategies — `LocalBm25Recall` (lexical) and `LocalDbRecall` (dense-vector) — into a single ranked list via `RRF(skill) = 1/(RRF_K + rank_bm25) + 1/(RRF_K + rank_vec)` with `RRF_K=60`. The third recall strategy, `RemoteRecall` (`core/skill/retrieval/remote_recall.py`), talks to an external `skill_retrieval_api` microservice over HTTP and returns an opaque fused score per result.

Today's client-server contract for the remote side is:

- `GET /health` — returns `{"embedding_ready": bool, "catalog_size": int, ...}`. There is no `bm25_ready` or equivalent signal.
- `POST /api/v1/search` — takes `{"query": str, "top_k": int}`, returns `{"results": [{"name", "description", "score", ...}]}`. The `score` field is opaque: the client has no way to tell whether it came from the Market's BM25 index, its vector index, a fused combination, or something else entirely.

The consequence is that `MultiRecall._rerank_candidates()` has exactly three lists to work with: local-BM25, local-vector, and remote-opaque. The RRF math in `_apply_fusion()` is already structured to accept `bm25_rank` and `vector_rank` per candidate (via the four optional fields on `RecallCandidate` added in MS-DES-0004), but a remote candidate carries neither — remote hits land with just a `score` and `match_type="remote"`, bypass the fusion stage entirely (the early-return in `_apply_fusion` at `bm25_rank is None and vector_rank is None`), and get tier-sorted via the local-before-remote rule.

This has two observable symptoms:

1. **No lexical reinforcement from the remote side.** A skill that both our local BM25 index and the Market's BM25 index agree on cannot express that joint agreement to the fusion stage, because the Market never tells us its score was BM25-derived. The remote signal is effectively flattened before it reaches RRF.
2. **Local-vs-remote is binary, not graded.** The tier rule is strict: any local candidate beats any remote candidate, regardless of how confidently either signal is. A high-confidence remote-BM25 + remote-vector hit can never outrank a tenuous local-only match. This is by design for the install-state concern (don't show a Market skill ahead of an already-installed local skill), but it prevents remote scores from participating in the per-candidate fusion that MS-DES-0004 made possible.

The retrospective's proposed lever for both symptoms is: extend RRF to fuse *three* lists — local-BM25, local-vector, and remote-BM25 — while keeping the local-before-remote tier rule. That requires the remote service to expose a BM25-identifiable signal. It does not today.

## Proposed solution (surface-shape decision)

Three plausible surface shapes exist. Each is locally consistent. The decision criterion is: **whose migration cost does the design internalize — the Market's, the client's, or existing callers of `/api/v1/search`?**

### Shape A — strategy parameter on the existing endpoint

```http
POST /api/v1/search
{"query": "...", "top_k": 10, "strategy": "bm25"}
```

- Server returns the same response shape as today; the `score` field is understood to be a pure-BM25 score (not a fused one) when `strategy="bm25"` is sent. Omitting `strategy` keeps the current fused/opaque behavior.
- Client calls the endpoint *twice per query*: once with `strategy="bm25"`, once with `strategy="vector"` (or once without the param for the existing fused behavior — see open question 3).
- Migration cost lands on the client (double fan-out, extra latency) and on whoever consumes the `strategy` parameter server-side.
- Backward-compatible for every existing caller of `/api/v1/search`.

**Client-side implications** (scaffolding for the follow-up MS-DES):

- `RemoteRecall.search(query, k)` grows two private helpers or an internal fan-out — `_search_bm25(query, k)` and `_search_vector(query, k)` — returning candidates tagged `match_type="remote_bm25"` and `match_type="remote_vector"`. The public `search()` orchestrates the two calls (likely in parallel via `asyncio.gather`) and returns the union, preserving per-strategy ranks on each candidate.
- `RecallCandidate` gains two new optional fields mirroring MS-DES-0004: `remote_bm25_score`, `remote_vector_score`, `remote_bm25_rank`, `remote_vector_rank`. Four fields, all `None` by default, same discipline as before.
- `MultiRecall._stamp_rank()` learns two new strategy names (`"remote_bm25"` and `"remote_vector"`) and stamps the corresponding rank fields. `_apply_fusion()` extends the RRF sum to up to four terms when all four ranks are present.
- The tier rule is preserved by extending the sort key in `_rerank_candidates()`: local-anything before remote-anything, fused score descending within each tier. No change to `_merge_into_existing`'s tier handling.

**Cost:** client fan-out doubles (two HTTP calls per query instead of one). The Market's CPU cost doubles per query as well, since each call runs one of the two indexes.

**Surface risk:** low. Adding an optional request param to an existing JSON endpoint is the minimal-invasiveness change. No response-schema break. No new endpoint path to version and document.

### Shape B — sibling endpoint

```http
POST /api/v1/search_bm25
{"query": "...", "top_k": 10}
```

- Server grows a second endpoint that runs only the BM25 index and returns a pure-BM25 score. Existing `/api/v1/search` is untouched.
- Client calls both endpoints in parallel (one for BM25, one for vector / the existing fused behavior), same fan-out count as Shape A.
- Migration cost lands on the Market (new endpoint must be designed, shipped, versioned, documented, tested, monitored).
- Backward-compatible for every existing caller.

**Client-side implications:** identical to Shape A except the URL dispatch. Same four new fields on `RecallCandidate`, same `_stamp_rank` extension, same `_apply_fusion` extension.

**Cost:** server grows a new endpoint path to maintain, but each call exercises exactly one index (no double-CPU cost per request as in Shape A's shared endpoint — the Market can cache index warm-up separately per endpoint).

**Surface risk:** medium. Second endpoint invites version skew: `/api/v1/search` could evolve while `/api/v1/search_bm25` lags, or vice versa. Requires an explicit versioning policy ("both endpoints move together at major-version rev") to avoid confusion.

### Shape C — multi-field response on the existing endpoint

```http
POST /api/v1/search
{"query": "...", "top_k": 10}

200 OK
{
  "results": [
    {
      "name": "skill-x",
      "description": "...",
      "bm25_score": 3.41,
      "bm25_rank": 1,
      "vector_score": 0.82,
      "vector_rank": 3
    },
    ...
  ]
}
```

- Server runs both indexes (as it likely does today to compute the current opaque `score`), and returns the per-strategy score *and* rank for every result — symmetrical with the local side.
- Client calls the endpoint *once* per query. No fan-out.
- Migration cost lands on existing callers: the response-shape change is breaking. A caller reading `result["score"]` directly needs to know the field is gone / renamed / derived-from.
- Requires a Market-side version bump (e.g., `/api/v2/search`) or a feature-flag period where both shapes ship.

**Client-side implications:** simplest client code. `RemoteRecall.search()` stays a single HTTP call. The mapping from the response into `RecallCandidate` populates four new fields directly: `remote_bm25_score`, `remote_vector_score`, `remote_bm25_rank`, `remote_vector_rank`. `_stamp_rank` still needs to learn `"remote"` means "populate whichever fields are non-null on the candidate" instead of stamping a single strategy.

**Cost:** breaking response-schema change. Every existing caller — including tools outside `memento-skills` that hit the same Market — has to migrate. The Market's CI and compat-testing surface grows.

**Surface risk:** highest. A breaking change at the API boundary is not reversible once downstream consumers cut over. It should only be adopted if the Market owner has an explicit "we're going to version the API anyway" plan.

## Recommendation (if a decision has to be made today)

If the Market owner is the same team / code path as `memento-skills` and a breaking response-schema change is acceptable, **Shape C** is the lowest long-run client complexity and best symmetry with MS-DES-0004's local fusion.

If the Market is a separate system with other consumers, **Shape A** is the minimum-invasiveness path. It doubles client fan-out but preserves every existing response contract, requires no endpoint-versioning policy, and the server change is a single optional request parameter.

**Shape B** is a reasonable compromise only if the Market's team explicitly prefers endpoint-per-strategy for operational or caching reasons (e.g., separate index warm-up metrics, separate rate-limit buckets). It has no advantage over A or C that isn't operational.

This recommendation is contingent on open question 1 below. If it turns out the Market owner has already settled on a surface shape (or has constraints we don't know about), that answer wins and this section is moot.

## Alternatives considered

### Alternative A — dual-remote client shim

Call the existing `/api/v1/search` endpoint twice with different top-`k` values or query variants, and treat the two result lists as if they were BM25 and vector lanes. Rejected because: (a) the Market's fused score is opaque, so there is no way to map two calls of the same endpoint to distinct strategy signals; (b) it invents a BM25-vs-vector distinction that doesn't exist in the response, which is the exact anti-pattern the user's "do not make up undocumented features" rule is meant to prevent; (c) it burns double the Market's CPU for strictly zero informational gain over a single call.

### Alternative B — use remote `score` as a BM25 proxy

Relabel the existing opaque `score` as `remote_bm25_score` and feed it into `_apply_fusion` as the remote BM25 rank, with no Market-side change required. Rejected because the opaque score isn't a BM25 score — it's whatever the Market's fused/ranked output produces today. Feeding a fused-hybrid score into RRF as if it were lexical-only double-counts the vector signal: the Market's internal vector hit influences both the "remote_bm25_rank" term *and* (transitively, via whatever fusion it already did) the effective ordering. Fusion math expects strategy-independent rank signals; this violates that assumption.

### Alternative C — drop the local-before-remote tier rule

Let remote candidates fuse directly with local ones on a unified score scale. Rejected because the tier rule isn't about score quality — it's about install state. A local skill is runnable today; a remote skill requires an install step. Showing a remote skill ahead of a local one in the discovery UI creates a friction spike the tier rule intentionally prevents. This alternative is out of scope regardless of which surface shape is chosen; the three-list fusion must preserve the tier rule.

### Alternative D — mirror the remote catalog locally and run BM25 over the mirror

Pull the Market's catalog periodically, mirror `name + description + body` (or whatever subset is public) into a local BM25 index, and run that index at query time. The client never asks the Market for BM25 because it has its own. Rejected because: (a) the mirror is a second source of truth that can drift from the Market's canonical state; (b) catalog size on the Market may be large enough that a full mirror is prohibitive (we'd have to truncate, which biases the index); (c) copyright / ToS implications of mirroring third-party skill metadata are out of scope for a retrieval spec; (d) this reintroduces the exact MS-DES-0003-shaped "local index of something we don't control" anti-pattern the doc-freshness relevance filter rejected on the docs-side.

### Alternative E — wait indefinitely for the Market owner

The retrospective's original disposition. Rejected for this cycle because (a) the spec itself can be written against a concrete decision tree without blocking on the answer, and (b) having the spec on hand accelerates the implementation-day turnaround once the answer arrives. This MS-DES *is* the "waiting" output in docs-first form.

## Open questions

These must be resolved before the follow-up implementation MS-DES can proceed.

1. **Who owns the `skill_retrieval_api` service, and are they willing to accept one of Shape A / B / C?** The retrospective called this out as "the blocker." Without a yes from the Market owner on a specific shape, the client-side code is speculative. The cheapest path is probably a ~30-minute sync with the Market owner to get a direct answer. Failing that, written confirmation in a linked issue / RFC channel is sufficient.
2. **If Shape A is chosen, what does `strategy` default to when omitted?** Two sub-options: (a) keep today's fused/opaque behavior (safest for existing callers), or (b) make `"bm25"` the default and require `"vector"` or `"fused"` to be explicit. Default (a) is strongly preferred for backward compatibility; (b) is only defensible if the Market has no existing callers beyond `memento-skills`.
3. **If Shape A or B is chosen, is the Market prepared for double query volume?** Fan-out doubles per-query CPU on the Market. If the Market is rate-limit-gated or cost-sensitive, the client may need to cap fan-out or fall back to single-strategy mode under load. This is a capacity question, not a design question, but it affects the rollout plan.
4. **If Shape C is chosen, what's the deprecation window for the existing response shape?** A breaking API change needs a concrete timeline (e.g., "both shapes co-exist for 30 days, then `score` goes away"). The client's migration is cheap; the risk is outside-`memento-skills` callers.
5. **How does the Market identify when its BM25 index is unhealthy (empty, corrupt, lagging the vector index)?** The local side uses `embedding_ready` in `GET /health`. An analogous `bm25_ready` signal is required on the remote side so the client can degrade gracefully — skip the remote-BM25 lane and fall back to the two-list fusion when the remote BM25 is unavailable. Applies to all three shapes.
6. **Is there a reason to treat remote-BM25 and local-BM25 as a *single* merged BM25 signal inside RRF rather than two independent signals?** E.g., if the Market's catalog and the local catalog overlap substantially, a skill that lands at rank 2 locally and rank 2 remotely gets two high-rank terms in the fused score, which may over-weight it. This is a fusion-math tuning question; the current proposal treats them as independent (four terms in the RRF sum, up from two) and relies on top-`k` truncation to keep things bounded. Worth empirical testing once implementation lands; not a blocker.

## Acceptance criteria (for the spec itself)

The deliverable of this cycle is the document you are reading. Its acceptance criteria are:

1. The three surface shapes are fully enumerated with concrete HTTP request / response snippets, not hand-waved.
2. Each surface shape has a client-side implications subsection listing the concrete files and functions that would change, sized to "the follow-up MS-DES can be written in under a day once a shape is chosen."
3. The recommendation section states a preferred shape with an explicit contingency clause (the Market-owner answer).
4. At least five alternatives are considered and rejected, covering the obvious misreads (reuse opaque score, drop tier rule, mirror the catalog, etc.).
5. At least five open questions are captured, tagged for Market-owner resolution where applicable.
6. The spec is unambiguous about what is *not* included: no implementation code, no test plan, no CHANGELOG-grade user-facing description, no Market-side schema commitment.
7. The spec follows the house-style MS-DES format (document-control table, problem statement, proposed solution, alternatives, open questions, acceptance criteria, out-of-scope sections) so it can slot into `docs/design/` alongside MS-DES-0003 through MS-DES-0009 without stylistic friction.

## Out of scope

- Any client-side code changes. This is spec-only for this cycle.
- Any server-side schema commitment. The three shapes are proposals, not contracts.
- Test plans for the eventual client-side changes. Those belong in the follow-up MS-DES once a shape is chosen.
- Changes to `RRF_K`, the tier rule, or the two-list fusion already shipped in MS-DES-0004. Three-list fusion extends that math; it does not change the constants or the tier rule.
- Catalog-mirroring, offline-mode, or degraded-mode behaviors beyond the minimal "remote BM25 lane skipped when unavailable" fallback mentioned in open question 5.
- Rewriting existing callers of `/api/v1/search` outside `memento-skills`. If Shape C is chosen, a separate migration note addresses them.
- Telemetry or diagnostics to compare pre- and post-three-list-fusion ranking quality. Worth doing, but it depends on an existing ranking-quality eval harness that isn't in this repo today and would itself be MS-DES-grade scope.

## Path forward

1. **Now.** This spec lands in `docs/design/` and is stamped in CHANGELOG as a Phase 3 design-space deliverable. No code changes.
2. **Blocker resolution.** Ryan raises open question 1 with the Market owner. Expected outcome: a chosen surface shape (A, B, or C), or an "indefinitely unavailable" answer that would reroute the work to Alternative D's catalog-mirror idea (out of scope today).
3. **Follow-up MS-DES (likely MS-DES-0011).** Once a shape is chosen, a new spec nails down the concrete client-side code, test plan, error-handling matrix (ties into open question 5), and rollout. Size estimates per shape are in the document-control block's Est. Hours row.
4. **Implementation.** The follow-up spec's acceptance criteria drive the code cycle. By that point, the design-space question is settled and the work is mechanical.

This path explicitly optimizes for docs-first discipline: produce the artifact that moves the decision forward today, even when the implementation itself is blocked on an external answer.
