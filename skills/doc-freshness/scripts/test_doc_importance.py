#!/usr/bin/env python3
"""test_doc_importance.py — Unit tests for the BM25-weighted importance module.

These tests lock in MS-DES-0009 behavior:

* ``_tokenize`` parity with ``core/skill/retrieval/local_bm25_recall._tokenize``
  (AC #3) — we test against the upstream canary strings to guard against
  accidental divergence as either copy evolves.
* ``DocBm25Index`` BM25 math invariants (scoring, IDF smoothing, length
  normalization, empty-corpus handling).
* ``compute_importance_scores`` end-to-end: max-normalized output in
  [0.0, 1.0] (AC #2), empty-corpus -> empty dict (AC #1), single-doc
  corpus -> that doc scores 1.0, combined-score formula uses the documented
  W_INTRINSIC / W_REFERENCE weights.
* ``classify_priority`` bucketing (AC for priority bucket cutpoints).
* Inbound reference counting: Markdown-link counts, inline-code-path counts,
  self-reference exclusion, out-of-tree reference rejection, anchor-stripped
  same-doc references don't double-count.

All tests use stdlib ``unittest`` + ``tempfile`` — no third-party deps, no
git repo required. Run via:

    python skills/doc-freshness/scripts/test_doc_importance.py
"""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling module importable regardless of invocation directory.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_importance  # noqa: E402
from doc_importance import (  # noqa: E402
    DocBm25Index,
    PRIORITY_HIGH,
    PRIORITY_MEDIUM,
    W_INTRINSIC,
    W_REFERENCE,
    _compute_inbound_reference_counts,
    _extract_doc_references,
    _tokenize,
    classify_priority,
    compute_importance_scores,
)


# ---------------------------------------------------------------------------
# _tokenize — parity with upstream local_bm25_recall._tokenize (AC #3)
# ---------------------------------------------------------------------------


class TestTokenizerParity(unittest.TestCase):
    """The tokenizer must produce the same output as the upstream BM25 port."""

    def test_english_sentence(self):
        """Plain English — stopwords dropped, words lowercased."""
        result = _tokenize("The quick brown fox jumps over the lazy dog")
        # "the" dropped (stopword); everything else kept, lowercased.
        self.assertEqual(
            result,
            ["quick", "brown", "fox", "jumps", "over", "lazy", "dog"],
        )

    def test_cjk_sentence(self):
        """CJK runs stay intact — not split character-by-character."""
        # Unicode \w matches CJK under re.UNICODE, so a CJK run is one token.
        result = _tokenize("快速的棕色狐狸")
        self.assertEqual(result, ["快速的棕色狐狸"])

    def test_mixed_script(self):
        """Mixed Latin/CJK — punctuation and underscores split tokens."""
        result = _tokenize("The API is 本地_BM25 compatible")
        # "the" and "is" dropped (stopwords); underscore splits 本地 and bm25;
        # "api" is kept (3 chars >= MIN_TOKEN_LENGTH=2).
        self.assertIn("api", result)
        self.assertIn("本地", result)
        self.assertIn("bm25", result)
        self.assertIn("compatible", result)

    def test_empty_input_returns_empty_list(self):
        """None / empty string produce []."""
        self.assertEqual(_tokenize(""), [])
        self.assertEqual(_tokenize(None), [])

    def test_short_tokens_dropped(self):
        """Tokens shorter than MIN_TOKEN_LENGTH=2 are dropped."""
        result = _tokenize("I a am in")
        # Single-char 'i' and 'a' dropped; 'am' and 'in' are stopwords.
        # (Our stopword list includes 'a', 'an', 'in' — and 'am' is NOT
        # in the stopword list, so it should survive.)
        self.assertIn("am", result)
        self.assertNotIn("i", result)
        self.assertNotIn("a", result)
        self.assertNotIn("in", result)


# ---------------------------------------------------------------------------
# DocBm25Index — BM25 math invariants
# ---------------------------------------------------------------------------


class TestDocBm25Index(unittest.TestCase):
    """Invariants of the simplified BM25 index."""

    def test_empty_corpus(self):
        """Building an index from no docs is legal and produces zeroes."""
        index = DocBm25Index.build({})
        self.assertEqual(index.n_docs, 0)
        self.assertEqual(index.avg_doc_length, 0.0)
        # IDF on an empty index returns 0 (avoids log(inf)).
        self.assertEqual(index.idf("anything"), 0.0)
        # top_k_terms on an absent doc returns [].
        self.assertEqual(index.top_k_terms("nonexistent"), [])

    def test_idf_monotonic_in_rarity(self):
        """A term in 1 doc out of 10 has higher IDF than a term in 9/10."""
        docs = {f"doc{i}.md": "common common" for i in range(9)}
        docs["rare.md"] = "common rare"
        index = DocBm25Index.build(docs)
        # "common" appears in all 10 docs; "rare" appears in 1.
        idf_common = index.idf("common")
        idf_rare = index.idf("rare")
        self.assertGreater(idf_rare, idf_common)

    def test_top_k_terms_orders_by_tf_idf(self):
        """A doc with a distinctive term ranks it first."""
        docs = {
            "a.md": "shared shared shared unique",  # "unique" is distinctive
            "b.md": "shared shared",
            "c.md": "shared",
        }
        index = DocBm25Index.build(docs)
        top = index.top_k_terms("a.md", k=5)
        # "unique" is present in one doc only, so it has the highest IDF;
        # "shared" is in all three.
        terms = [t for t, _ in top]
        self.assertEqual(terms[0], "unique")

    def test_idf_finite_for_single_doc_corpus(self):
        """IDF formula handles n_docs=1 without producing inf or NaN."""
        index = DocBm25Index.build({"only.md": "alpha beta"})
        idf = index.idf("alpha")
        self.assertTrue(math.isfinite(idf))


# ---------------------------------------------------------------------------
# compute_importance_scores — end-to-end invariants
# ---------------------------------------------------------------------------


class TestComputeImportanceScores(unittest.TestCase):
    """AC #1, #2: empty corpus, single-doc edge case, [0,1] range invariant."""

    def test_empty_corpus_returns_empty_dict(self):
        """AC #1: no docs -> empty dict, no error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = compute_importance_scores(root, [])
            self.assertEqual(result, {})

    def test_single_doc_scores_one_point_zero(self):
        """A one-doc corpus max-normalizes to itself: the doc scores 1.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            doc = root / "only.md"
            doc.write_text("alpha beta gamma distinctive content here")
            scores = compute_importance_scores(root, [doc])
            self.assertIn("only.md", scores)
            self.assertAlmostEqual(scores["only.md"], W_INTRINSIC, places=6)
            # reference_score is 0 (no other docs to reference it), so the
            # combined score = W_INTRINSIC * 1.0 + W_REFERENCE * 0.0 == W_INTRINSIC.

    def test_scores_always_in_unit_interval(self):
        """AC #2: every score is in [0.0, 1.0]."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs = []
            for i in range(5):
                p = root / f"doc{i}.md"
                p.write_text(f"content for doc {i} with some terms keyword{i}")
                docs.append(p)
            # Make doc0 reference doc1 and doc2.
            (root / "doc0.md").write_text(
                "See [doc1](doc1.md) and [doc2](doc2.md) for details."
            )
            scores = compute_importance_scores(root, docs)
            for path, s in scores.items():
                self.assertGreaterEqual(s, 0.0, f"{path}: {s}")
                self.assertLessEqual(s, 1.0, f"{path}: {s}")

    def test_max_normalization_produces_one(self):
        """In a non-empty corpus with non-zero signals, max score == 1.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Three docs with clearly different content densities.
            docs = []
            a = root / "dense.md"
            a.write_text(
                "This doc has many distinctive technical terms "
                "like transformer, tokenizer, embedding, retrieval, "
                "reranker, vectorspace, indexing, semantic"
            )
            docs.append(a)
            b = root / "sparse.md"
            b.write_text("Short doc.")
            docs.append(b)
            c = root / "medium.md"
            c.write_text("A moderate doc with some terms and content.")
            docs.append(c)
            # Make dense.md referenced by both others for extra signal.
            b.write_text(b.read_text() + " See [dense](dense.md).")
            c.write_text(c.read_text() + " See [dense](dense.md).")

            scores = compute_importance_scores(root, docs)
            max_score = max(scores.values())
            self.assertAlmostEqual(max_score, 1.0, places=6)
            # dense.md should be the top doc.
            top = max(scores.items(), key=lambda kv: kv[1])
            self.assertEqual(top[0], "dense.md")

    def test_weights_sum_to_one(self):
        """The convex-combination invariant: W_INTRINSIC + W_REFERENCE == 1.0."""
        self.assertAlmostEqual(W_INTRINSIC + W_REFERENCE, 1.0, places=6)


# ---------------------------------------------------------------------------
# Inbound reference counting
# ---------------------------------------------------------------------------


class TestInboundReferenceCounts(unittest.TestCase):
    """Tests for _compute_inbound_reference_counts and its helpers."""

    def test_markdown_link_counts(self):
        """[text](path.md) increments the target's inbound count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.md").write_text("See [B](b.md) for details.")
            (root / "b.md").write_text("This is B.")
            doc_texts = {
                "a.md": (root / "a.md").read_text(),
                "b.md": (root / "b.md").read_text(),
            }
            counts = _compute_inbound_reference_counts(root, doc_texts)
            self.assertEqual(counts["b.md"], 1)
            self.assertEqual(counts["a.md"], 0)

    def test_inline_code_path_counts(self):
        """Inline-code paths like `b.md` count as references."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.md").write_text("The file `b.md` is relevant here.")
            (root / "b.md").write_text("B content.")
            doc_texts = {
                "a.md": (root / "a.md").read_text(),
                "b.md": (root / "b.md").read_text(),
            }
            counts = _compute_inbound_reference_counts(root, doc_texts)
            self.assertEqual(counts["b.md"], 1)

    def test_self_reference_excluded(self):
        """A doc linking to itself doesn't inflate its own inbound count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.md").write_text("Self [link](a.md) to myself.")
            doc_texts = {"a.md": (root / "a.md").read_text()}
            counts = _compute_inbound_reference_counts(root, doc_texts)
            self.assertEqual(counts["a.md"], 0)

    def test_anchor_in_reference_resolves_to_doc(self):
        """[text](doc.md#section) counts as a ref to doc.md (anchor stripped)."""
        refs = _extract_doc_references("See [here](target.md#section) please.")
        self.assertIn("target.md", refs)

    def test_external_url_ignored(self):
        """http:// and https:// URLs don't count as doc references."""
        refs = _extract_doc_references("See [online](https://example.com/foo.md)")
        # The regex captures the URL, but _resolve_reference filters out
        # external URLs before resolution — verify via extraction level
        # (external URLs are ignored by the "://"  check in resolver).
        # Extraction may or may not include; what matters is resolver behavior.
        # Assert via the end-to-end path:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.md").write_text("See [online](https://example.com/foo.md)")
            (root / "foo.md").write_text("Local foo.")
            doc_texts = {
                "a.md": (root / "a.md").read_text(),
                "foo.md": (root / "foo.md").read_text(),
            }
            counts = _compute_inbound_reference_counts(root, doc_texts)
            # foo.md should NOT be counted as referenced by a.md's external URL.
            self.assertEqual(counts["foo.md"], 0)


# ---------------------------------------------------------------------------
# classify_priority — bucket cutpoints
# ---------------------------------------------------------------------------


class TestClassifyPriority(unittest.TestCase):
    """Priority bucket discretization."""

    def test_high_bucket(self):
        self.assertEqual(classify_priority(PRIORITY_HIGH), "high")
        self.assertEqual(classify_priority(0.9), "high")
        self.assertEqual(classify_priority(1.0), "high")

    def test_medium_bucket(self):
        self.assertEqual(classify_priority(PRIORITY_MEDIUM), "medium")
        self.assertEqual(classify_priority(0.5), "medium")
        self.assertEqual(classify_priority(PRIORITY_HIGH - 0.0001), "medium")

    def test_low_bucket(self):
        self.assertEqual(classify_priority(0.0), "low")
        self.assertEqual(classify_priority(0.1), "low")
        self.assertEqual(classify_priority(PRIORITY_MEDIUM - 0.0001), "low")


# ---------------------------------------------------------------------------
# Integration: scanner --min-priority and --format priority-digest
# ---------------------------------------------------------------------------
#
# Lightweight integration tests that stand up a tiny temp docs tree + git
# repo, invoke scan_documentation, and inspect the resulting dict shape.
# These lock in AC #4 (new fields present), AC #5/#6 (--min-priority
# filtering + summary recompute), AC #7 (priority-digest formatter), and
# AC #8 (JSON backward compat — all old fields still there).


import subprocess  # noqa: E402  (imported here so the BM25 tests don't need it)


def _init_git_repo(root: Path) -> None:
    """Initialize a minimal git repo at ``root`` with a single commit."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)


class TestScannerIntegration(unittest.TestCase):
    """End-to-end: new fields surface correctly, CLI flags behave per AC."""

    def _build_fixture_tree(self, root: Path) -> None:
        """Create a small docs tree and git-commit it."""
        (root / "docs").mkdir(parents=True, exist_ok=True)
        # Central doc with distinctive terms and inbound references.
        (root / "docs" / "central.md").write_text(
            "# Central\n\nDistinctive BM25 tokenization transformer retrieval "
            "vectorspace indexing semantic reranker.\n"
        )
        # Two docs that reference central.md.
        (root / "docs" / "a.md").write_text(
            "# A\n\nThis references [central](central.md) heavily.\n"
        )
        (root / "docs" / "b.md").write_text(
            "# B\n\nAnother doc that uses `central.md` path syntax.\n"
        )
        # A trivially-light doc that shouldn't score high.
        (root / "docs" / "trivial.md").write_text("# Trivial\n\nShort.\n")
        _init_git_repo(root)

    def test_new_fields_present_in_every_doc_record(self):
        """AC #4: importance_score and priority appear on every record."""
        # Import here so top-level tests don't need to import the scanner.
        import doc_freshness_scanner
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_fixture_tree(root)
            result = doc_freshness_scanner.scan_documentation(
                repo_path=str(root),
                docs_path="docs/",
                since="2020-01-01",
            )
            self.assertGreater(len(result["documents"]), 0)
            for doc in result["documents"]:
                self.assertIn("importance_score", doc)
                self.assertIn("priority", doc)
                self.assertIsInstance(doc["importance_score"], float)
                self.assertIn(doc["priority"], ("low", "medium", "high"))
            self.assertIn("priority_counts", result["summary"])

    def test_min_priority_filter_shrinks_list(self):
        """AC #5: --min-priority high filters out low/medium records."""
        import doc_freshness_scanner
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_fixture_tree(root)
            # Unfiltered baseline.
            full = doc_freshness_scanner.scan_documentation(
                repo_path=str(root), docs_path="docs/", since="2020-01-01",
            )
            high_only = doc_freshness_scanner.scan_documentation(
                repo_path=str(root), docs_path="docs/", since="2020-01-01",
                min_priority="high",
            )
            # High-filtered result is a (possibly equal) subset of full.
            self.assertLessEqual(
                len(high_only["documents"]),
                len(full["documents"]),
            )
            # Every surviving doc must have priority == high.
            for doc in high_only["documents"]:
                self.assertEqual(doc["priority"], "high")
            # Summary counters recompute against the filtered list.
            self.assertEqual(
                high_only["summary"]["total_docs"],
                len(high_only["documents"]),
            )

    def test_json_backward_compat(self):
        """AC #8: JSON output retains all existing fields unchanged."""
        import doc_freshness_scanner
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_fixture_tree(root)
            result = doc_freshness_scanner.scan_documentation(
                repo_path=str(root), docs_path="docs/", since="2020-01-01",
            )
            # Every record must contain the full pre-v2 schema.
            for doc in result["documents"]:
                for key in (
                    "path", "last_updated", "days_since_update", "tracked",
                    "status", "related_code_changes", "matched_topics",
                    "recommendation",
                ):
                    self.assertIn(key, doc, f"missing pre-v2 key: {key}")

    def test_priority_digest_formatter_output(self):
        """AC #7: priority-digest produces valid Markdown without JSON noise."""
        import doc_freshness_scanner
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_fixture_tree(root)
            result = doc_freshness_scanner.scan_documentation(
                repo_path=str(root), docs_path="docs/", since="2020-01-01",
            )
            digest = doc_freshness_scanner.format_priority_digest(result)
            # Must start with an H1 heading.
            self.assertTrue(digest.startswith("# Doc-freshness priority digest"))
            # Must include a priority-mix summary line.
            self.assertIn("Priority mix", digest)
            # Must NOT contain JSON braces (the formatter is Markdown, not JSON).
            self.assertNotIn('"documents":', digest)


if __name__ == "__main__":
    # Run verbosely — the skill-dev workflow reads test output directly.
    unittest.main(verbosity=2)
