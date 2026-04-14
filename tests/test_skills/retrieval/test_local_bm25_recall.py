"""test_local_bm25_recall.py — unit tests for MS-DES-0004.

Covers:

* ``_tokenize`` — NFKC normalization, lowercasing, stopword filtering,
  min-length filtering.
* ``Bm25Index`` — build from synthetic Skills, score a document against
  a query, rank top-k, field-weighting behavior, idempotent rebuild.
* ``LocalBm25Recall`` — async ``search`` interface, empty-query
  handling, directory-signature invalidation, deterministic output.

Usage::

    pytest tests/test_skills/retrieval/test_local_bm25_recall.py -v

These tests are stdlib-only — they build synthetic ``Skill`` objects in
memory and, where a directory is needed, use ``tmp_path`` to stage a
minimal skill tree. No ``ConfigManager`` dependency.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from core.skill.retrieval.local_bm25_recall import (
    BM25_B,
    BM25_K1,
    Bm25Index,
    LocalBm25Recall,
    STOPWORDS,
    W_BODY,
    W_DESC,
    W_NAME,
    _tokenize,
)
from core.skill.retrieval.schema import RecallCandidate
from core.skill.schema import ExecutionMode, Skill


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _make_skill(
    name: str,
    description: str = "",
    content: str = "",
) -> Skill:
    """Build a minimal ``Skill`` for index tests.

    Bypasses ``SkillLoader`` entirely — BM25 only needs name, description,
    and content.
    """
    return Skill(
        name=name,
        description=description,
        content=content,
        execution_mode=ExecutionMode.KNOWLEDGE,
    )


def _stage_skill_dir(root: Path, name: str, description: str, body: str) -> None:
    """Create a minimal skills/<name>/SKILL.md under ``root``."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    front_matter = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n"
    )
    (skill_dir / "SKILL.md").write_text(front_matter + body, encoding="utf-8")


# -----------------------------------------------------------------------------
# _tokenize
# -----------------------------------------------------------------------------


class TestTokenize:
    """Low-level tokenizer behavior."""

    def test_empty_string_returns_empty_list(self):
        assert _tokenize("") == []

    def test_none_input_returns_empty_list(self):
        assert _tokenize(None) == []  # type: ignore[arg-type]

    def test_whitespace_only_returns_empty_list(self):
        assert _tokenize("   \n\t  ") == []

    def test_lowercases_input(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_splits_on_punctuation(self):
        # "don't" -> ["don", "t"] then the "t" is dropped by MIN_TOKEN_LENGTH.
        tokens = _tokenize("don't stop!")
        assert "don" in tokens
        assert "stop" in tokens
        assert "t" not in tokens

    def test_drops_single_character_tokens(self):
        # "a b cd" -> "a"/"b" filtered by MIN_TOKEN_LENGTH; "cd" kept.
        # "a" would also be filtered as a stopword anyway.
        tokens = _tokenize("a b cd")
        assert "cd" in tokens
        assert "a" not in tokens
        assert "b" not in tokens

    def test_drops_stopwords(self):
        # Every token in this string is a stopword except "skills".
        tokens = _tokenize("the and of skills")
        assert tokens == ["skills"]

    def test_nfkc_normalizes_fullwidth(self):
        # Full-width Latin letters normalize to ASCII.
        tokens = _tokenize("ＨＥＬＬＯ")
        assert tokens == ["hello"]

    def test_keeps_cjk_runs(self):
        # CJK characters are "word" characters under the UNICODE flag, so
        # they should tokenize as one run, not split per-character.
        tokens = _tokenize("中文测试")
        assert tokens == ["中文测试"]

    def test_drops_underscores_inside_words(self):
        # Underscores are treated as non-word by the tokenizer regex.
        tokens = _tokenize("doc_freshness scanner")
        assert tokens == ["doc", "freshness", "scanner"]

    def test_keeps_digits(self):
        # Digits count as word characters.
        tokens = _tokenize("version 2026 release")
        assert "2026" in tokens
        assert "version" in tokens
        assert "release" in tokens


# -----------------------------------------------------------------------------
# Bm25Index
# -----------------------------------------------------------------------------


class TestBm25Index:
    """Index construction and scoring."""

    def test_empty_corpus(self):
        index = Bm25Index.build([])
        assert index.n_docs == 0
        assert index.avg_doc_length == 0.0
        assert index.rank("anything", k=10) == []

    def test_single_doc_corpus(self):
        skill = _make_skill("alpha", description="the alpha skill", content="")
        index = Bm25Index.build([skill])
        assert index.n_docs == 1
        # "alpha" appears in name (W_NAME) and description (W_DESC) ->
        # at least W_NAME + W_DESC occurrences in the merged bag.
        assert index.documents["alpha"].term_freqs.get("alpha", 0) >= W_NAME

    def test_field_weighting_name_beats_body(self):
        """A skill whose name matches the query ranks above one where only the body matches."""
        name_match = _make_skill("changelog", description="", content="")
        body_match = _make_skill(
            "other",
            description="",
            content="this skill mentions changelog deep in the body " * 5,
        )
        index = Bm25Index.build([name_match, body_match])
        ranked = index.rank("changelog", k=10)
        assert len(ranked) == 2
        assert ranked[0][0] == "changelog"

    def test_exact_name_match_ranks_first(self):
        skills = [
            _make_skill("style_checker", description="reviews markdown", content=""),
            _make_skill("doc_freshness", description="scans docs", content=""),
            _make_skill(
                "doc_generator",
                description="generates first-draft docs",
                content="",
            ),
        ]
        index = Bm25Index.build(skills)
        ranked = index.rank("style checker", k=3)
        assert ranked[0][0] == "style_checker"

    def test_body_only_keyword_surfaces_skill(self):
        """A query term that only appears in the body still ranks the matching skill."""
        skill_a = _make_skill(
            "skill_a",
            description="does thing A",
            content="handles localization and translation",
        )
        skill_b = _make_skill(
            "skill_b",
            description="does thing B",
            content="completely unrelated content about trees",
        )
        index = Bm25Index.build([skill_a, skill_b])
        ranked = index.rank("localization", k=5)
        assert len(ranked) == 1
        assert ranked[0][0] == "skill_a"

    def test_rank_returns_at_most_k(self):
        skills = [
            _make_skill(f"skill_{i}", description="test skill content", content="")
            for i in range(10)
        ]
        index = Bm25Index.build(skills)
        ranked = index.rank("test", k=3)
        assert len(ranked) <= 3

    def test_empty_query_returns_empty(self):
        skills = [_make_skill("alpha", description="alpha skill")]
        index = Bm25Index.build(skills)
        assert index.rank("", k=10) == []
        assert index.rank("the and of", k=10) == []  # stopwords-only

    def test_score_is_non_negative(self):
        skill = _make_skill("alpha", description="alpha skill content")
        index = Bm25Index.build([skill])
        tokens = ["alpha"]
        score = index.score(tokens, "alpha")
        assert score >= 0.0
        assert math.isfinite(score)

    def test_score_zero_for_missing_term(self):
        skill = _make_skill("alpha", description="alpha skill", content="")
        index = Bm25Index.build([skill])
        score = index.score(["nonexistent"], "alpha")
        assert score == 0.0

    def test_score_zero_for_missing_doc(self):
        skill = _make_skill("alpha", description="alpha", content="")
        index = Bm25Index.build([skill])
        score = index.score(["alpha"], "not_in_index")
        assert score == 0.0

    def test_idempotent_rebuild(self):
        """Building the same corpus twice produces identical index state."""
        skills = [
            _make_skill("alpha", description="one", content="body one"),
            _make_skill("beta", description="two", content="body two"),
        ]
        index_a = Bm25Index.build(skills)
        index_b = Bm25Index.build(skills)

        assert index_a.n_docs == index_b.n_docs
        assert index_a.avg_doc_length == index_b.avg_doc_length
        assert index_a.doc_freqs == index_b.doc_freqs
        for name in ["alpha", "beta"]:
            assert index_a.documents[name].term_freqs == index_b.documents[name].term_freqs
            assert index_a.documents[name].doc_length == index_b.documents[name].doc_length

    def test_avg_doc_length_matches_arithmetic_mean(self):
        skills = [
            _make_skill("a", description="x", content=""),
            _make_skill("b", description="x y", content=""),
            _make_skill("c", description="x y z", content=""),
        ]
        index = Bm25Index.build(skills)
        total = sum(e.doc_length for e in index.documents.values())
        assert index.avg_doc_length == pytest.approx(total / 3.0)


# -----------------------------------------------------------------------------
# LocalBm25Recall (async)
# -----------------------------------------------------------------------------


class TestLocalBm25Recall:
    """Public strategy interface."""

    def test_is_available_true_when_dir_exists(self, tmp_path: Path):
        recall = LocalBm25Recall(tmp_path)
        assert recall.is_available() is True

    def test_is_available_false_when_dir_missing(self, tmp_path: Path):
        recall = LocalBm25Recall(tmp_path / "nonexistent")
        assert recall.is_available() is False

    def test_name_property(self, tmp_path: Path):
        recall = LocalBm25Recall(tmp_path)
        assert recall.name == "local_bm25"

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, tmp_path: Path):
        _stage_skill_dir(tmp_path, "alpha", "alpha skill", "body content")
        recall = LocalBm25Recall(tmp_path)
        assert await recall.search("") == []
        assert await recall.search("   ") == []

    @pytest.mark.asyncio
    async def test_search_returns_bm25_tagged_candidates(self, tmp_path: Path):
        _stage_skill_dir(
            tmp_path, "changelog_writer", "writes release changelogs", "body"
        )
        _stage_skill_dir(
            tmp_path, "doc_freshness", "scans docs for staleness", "body"
        )
        recall = LocalBm25Recall(tmp_path)
        results = await recall.search("changelog", k=5)

        assert len(results) >= 1
        assert all(isinstance(c, RecallCandidate) for c in results)
        assert all(c.match_type == "bm25" for c in results)
        assert all(c.source == "local" for c in results)
        assert all(c.bm25_score is not None for c in results)
        assert results[0].name == "changelog_writer"

    @pytest.mark.asyncio
    async def test_deterministic_output(self, tmp_path: Path):
        for i in range(5):
            _stage_skill_dir(
                tmp_path,
                f"skill_{i}",
                f"description {i} test",
                f"body content {i}",
            )
        recall = LocalBm25Recall(tmp_path)
        first = await recall.search("test", k=10)
        second = await recall.search("test", k=10)
        assert [c.name for c in first] == [c.name for c in second]
        assert [c.bm25_score for c in first] == [c.bm25_score for c in second]

    @pytest.mark.asyncio
    async def test_invalidate_triggers_rebuild(self, tmp_path: Path):
        _stage_skill_dir(tmp_path, "alpha", "alpha skill", "original body")
        recall = LocalBm25Recall(tmp_path)
        await recall.search("alpha", k=5)  # warm up
        assert recall._index_built is True

        recall.invalidate()
        assert recall._index_built is False

        # Next search rebuilds.
        await recall.search("alpha", k=5)
        assert recall._index_built is True

    @pytest.mark.asyncio
    async def test_new_skill_surfaces_after_dir_change(self, tmp_path: Path):
        _stage_skill_dir(tmp_path, "alpha", "alpha skill", "original")
        recall = LocalBm25Recall(tmp_path)

        before = await recall.search("beta", k=5)
        assert before == []

        # Add a new skill and bump mtime of the new SKILL.md so the
        # signature changes.
        _stage_skill_dir(tmp_path, "beta", "beta skill keyword", "body")

        after = await recall.search("beta", k=5)
        assert len(after) >= 1
        assert any(c.name == "beta" for c in after)

    @pytest.mark.asyncio
    async def test_stats_reflect_index_state(self, tmp_path: Path):
        _stage_skill_dir(tmp_path, "alpha", "alpha skill", "body")
        _stage_skill_dir(tmp_path, "beta", "beta skill", "body")
        recall = LocalBm25Recall(tmp_path)
        await recall.search("skill", k=10)  # warm index

        stats = recall.get_stats()
        assert stats["name"] == "local_bm25"
        assert stats["indexed_skills"] == 2
        assert stats["unique_terms"] > 0
        assert stats["avg_doc_length"] > 0
        assert stats["index_built"] is True

    @pytest.mark.asyncio
    async def test_rebuild_is_idempotent_on_disk(self, tmp_path: Path):
        _stage_skill_dir(tmp_path, "alpha", "alpha skill", "body")
        _stage_skill_dir(tmp_path, "beta", "beta skill", "body")
        recall = LocalBm25Recall(tmp_path)

        recall.rebuild()
        sig_a = recall._dir_signature
        docs_a = dict(recall._index.doc_freqs)

        recall.rebuild()
        sig_b = recall._dir_signature
        docs_b = dict(recall._index.doc_freqs)

        assert sig_a == sig_b
        assert docs_a == docs_b


# -----------------------------------------------------------------------------
# Sanity checks on tuning constants
# -----------------------------------------------------------------------------


class TestTuningConstants:
    """Guard-rails on the BM25 parameters."""

    def test_bm25_k1_is_canonical(self):
        assert BM25_K1 == 1.2

    def test_bm25_b_is_canonical(self):
        assert BM25_B == 0.75

    def test_field_weights_monotonic(self):
        # name tokens should weigh more than description than body.
        assert W_NAME > W_DESC > W_BODY

    def test_stopwords_nonempty(self):
        assert len(STOPWORDS) >= 20
        assert "the" in STOPWORDS
        assert "and" in STOPWORDS
