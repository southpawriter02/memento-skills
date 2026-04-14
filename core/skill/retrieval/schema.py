"""retrieval/schema.py — 检索层数据模型

Data contracts for the retrieval layer.

This module defines the shared shape returned by every recall strategy and
consumed by the fusion step inside ``MultiRecall``. Keeping the contract tight
here lets us add new strategies — such as the ``LocalBm25Recall`` introduced
by MS-DES-0004 — without touching downstream consumers.

Schema evolution history:

* Initial — ``name``, ``description``, ``source``, ``score``, ``match_type``,
  ``skill``, ``metadata``.
* MS-DES-0004 (2026-04-14) — added four optional fields to carry per-strategy
  signals into the fusion stage: ``bm25_score``, ``vector_score``,
  ``bm25_rank``, ``vector_rank``. All default to ``None`` so older producers
  and consumers are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class RecallCandidate:
    """A unified record returned by any recall strategy.

    Used by local retrieval, remote retrieval, and the multi-recall merger
    that sits in front of them. Every strategy emits a list of these; the
    fusion step inside ``MultiRecall._rerank_candidates`` combines them into
    a single ranked output.

    Attributes:
        name: Skill name (stable identifier across strategies).
        description: Human-readable description (copied from the
            ``SkillManifest`` when available).
        source: ``"local"`` for anything produced by an on-disk strategy;
            ``"remote"`` for cloud Market hits.
        score: The *effective* ranking score. Pre-fusion this is the
            strategy's own score; post-fusion (after ``_rerank_candidates``)
            this holds the fused score derived via reciprocal rank fusion.
        match_type: Strategy tag — ``"embedding"``, ``"local_file"``,
            ``"bm25"``, ``"remote"``, etc. After fusion, becomes
            ``"hybrid"`` when the candidate was surfaced by both a lexical
            and a vector strategy.
        skill: The full ``Skill`` object for local candidates; ``None`` for
            remote candidates that have not yet been installed.
        metadata: Loose bag of extra fields carried through from the
            underlying strategy (e.g., remote-strategy download URL).
        bm25_score: BM25 score assigned by ``LocalBm25Recall`` (absolute,
            un-normalized). ``None`` when the candidate did not come out of
            a lexical index.
        vector_score: Cosine similarity score from the vector strategy.
            ``None`` when the candidate did not come out of the vector
            index. The value is expressed as a similarity
            (``1.0 - distance``) to mirror the existing convention.
        bm25_rank: 1-indexed rank of this candidate within the BM25
            strategy's output. Filled in during fusion; ``None`` if the
            candidate did not appear in the BM25 result list.
        vector_rank: 1-indexed rank within the vector strategy's output.
            Filled in during fusion.

    Notes:
        The four optional fields are consumed by the RRF fusion path
        described in ``docs/design/bm25-retrieval-layer.md`` (MS-DES-0004).
        Callers that only read ``name`` / ``score`` behave exactly as
        before.
    """

    name: str
    description: str = ""
    source: Literal["local", "remote"] = "local"
    score: float = 0.0
    match_type: str = ""
    skill: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # --- MS-DES-0004 additions — fusion-stage inputs / diagnostics --------
    # These are deliberately optional so every existing producer (local_file,
    # local_db, remote) keeps working without modification. Populated only by
    # strategies that know how to fill them in.
    bm25_score: float | None = None
    vector_score: float | None = None
    bm25_rank: int | None = None
    vector_rank: int | None = None
