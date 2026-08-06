"""multi_recall — 多路召回合并器 / Multi-recall merger.

Manages multiple recall strategies, executes them in parallel, and merges
their results into a single ranked list.

Fusion behavior (MS-DES-0004):

* The strategy list may contain any mix of ``LocalFileRecall``,
  ``LocalDbRecall``, ``LocalBm25Recall``, and ``RemoteRecall``.
* When the same skill appears in both the BM25 and the vector strategy's
  output, the two per-strategy scores are fused into a single effective
  score via reciprocal rank fusion (RRF):

      RRF(skill) = 1 / (k + rank_bm25) + 1 / (k + rank_vec)

  with ``k = RRF_K = 60`` (Cormack, Clarke & Büttcher 2009).
* The local-before-remote tier rule is preserved: remote candidates can
  never rank above any local candidate, regardless of fused score. This
  is a hard invariant — it protects against a noisy cloud ranker
  displacing a good local hit.
* Strategies that are not BM25 or vector (``local_file``, ``remote``)
  retain their existing behavior. Their ``score`` feeds the sort within
  their tier only.

Example usage::

    from core.skill.retrieval import (
        MultiRecall, LocalFileRecall, LocalDbRecall,
        LocalBm25Recall, RemoteRecall,
    )

    recalls = [
        LocalFileRecall(skills_dir),
        LocalDbRecall(db_path, embedding_client),
        LocalBm25Recall(skills_dir),
        RemoteRecall(base_url),
    ]
    multi = MultiRecall(recalls)
    candidates = await multi.recall("changelog writer", k=10)
"""

from __future__ import annotations

import asyncio

from utils.logger import get_logger

from .base import BaseRecall
from .schema import RecallCandidate

logger = get_logger(__name__)


#: Reciprocal Rank Fusion constant (Cormack, Clarke & Büttcher 2009).
#: Canonical and sole declaration — see MS-DES-0013. ``_apply_fusion`` is the
#: only consumer; tests import it from here. When MS-DES-0011 lands remote
#: BM25, the extra RRF terms are added in ``_apply_fusion``, not in a
#: strategy module.
RRF_K: int = 60


class MultiRecall:
    """Parallel-dispatch, rank-fusing recall orchestrator.

    Args:
        recalls: An ordered list of recall strategies. Ordering is used
            only as a tiebreaker in the existing dedup pass — the fusion
            step does its own ranking.
    """

    def __init__(self, recalls: "list[BaseRecall] | None" = None):
        self._recalls = recalls or []

    @classmethod
    def from_config(cls, config: "SkillConfig") -> "MultiRecall":
        """Build a ``MultiRecall`` with every available local strategy.

        Wires (in order):

        1. ``LocalFileRecall`` — always available if the skills directory
           exists. Provides the enumerate-all baseline.
        2. ``LocalDbRecall`` — available when the embedding client and
           ``sqlite-vec`` are both reachable.
        3. ``LocalBm25Recall`` — always available if the skills directory
           exists. Provides the lexical BM25 layer. [MS-DES-0004]
        4. ``RemoteRecall`` — available when a cloud catalog URL is
           configured.

        Args:
            config: Runtime ``SkillConfig``.

        Returns:
            A ``MultiRecall`` with the strategy list populated.
        """
        recalls: list[BaseRecall] = []

        # Keep local imports — the ``LocalDbRecall`` module imports sqlite-vec
        # at top level and we do not want a cold import-time dependency here.
        from .local_file_recall import LocalFileRecall
        from .local_bm25_recall import LocalBm25Recall
        from .remote_recall import RemoteRecall

        # LocalFileRecall — enumerate everything, score=1.0.
        file_recall = LocalFileRecall.from_config(config)
        if file_recall.is_available():
            recalls.append(file_recall)

        # LocalDbRecall — vector search. Optional.
        try:
            from .local_db_recall import LocalDbRecall

            db_recall = LocalDbRecall.from_config(config)
            if db_recall.is_available():
                recalls.append(db_recall)
        except Exception:
            pass

        # LocalBm25Recall — lexical BM25. [MS-DES-0004]
        bm25_recall = LocalBm25Recall.from_config(config)
        if bm25_recall.is_available():
            recalls.append(bm25_recall)

        # RemoteRecall — cloud Market. Optional.
        remote_recall = RemoteRecall.from_config(config)
        if remote_recall:
            recalls.append(remote_recall)

        return cls(recalls)

    # -------------------------------------------------------------------------
    # Strategy registry helpers
    # -------------------------------------------------------------------------

    def add_recall(self, recall: "BaseRecall") -> None:
        """Append a strategy to the dispatch list."""
        self._recalls.append(recall)

    def remove_recall(self, name: str) -> bool:
        """Remove a strategy by name.

        Args:
            name: The strategy's ``.name`` property value.

        Returns:
            ``True`` if a strategy was removed, ``False`` otherwise.
        """
        for i, r in enumerate(self._recalls):
            if r.name == name:
                self._recalls.pop(i)
                return True
        return False

    def get_available_recalls(self) -> list["BaseRecall"]:
        """Return every registered strategy whose ``is_available()`` is True."""
        return [r for r in self._recalls if r.is_available()]

    def get_recall_by_type(self, recall_type: type) -> "BaseRecall | None":
        """Locate a strategy by class."""
        for recall in self._recalls:
            if isinstance(recall, recall_type):
                return recall
        return None

    # -------------------------------------------------------------------------
    # Public retrieval surface
    # -------------------------------------------------------------------------

    async def recall(
        self,
        query: str,
        k: int = 10,
        per_recall_k: int | None = None,
        source_filter: str | None = None,
        **kwargs,
    ) -> list[RecallCandidate]:
        """Execute multi-path retrieval and return a fused ranked list.

        Runs every available strategy in parallel, merges by skill name,
        fuses BM25 + vector scores via RRF, and applies the
        local-before-remote tier rule.

        Args:
            query: Search query string.
            k: Maximum number of results to return.
            per_recall_k: Optional per-strategy result cap. Defaults to
                ``k`` — each strategy is asked for up to ``k`` results so
                the merge has enough material to rank.
            source_filter: ``"local"`` or ``"remote"`` to filter by
                candidate source. ``None`` applies no filter.
            **kwargs: Forwarded to each strategy's ``search`` method.

        Returns:
            A list of ``RecallCandidate`` sorted by fused score with the
            tier rule enforced, truncated to ``k`` entries.
        """
        per_k = per_recall_k or k
        available_recalls = self.get_available_recalls()

        if not available_recalls:
            logger.warning("[MULTI_RECALL] No available recall strategies")
            return []

        # Dispatch in parallel. return_exceptions=True ensures a single
        # strategy failure does not sink the whole call.
        tasks = [
            self._safe_search(r, query, per_k, **kwargs) for r in available_recalls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # -----------------------------------------------------------------
        # Step 1 — dedup-merge across strategies into a single dict keyed
        # by skill name. During merge we:
        #
        # * stamp each per-strategy rank onto the accumulated candidate
        #   (used later for RRF fusion);
        # * prefer local over remote when the same name shows up in both;
        # * preserve the first-local-wins rule for local/local collisions.
        # -----------------------------------------------------------------
        seen: dict[str, RecallCandidate] = {}

        for recall, result in zip(available_recalls, results):
            if isinstance(result, Exception):
                logger.warning(
                    "[MULTI_RECALL] Recall '{}' failed: {}", recall.name, result
                )
                continue

            logger.debug(
                "[MULTI_RECALL] '{}' returned {} results",
                recall.name,
                len(result),
            )

            for rank, candidate in enumerate(result, start=1):
                # Source filter applied at merge time so the final list
                # already respects the caller's filter.
                if source_filter and candidate.source != source_filter:
                    continue

                # Stamp rank metadata onto the candidate so fusion can
                # consume it later.
                self._stamp_rank(candidate, recall.name, rank)

                existing = seen.get(candidate.name)
                if existing is None:
                    seen[candidate.name] = candidate
                    continue

                # Existing entry — we need to merge the new signal in.
                self._merge_into_existing(existing, candidate)

        # -----------------------------------------------------------------
        # Step 2 — fuse BM25 + vector scores via reciprocal rank fusion,
        # write the fused value back onto ``score``, and flag hybrid
        # matches in ``match_type``.
        # -----------------------------------------------------------------
        for candidate in seen.values():
            self._apply_fusion(candidate)

        # -----------------------------------------------------------------
        # Step 3 — sort with the tier rule. Local always beats remote,
        # score descending within each tier.
        # -----------------------------------------------------------------
        def _sort_key(c: RecallCandidate) -> tuple[int, float]:
            tier = 0 if c.source == "local" else 1
            return (tier, -c.score)

        candidates = sorted(seen.values(), key=_sort_key)[:k]

        local_count = sum(1 for c in candidates if c.source == "local")
        remote_count = len(candidates) - local_count

        logger.info(
            "[MULTI_RECALL] query='{}' → {} candidates "
            "(local={}, remote={}, strategies={})",
            query,
            len(candidates),
            local_count,
            remote_count,
            len(available_recalls),
        )

        return candidates

    async def search(
        self,
        query: str,
        k: int = 10,
        per_recall_k: int | None = None,
        **kwargs,
    ) -> list[RecallCandidate]:
        """Backward-compatible alias for ``recall``."""
        return await self.recall(query, k=k, per_recall_k=per_recall_k, **kwargs)

    # -------------------------------------------------------------------------
    # Fusion internals
    # -------------------------------------------------------------------------

    @staticmethod
    def _stamp_rank(
        candidate: RecallCandidate,
        strategy_name: str,
        rank: int,
    ) -> None:
        """Record the per-strategy rank onto the candidate.

        This is what lets the RRF fusion step — running later — know
        where the candidate placed inside each strategy's result list.
        """
        if strategy_name == "local_bm25":
            candidate.bm25_rank = rank
            if candidate.bm25_score is None:
                candidate.bm25_score = candidate.score
        elif strategy_name == "local_db":
            candidate.vector_rank = rank
            if candidate.vector_score is None:
                candidate.vector_score = candidate.score

    @staticmethod
    def _merge_into_existing(
        existing: RecallCandidate,
        incoming: RecallCandidate,
    ) -> None:
        """Merge a new candidate's signals into an existing dict entry.

        Called when two strategies surface the same skill. We want to
        keep every per-strategy signal so the fusion step can use it.

        Tier rule during merge:
        * ``local`` overwrites ``remote`` wholesale (local always wins).
        * ``local`` vs ``local`` keeps the first-seen candidate as the
          "base" and copies only the new BM25/vector signals in.
        * ``remote`` incoming into an existing ``local`` is silently
          dropped.
        """
        # local always beats remote — promote incoming wholesale.
        if incoming.source == "local" and existing.source == "remote":
            # Preserve any per-strategy signals already on the remote
            # entry (there shouldn't be any, but be defensive).
            incoming.bm25_score = incoming.bm25_score or existing.bm25_score
            incoming.vector_score = incoming.vector_score or existing.vector_score
            incoming.bm25_rank = incoming.bm25_rank or existing.bm25_rank
            incoming.vector_rank = incoming.vector_rank or existing.vector_rank
            # Direct attribute copy — we can't reassign ``existing`` in
            # the caller's dict from here, so mutate in place.
            existing.__dict__.update(incoming.__dict__)
            return

        # remote incoming into an existing local — copy only remote-specific
        # metadata; do not overwrite the local candidate.
        if incoming.source == "remote" and existing.source == "local":
            # Remote hit confirms the skill exists on the Market too —
            # stash that fact in metadata for callers who care.
            existing.metadata.setdefault(
                "also_available_remote", incoming.metadata or {}
            )
            return

        # Same-tier merge — adopt new per-strategy signals when present.
        if incoming.bm25_score is not None:
            existing.bm25_score = incoming.bm25_score
            existing.bm25_rank = incoming.bm25_rank
        if incoming.vector_score is not None:
            existing.vector_score = incoming.vector_score
            existing.vector_rank = incoming.vector_rank
        # Copy description through if the existing entry was missing one.
        if not existing.description and incoming.description:
            existing.description = incoming.description
        # Promote the richer skill object if the existing one was None.
        if existing.skill is None and incoming.skill is not None:
            existing.skill = incoming.skill

    @staticmethod
    def _apply_fusion(candidate: RecallCandidate) -> None:
        """Compute the RRF-fused score and update score / match_type.

        Fusion rules:

        * If neither BM25 nor vector ranks are set, leave ``score`` alone
          (the candidate came from a non-fused strategy like local_file
          or remote).
        * If only one rank is set, use its single RRF term. This still
          lets BM25-only and vector-only hits compete on a comparable
          fused scale.
        * If both ranks are set, sum the two RRF terms and mark the
          candidate as ``match_type="hybrid"``.
        """
        bm25_rank = candidate.bm25_rank
        vector_rank = candidate.vector_rank

        if bm25_rank is None and vector_rank is None:
            return  # Nothing to fuse.

        fused = 0.0
        if bm25_rank is not None:
            fused += 1.0 / (RRF_K + bm25_rank)
        if vector_rank is not None:
            fused += 1.0 / (RRF_K + vector_rank)

        candidate.score = fused

        if bm25_rank is not None and vector_rank is not None:
            candidate.match_type = "hybrid"

    # -------------------------------------------------------------------------
    # Misc
    # -------------------------------------------------------------------------

    async def _safe_search(
        self,
        recall: "BaseRecall",
        query: str,
        k: int,
        **kwargs,
    ) -> "list[RecallCandidate] | Exception":
        """Invoke a single strategy, returning exceptions instead of raising."""
        try:
            return await recall.search(query, k=k, **kwargs)
        except Exception as e:
            logger.warning("Recall '{}' failed: {}", recall.name, e)
            return e

    def get_stats(self) -> dict:
        """Aggregate stats across all strategies."""
        return {
            "total_strategies": len(self._recalls),
            "available_strategies": len(self.get_available_recalls()),
            "strategies": [r.get_stats() for r in self._recalls],
        }

    async def close(self) -> None:
        """Close every strategy that exposes a ``close`` hook."""
        for recall in self._recalls:
            if hasattr(recall, "close") and callable(getattr(recall, "close")):
                try:
                    recall.close()
                except Exception as e:
                    logger.warning("Failed to close recall '{}': {}", recall.name, e)
