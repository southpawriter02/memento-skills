"""test_bm25_parity.py — drift tripwire for the duplicated BM25 primitives.

MS-DES-0013.

``skills/doc-freshness/scripts/doc_importance.py`` carries a deliberate port
of the tokenizer and tuning constants from
``core/skill/retrieval/local_bm25_recall.py``. MS-DES-0009 chose to port
rather than import so that scripts under ``skills/*/scripts/`` stay
stdlib-only and importable in isolation. That decision stands.

What did not exist until this file is an alarm. ``test_doc_importance.py``
is documented as testing "parity with upstream ``local_bm25_recall``", but
every assertion there compares the port against a *hardcoded literal* — it
never imports the upstream module, so it cannot see upstream change. Add a
stopword to ``local_bm25_recall.STOPWORDS`` and both suites stay green while
the two tokenizers silently disagree.

This file is the one place allowed to import both sides. It lives in the
pytest suite rather than the skill's stdlib suite because
``skills/*/scripts/`` must not reach into ``core.*`` — doing so there would
break the isolation guarantee that the port exists to protect.

Scope of the contract — read this before "fixing" a failure:

    Same tokens in, same tuning constants. The scoring layers above them
    may differ.

Scoring parity between ``Bm25Index`` and ``DocBm25Index`` is **explicitly
out of contract**. The port is a deliberate simplification: ``DocBm25Index``
has no field weighting (no ``W_NAME`` / ``W_DESC`` / ``W_BODY``) and its
corpus unit is a Markdown document rather than a ``SKILL.md`` triple.
Asserting score equality would force the two implementations to converge,
which is precisely the consolidation MS-DES-0013 rejects.

When one of these tests fails there are exactly two legitimate remedies:

1. The divergence was accidental — sync the port back to upstream.
2. The divergence is intentional — amend the contract table in
   ``docs/design/bm25-shared-primitives-parity.md`` and this file in the
   same commit, so the decision is reviewable rather than silent.

Usage::

    pytest tests/test_skills/retrieval/test_bm25_parity.py -v
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_FRESHNESS_SCRIPTS = REPO_ROOT / "skills" / "doc-freshness" / "scripts"
RETRIEVAL_DIR = REPO_ROOT / "core" / "skill" / "retrieval"

# ``doc_importance`` is a standalone script, not an installed package — put
# its directory on the path the same way its own test suite does.
if str(DOC_FRESHNESS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DOC_FRESHNESS_SCRIPTS))

import doc_importance  # noqa: E402

from core.skill.retrieval import local_bm25_recall  # noqa: E402


#: Paths quoted in failure messages so a reader can act without first
#: reconstructing MS-DES-0013 from scratch.
_UPSTREAM = "core/skill/retrieval/local_bm25_recall.py"
_PORT = "skills/doc-freshness/scripts/doc_importance.py"
_REMEDY = (
    f"Sync the port in {_PORT} back to {_UPSTREAM}, or — if the divergence "
    "is intentional — amend the contract table in "
    "docs/design/bm25-shared-primitives-parity.md (MS-DES-0013) and this "
    "test in the same commit."
)


# ---------------------------------------------------------------------------
# Group 1 — tuning-constant parity
# ---------------------------------------------------------------------------


class TestTuningConstantParity:
    """The five shared symbols in the MS-DES-0013 contract table."""

    def test_bm25_k1_matches(self):
        assert doc_importance.BM25_K1 == local_bm25_recall.BM25_K1, (
            f"BM25_K1 drifted: {_PORT} has {doc_importance.BM25_K1}, "
            f"{_UPSTREAM} has {local_bm25_recall.BM25_K1}. {_REMEDY}"
        )

    def test_bm25_b_matches(self):
        assert doc_importance.BM25_B == local_bm25_recall.BM25_B, (
            f"BM25_B drifted: {_PORT} has {doc_importance.BM25_B}, "
            f"{_UPSTREAM} has {local_bm25_recall.BM25_B}. {_REMEDY}"
        )

    def test_min_token_length_matches(self):
        assert (
            doc_importance.MIN_TOKEN_LENGTH == local_bm25_recall.MIN_TOKEN_LENGTH
        ), (
            f"MIN_TOKEN_LENGTH drifted: {_PORT} has "
            f"{doc_importance.MIN_TOKEN_LENGTH}, {_UPSTREAM} has "
            f"{local_bm25_recall.MIN_TOKEN_LENGTH}. {_REMEDY}"
        )

    def test_stopwords_match(self):
        port = set(doc_importance.STOPWORDS)
        upstream = set(local_bm25_recall.STOPWORDS)
        assert port == upstream, (
            "STOPWORDS drifted. "
            f"Only in {_PORT}: {sorted(port - upstream)}. "
            f"Only in {_UPSTREAM}: {sorted(upstream - port)}. {_REMEDY}"
        )

    def test_token_regex_matches(self):
        assert (
            doc_importance._TOKEN_RE.pattern == local_bm25_recall._TOKEN_RE.pattern
        ), (
            f"_TOKEN_RE drifted: {_PORT} has "
            f"{doc_importance._TOKEN_RE.pattern!r}, {_UPSTREAM} has "
            f"{local_bm25_recall._TOKEN_RE.pattern!r}. {_REMEDY}"
        )


# ---------------------------------------------------------------------------
# Group 2 — tokenizer output parity
# ---------------------------------------------------------------------------


#: One shared corpus fed to both live functions. This is the property the
#: hardcoded canaries in test_doc_importance.py cannot express: they pin the
#: port to a literal, not to upstream.
PARITY_CORPUS = [
    pytest.param("The quick brown fox jumps over the lazy dog", id="english"),
    pytest.param("the and of to with by from", id="stopwords-only"),
    pytest.param("快速的棕色狐狸", id="cjk-run"),
    pytest.param("The API is 本地_BM25 compatible", id="mixed-script-underscore"),
    pytest.param("well-known state-of-the-art design", id="hyphenation"),
    pytest.param("Release v0.3.0 shipped today", id="version-literal"),
    pytest.param("See config.json and pyproject.toml", id="dotted-paths"),
    pytest.param("MS-DES-0004 supersedes MS-ANA-0001", id="spec-identifiers"),
    pytest.param("a I x y z", id="single-chars"),
    pytest.param("", id="empty-string"),
    pytest.param(None, id="none"),
    pytest.param("ｆｕｌｌ　ｗｉｄｔｈ ＡＰＩ", id="nfkc-fullwidth"),
    pytest.param("   leading and trailing   whitespace   ", id="whitespace"),
    pytest.param("Ünïcödé àccénts café naïve", id="accented-latin"),
    pytest.param("BM25 k1=1.2 b=0.75 tuning", id="constants-in-prose"),
    pytest.param("Skill Market fusion — RRF over two lists", id="em-dash"),
]


class TestTokenizerParity:
    """``_tokenize`` must agree function-to-function, not against literals."""

    @pytest.mark.parametrize("text", PARITY_CORPUS)
    def test_tokenize_agrees(self, text):
        upstream = local_bm25_recall._tokenize(text)
        port = doc_importance._tokenize(text)
        assert port == upstream, (
            f"_tokenize diverged on {text!r}.\n"
            f"  {_PORT}: {port}\n"
            f"  {_UPSTREAM}: {upstream}\n"
            f"{_REMEDY}"
        )


# ---------------------------------------------------------------------------
# Group 3 — single-declaration guard for RRF_K (MS-DES-0013 part 1)
# ---------------------------------------------------------------------------


#: Matches a module-level binding assignment such as ``RRF_K: int = 60`` or
#: ``RRF_K = 60``. Deliberately anchored to column zero so references inside
#: functions, comments, and docstrings do not count.
_RRF_K_BINDING = re.compile(r"^RRF_K\s*(?::[^=]+)?=", re.MULTILINE)


class TestRrfKSingleDeclaration:
    """``RRF_K`` is declared once, in the module that consumes it."""

    def test_exactly_one_binding_in_retrieval_package(self):
        found = {
            path.relative_to(REPO_ROOT).as_posix(): len(
                _RRF_K_BINDING.findall(path.read_text(encoding="utf-8"))
            )
            for path in sorted(RETRIEVAL_DIR.glob("*.py"))
        }
        declaring = {path: n for path, n in found.items() if n}
        assert declaring == {"core/skill/retrieval/multi_recall.py": 1}, (
            "RRF_K must be declared exactly once, in multi_recall.py (the "
            f"only consumer). Found: {declaring}. A second declaration "
            "reintroduces the MS-DES-0013 defect where the copy documented "
            "as canonical is read by nothing, so retuning it silently does "
            "nothing."
        )

    def test_canonical_value_is_importable_from_multi_recall(self):
        from core.skill.retrieval.multi_recall import RRF_K

        assert RRF_K == 60

    def test_local_bm25_recall_no_longer_exports_rrf_k(self):
        assert not hasattr(local_bm25_recall, "RRF_K"), (
            "local_bm25_recall should no longer bind RRF_K — it never "
            "consumed it, and the stale copy is what MS-DES-0013 removed. "
            "Import it from core.skill.retrieval.multi_recall instead."
        )
