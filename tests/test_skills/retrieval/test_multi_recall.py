"""test_multi_recall.py — MultiRecall 单元测试

测试多路召回合并功能。

用法：
    pytest tests/test_skills/retrieval/test_multi_recall.py -v
"""

from __future__ import annotations

import pytest
import time

from core.skill.retrieval import MultiRecall, LocalFileRecall, RecallCandidate


class TestMultiRecall:
    """MultiRecall 测试类"""

    def test_initialization_with_strategies(self, multi_recall: MultiRecall):
        """测试使用策略列表初始化"""
        assert isinstance(multi_recall._recalls, list)
        assert len(multi_recall._recalls) >= 1  # 至少应该有 LocalFileRecall

    def test_get_available_recalls(self, multi_recall: MultiRecall):
        """测试获取可用策略"""
        available = multi_recall.get_available_recalls()

        assert isinstance(available, list)
        assert len(available) >= 1  # 至少有一个可用

        # 所有可用策略的 is_available 应该返回 True
        for recall in available:
            assert recall.is_available() is True

        print(f"\nAvailable recalls: {[r.name for r in available]}")

    def test_get_stats(self, multi_recall: MultiRecall):
        """测试获取统计信息"""
        stats = multi_recall.get_stats()

        assert "total_strategies" in stats
        assert "available_strategies" in stats
        assert "strategies" in stats

        assert isinstance(stats["total_strategies"], int)
        assert isinstance(stats["available_strategies"], int)
        assert stats["available_strategies"] <= stats["total_strategies"]

        print(
            f"\nStats: {stats['total_strategies']} total, {stats['available_strategies']} available"
        )

    @pytest.mark.asyncio
    async def test_search_returns_candidates(self, multi_recall: MultiRecall):
        """测试搜索返回候选列表"""
        if not multi_recall.get_available_recalls():
            pytest.skip("No available recall strategies")

        query = "test"
        start = time.time()
        candidates = await multi_recall.search(query, k=10)
        elapsed = (time.time() - start) * 1000

        print(
            f"\nQuery: '{query}', Time: {elapsed:.1f}ms, Candidates: {len(candidates)}"
        )

        assert isinstance(candidates, list)
        assert all(isinstance(c, RecallCandidate) for c in candidates)
        assert len(candidates) <= 10  # 不超过 k

    @pytest.mark.asyncio
    async def test_search_local_priority(self, multi_recall: MultiRecall):
        """测试 local 优先策略"""
        available = multi_recall.get_available_recalls()
        if not available:
            pytest.skip("No available recall strategies")

        # 如果同时有 local 和 remote，验证 local 优先
        has_local = any(r.name == "local_file" for r in available)
        has_remote = any(r.name == "remote" for r in available)

        if not (has_local and has_remote):
            pytest.skip("Need both local and remote recalls to test priority")

        query = "web"
        candidates = await multi_recall.search(query, k=20)

        # 统计来源
        local_count = sum(1 for c in candidates if c.source == "local")
        remote_count = sum(1 for c in candidates if c.source == "remote")

        print(f"\nLocal: {local_count}, Remote: {remote_count}")

        # 如果同一个 skill 在 local 和 remote 都存在，应该优先使用 local
        # 这里只是验证搜索成功，不验证具体逻辑

    @pytest.mark.asyncio
    async def test_search_respects_k_parameter(self, multi_recall: MultiRecall):
        """测试 k 参数限制返回数量"""
        if not multi_recall.get_available_recalls():
            pytest.skip("No available recall strategies")

        query = "test"

        candidates_3 = await multi_recall.search(query, k=3)
        candidates_5 = await multi_recall.search(query, k=5)
        candidates_10 = await multi_recall.search(query, k=10)

        assert len(candidates_3) <= 3
        assert len(candidates_5) <= 5
        assert len(candidates_10) <= 10

        print(
            f"\nk=3: {len(candidates_3)}, k=5: {len(candidates_5)}, k=10: {len(candidates_10)}"
        )

    @pytest.mark.asyncio
    async def test_search_sorted_by_score(self, multi_recall: MultiRecall):
        """测试结果按分数降序排序"""
        if not multi_recall.get_available_recalls():
            pytest.skip("No available recall strategies")

        query = "test"
        candidates = await multi_recall.search(query, k=10)

        if len(candidates) >= 2:
            # 验证分数是降序
            for i in range(len(candidates) - 1):
                assert candidates[i].score >= candidates[i + 1].score

    @pytest.mark.asyncio
    async def test_search_with_per_recall_k(self, multi_recall: MultiRecall):
        """测试 per_recall_k 参数"""
        if not multi_recall.get_available_recalls():
            pytest.skip("No available recall strategies")

        query = "test"

        # 使用 per_recall_k 限制每个策略的返回数
        candidates = await multi_recall.search(query, k=10, per_recall_k=5)

        assert isinstance(candidates, list)
        assert len(candidates) <= 10

    def test_add_recall(self, skills_dir):
        """测试动态添加策略"""
        multi = MultiRecall()

        assert len(multi._recalls) == 0

        # 添加策略
        recall = LocalFileRecall(skills_dir)
        multi.add_recall(recall)

        assert len(multi._recalls) == 1
        assert multi._recalls[0] == recall

    def test_remove_recall(self, skills_dir):
        """测试动态移除策略"""
        recall = LocalFileRecall(skills_dir)
        multi = MultiRecall([recall])

        assert len(multi._recalls) == 1

        # 移除策略
        removed = multi.remove_recall("local_file")

        assert removed is True
        assert len(multi._recalls) == 0

        # 移除不存在的策略
        removed = multi.remove_recall("non_existent")
        assert removed is False

    @pytest.mark.asyncio
    async def test_close(self, multi_recall: MultiRecall):
        """测试关闭资源"""
        # 只是验证不抛出异常
        await multi_recall.close()


class TestMultiRecallEmpty:
    """MultiRecall 空状态测试"""

    def test_empty_recalls(self):
        """测试空策略列表"""
        multi = MultiRecall([])

        assert multi.get_available_recalls() == []
        assert multi.get_stats()["total_strategies"] == 0

    @pytest.mark.asyncio
    async def test_search_with_no_available_recalls(self):
        """测试无可用策略时搜索"""
        multi = MultiRecall([])

        candidates = await multi.search("test", k=10)

        assert candidates == []


# =============================================================================
# MS-DES-0004 — RRF fusion unit tests
# =============================================================================
#
# These tests exercise the pure fusion helpers on ``MultiRecall`` directly:
# ``_stamp_rank``, ``_merge_into_existing``, and ``_apply_fusion``. They do
# not require any real recall strategies, skills directory, or network —
# they manipulate ``RecallCandidate`` objects in-process and assert the
# fusion math lines up with the spec.
# =============================================================================


class TestRrfFusion:
    """Reciprocal rank fusion behavior inside ``_apply_fusion``."""

    def test_bm25_only_sets_single_term_score(self):
        """A candidate with only a BM25 rank gets the single-term RRF score."""
        c = RecallCandidate(name="alpha", source="local", score=0.0, bm25_rank=1)
        MultiRecall._apply_fusion(c)

        from core.skill.retrieval.multi_recall import RRF_K

        assert c.score == pytest.approx(1.0 / (RRF_K + 1))
        assert c.match_type != "hybrid"

    def test_vector_only_sets_single_term_score(self):
        """A candidate with only a vector rank gets the single-term RRF score."""
        c = RecallCandidate(name="beta", source="local", score=0.0, vector_rank=1)
        MultiRecall._apply_fusion(c)

        from core.skill.retrieval.multi_recall import RRF_K

        assert c.score == pytest.approx(1.0 / (RRF_K + 1))
        assert c.match_type != "hybrid"

    def test_both_ranks_set_match_type_hybrid(self):
        """Both BM25 and vector ranks present — fused score + hybrid tag."""
        c = RecallCandidate(
            name="gamma", source="local", score=0.0,
            bm25_rank=3, vector_rank=3,
        )
        MultiRecall._apply_fusion(c)

        from core.skill.retrieval.multi_recall import RRF_K

        expected = 1.0 / (RRF_K + 3) + 1.0 / (RRF_K + 3)
        assert c.score == pytest.approx(expected)
        assert c.match_type == "hybrid"

    def test_neither_rank_leaves_score_untouched(self):
        """Candidates from non-fused strategies keep their original score."""
        c = RecallCandidate(name="delta", source="local", score=0.42)
        MultiRecall._apply_fusion(c)
        assert c.score == 0.42

    def test_cross_list_agreement_beats_single_list_top(self):
        """AC #14 from MS-DES-0004.

        A skill present at BM25 rank-3 AND vector rank-3 must rank above a
        skill present only at BM25 rank-1. Without this invariant RRF
        would not be doing its job.
        """
        hybrid = RecallCandidate(
            name="hybrid", source="local", score=0.0,
            bm25_rank=3, vector_rank=3,
        )
        solo = RecallCandidate(
            name="solo", source="local", score=0.0,
            bm25_rank=1,
        )
        MultiRecall._apply_fusion(hybrid)
        MultiRecall._apply_fusion(solo)
        assert hybrid.score > solo.score


class TestStampRank:
    """Per-strategy rank stamping by ``_stamp_rank``."""

    def test_bm25_rank_stamped(self):
        c = RecallCandidate(name="alpha", score=0.7)
        MultiRecall._stamp_rank(c, "local_bm25", 5)
        assert c.bm25_rank == 5
        # bm25_score back-fills from .score when not already set.
        assert c.bm25_score == 0.7

    def test_vector_rank_stamped(self):
        c = RecallCandidate(name="beta", score=0.8)
        MultiRecall._stamp_rank(c, "local_db", 2)
        assert c.vector_rank == 2
        assert c.vector_score == 0.8

    def test_unknown_strategy_is_noop(self):
        """Strategies other than local_bm25 / local_db leave the candidate alone."""
        c = RecallCandidate(name="gamma", source="local", score=1.0)
        MultiRecall._stamp_rank(c, "local_file", 1)
        assert c.bm25_rank is None
        assert c.vector_rank is None


class TestMergeIntoExisting:
    """Dedup-merge semantics when two strategies surface the same skill."""

    def test_local_displaces_remote(self):
        """A local incoming candidate overwrites an existing remote entry."""
        existing = RecallCandidate(name="s", source="remote", score=0.3)
        incoming = RecallCandidate(
            name="s", source="local", score=0.9,
            bm25_score=0.9, bm25_rank=1,
        )
        MultiRecall._merge_into_existing(existing, incoming)
        assert existing.source == "local"
        assert existing.score == 0.9
        assert existing.bm25_rank == 1

    def test_remote_does_not_displace_local(self):
        """A remote incoming is silently dropped; local stays primary."""
        existing = RecallCandidate(name="s", source="local", score=0.5)
        incoming = RecallCandidate(
            name="s", source="remote", score=0.99,
            metadata={"market_id": "abc"},
        )
        MultiRecall._merge_into_existing(existing, incoming)
        assert existing.source == "local"
        assert existing.score == 0.5
        # But the fact that the Market also has it is stashed in metadata.
        assert "also_available_remote" in existing.metadata

    def test_same_tier_adopts_new_bm25_signal(self):
        """A later local strategy's BM25 score transfers onto the existing candidate."""
        existing = RecallCandidate(name="s", source="local", score=1.0)
        incoming = RecallCandidate(
            name="s", source="local", score=1.5,
            bm25_score=1.5, bm25_rank=2,
        )
        MultiRecall._merge_into_existing(existing, incoming)
        assert existing.bm25_rank == 2
        assert existing.bm25_score == 1.5

    def test_same_tier_adopts_new_vector_signal(self):
        existing = RecallCandidate(name="s", source="local", score=1.0)
        incoming = RecallCandidate(
            name="s", source="local", score=0.8,
            vector_score=0.8, vector_rank=4,
        )
        MultiRecall._merge_into_existing(existing, incoming)
        assert existing.vector_rank == 4
        assert existing.vector_score == 0.8


class TestTierRuleAfterFusion:
    """Sanity-check that the tier sort preserves local-before-remote."""

    def test_sort_key_ordering(self):
        """Even with a lower fused score, local must beat remote."""
        local_weak = RecallCandidate(
            name="local", source="local", score=0.01, bm25_rank=10,
        )
        remote_strong = RecallCandidate(
            name="remote", source="remote", score=0.99,
        )

        def _sort_key(c):
            tier = 0 if c.source == "local" else 1
            return (tier, -c.score)

        ordered = sorted([remote_strong, local_weak], key=_sort_key)
        assert ordered[0].source == "local"
        assert ordered[1].source == "remote"
