"""local_bm25_recall — 本地 BM25 词法召回 / Local BM25 lexical recall.

MS-DES-0004: a third local recall strategy that runs a BM25 lexical search
against the skill library's name, description, and full SKILL.md body. It
complements ``LocalDbRecall`` (dense-vector retrieval) by catching queries
where lexical precision matters — exact skill names, tool identifiers,
document IDs, keywords that appear only in the body text.

The strategy is additive: it does not replace the vector pipeline, and the
score fusion inside ``MultiRecall._rerank_candidates()`` combines BM25 and
vector rankings via reciprocal rank fusion (RRF).

Design notes:

* **Stdlib-only.** No ``rank_bm25``, no ``whoosh``, no ``nltk``. The BM25
  math is short, the corpus is small (tens-to-hundreds of skills), and
  shipping a third-party dependency for this much code costs more than it
  saves. See MS-DES-0004 § "Alternatives considered" for the rationale.

* **In-memory index.** The index lives entirely in Python dicts. Rebuild is
  cheap (sub-second for ~500 skills on laptop-class hardware). We do not
  persist to disk in v1.

* **Field weighting by token repetition.** Instead of implementing full
  BM25F, we repeat name tokens ``W_NAME`` times, description tokens
  ``W_DESC`` times, and body tokens ``W_BODY`` times before merging into
  the scoring corpus. This is a deliberate simplification — BM25F would be
  more principled but is roughly 3x the code for marginal gains at our
  corpus size.

* **Atomic rebuild.** ``rebuild()`` builds the new index into a local
  variable first, then swaps it in at the end. A partial build never
  becomes the live index.

Typical lifecycle::

    recall = LocalBm25Recall(skills_dir=config.skills_dir)
    # Index builds lazily on first query.
    results = await recall.search("changelog writer", k=10)
    # When a skill is installed or removed, invalidate the index:
    recall.invalidate()
"""

from __future__ import annotations

import math
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from core.skill.loader import SkillLoader
from core.skill.schema import Skill
from utils.logger import get_logger

from .base import BaseRecall
from .schema import RecallCandidate

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Tuning constants — exposed as module-level constants (not config) per
# MS-DES-0004 open-question #3 / #4 / #5 recommendations. Promote into
# ``SkillConfig`` only if real-world queries surface tuning needs.
# -----------------------------------------------------------------------------

#: BM25 k1 parameter — term-frequency saturation knob.
#: 1.2 is the canonical default from Robertson & Zaragoza.
BM25_K1: float = 1.2

#: BM25 b parameter — length-normalization knob (0 = off, 1 = full).
#: 0.75 is the canonical default.
BM25_B: float = 0.75

#: Reciprocal Rank Fusion is a property of the fusion stage, not of this
#: strategy, and this module never consumed it. The canonical ``RRF_K``
#: lives in ``multi_recall.py`` — see MS-DES-0013. A duplicate literal used
#: to sit here, documented as the canonical source but read by nothing, so
#: retuning it had no effect on fusion.

#: Field-weighting factors applied by token repetition before scoring.
#: name >> description >> body is the intuition: a query that matches the
#: skill's name is very likely the right hit; a match in the body is weaker
#: evidence. These are deliberately small integers — large repetitions
#: bloat the corpus without improving rank quality.
W_NAME: int = 4
W_DESC: int = 2
W_BODY: int = 1

#: Minimum token length to keep after tokenization. Single characters almost
#: always reduce precision (e.g., stray letters from hyphenated words).
MIN_TOKEN_LENGTH: int = 2

#: A small hand-curated English stopword set. Kept short on purpose —
#: BM25's IDF term already downweights them, but dropping them produces
#: cleaner rank output for human inspection during the "is this working?"
#: phase. See MS-DES-0004 open-question #1 / #2.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "has", "have", "he", "in", "is", "it", "its", "of", "on", "or",
        "that", "the", "this", "to", "was", "were", "will", "with",
        "you", "your",
    }
)

#: Tokenization regex. ``[^\W_]+`` under the UNICODE flag keeps sequences of
#: Unicode letters and digits, dropping underscores and punctuation. This
#: intentionally leaves CJK runs intact (they are "word" characters under
#: the Unicode flag) so they tokenize into single runs rather than
#: being split character-by-character.
_TOKEN_RE: re.Pattern[str] = re.compile(r"[^\W_]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Tokenize ``text`` for BM25 indexing.

    Pipeline:

    1. NFKC-normalize (collapses full-width punctuation, compatibility
       forms, etc. into their canonical Latin equivalents).
    2. Lowercase.
    3. Split on non-word characters (anything that is not a Unicode letter
       or digit).
    4. Drop tokens shorter than ``MIN_TOKEN_LENGTH``.
    5. Drop tokens that match the ``STOPWORDS`` set.

    Intentionally language-naive. We do not stem, lemmatize, or apply any
    language-specific morphology. The Memento-Skills corpus is primarily
    English, and BM25's IDF term handles morphological variants well enough
    at small corpus sizes.

    Args:
        text: Raw input text. Empty / ``None`` acceptable.

    Returns:
        A list of tokens in original order (BM25 scoring treats tokens as
        a bag, but preserving order makes the function easier to debug).
    """
    if not text:
        return []
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens = _TOKEN_RE.findall(normalized)
    return [
        t for t in tokens
        if len(t) >= MIN_TOKEN_LENGTH and t not in STOPWORDS
    ]


# -----------------------------------------------------------------------------
# Bm25Index — private in-memory index structure
# -----------------------------------------------------------------------------


@dataclass
class _IndexEntry:
    """Per-document accounting inside the BM25 index.

    Stored under ``Bm25Index.documents[skill_name]``. Exists so the index
    can incrementally rebuild without re-tokenizing every skill.
    """

    name_tokens: list[str] = field(default_factory=list)
    description_tokens: list[str] = field(default_factory=list)
    body_tokens: list[str] = field(default_factory=list)
    merged_tokens: list[str] = field(default_factory=list)  # Post-weighting bag.
    term_freqs: dict[str, int] = field(default_factory=dict)
    doc_length: int = 0


class Bm25Index:
    """A pure-Python BM25 index over a fixed corpus.

    The index owns per-document token lists, term frequencies, corpus-wide
    document frequencies, and average document length. Rebuilding is cheap
    enough that we do not implement incremental updates — every
    ``rebuild()`` call re-tokenizes from scratch and atomically replaces
    the in-memory state.

    Not thread-safe for concurrent writers. The containing
    ``LocalBm25Recall`` serializes writes with a lock.
    """

    def __init__(self) -> None:
        # Maps skill_name -> _IndexEntry.
        self.documents: dict[str, _IndexEntry] = {}
        # Corpus-wide document frequencies: term -> number of docs containing it.
        self.doc_freqs: dict[str, int] = {}
        self.n_docs: int = 0
        self.avg_doc_length: float = 0.0

    # -------------------------------------------------------------------------
    # Construction helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _merged_bag(
        name_tokens: list[str],
        description_tokens: list[str],
        body_tokens: list[str],
    ) -> list[str]:
        """Apply field weighting by repeating tokens per field weight.

        Produces the bag of tokens that actually feeds BM25 scoring. Token
        repetition is the simplest stand-in for BM25F's per-field term
        frequency accounting — cheap, correct for our scale, and easy to
        explain.
        """
        return (
            name_tokens * W_NAME
            + description_tokens * W_DESC
            + body_tokens * W_BODY
        )

    @classmethod
    def build(cls, skills: Iterable[Skill]) -> "Bm25Index":
        """Build a fresh index from the given skills.

        Args:
            skills: Any iterable of ``Skill`` objects. Order does not
                matter.

        Returns:
            A new, fully-populated ``Bm25Index``.
        """
        index = cls()

        for skill in skills:
            name_tokens = _tokenize(skill.name.replace("_", " "))
            description_tokens = _tokenize(skill.description or "")
            body_tokens = _tokenize(skill.content or "")

            merged = cls._merged_bag(name_tokens, description_tokens, body_tokens)

            # Per-document term frequency.
            tf: dict[str, int] = {}
            for token in merged:
                tf[token] = tf.get(token, 0) + 1

            entry = _IndexEntry(
                name_tokens=name_tokens,
                description_tokens=description_tokens,
                body_tokens=body_tokens,
                merged_tokens=merged,
                term_freqs=tf,
                doc_length=len(merged),
            )
            index.documents[skill.name] = entry

            # Corpus-wide document frequency — a term counts once per doc.
            for term in tf.keys():
                index.doc_freqs[term] = index.doc_freqs.get(term, 0) + 1

        index.n_docs = len(index.documents)
        if index.n_docs > 0:
            total_length = sum(e.doc_length for e in index.documents.values())
            index.avg_doc_length = total_length / index.n_docs
        else:
            index.avg_doc_length = 0.0

        return index

    # -------------------------------------------------------------------------
    # Scoring
    # -------------------------------------------------------------------------

    def _idf(self, term: str) -> float:
        """Compute the smoothed BM25 IDF for a single term.

        Uses the Robertson-Spärck-Jones formula with the ``+0.5`` /
        ``+1`` smoothing from the BM25+ family to keep the IDF
        non-negative for very common terms::

            idf(t) = ln( 1 + (N - df(t) + 0.5) / (df(t) + 0.5) )

        This matches the formula used by Lucene and ``rank_bm25``.
        """
        df = self.doc_freqs.get(term, 0)
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score(self, query_tokens: list[str], skill_name: str) -> float:
        """Score a single document against a tokenized query.

        Args:
            query_tokens: The query, already tokenized.
            skill_name: The document to score.

        Returns:
            A non-negative BM25 score. Zero means the document does not
            contain any of the query's terms (or the document is not in
            the index).
        """
        entry = self.documents.get(skill_name)
        if entry is None or not query_tokens:
            return 0.0

        dl = entry.doc_length
        if dl == 0:
            return 0.0

        length_norm = 1.0 - BM25_B + BM25_B * (dl / self.avg_doc_length)

        score = 0.0
        for term in query_tokens:
            tf = entry.term_freqs.get(term, 0)
            if tf == 0:
                continue
            idf = self._idf(term)
            numerator = tf * (BM25_K1 + 1.0)
            denominator = tf + BM25_K1 * length_norm
            score += idf * (numerator / denominator)

        # Defensive clamp — BM25 over finite integers cannot produce
        # non-finite values, but guard anyway. Matches MS-DES-0004
        # "Error handling".
        if not math.isfinite(score) or score < 0:
            logger.error(
                "[BM25] Non-finite or negative score detected: {} for '{}'",
                score,
                skill_name,
            )
            return 0.0

        return score

    def rank(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """Rank every document in the index against the query.

        Args:
            query: Raw query string. Tokenization happens here.
            k: Maximum number of results to return.

        Returns:
            A list of ``(skill_name, score)`` tuples sorted by score
            descending, score-0 entries pruned, truncated to ``k``.
        """
        query_tokens = _tokenize(query)
        if not query_tokens or self.n_docs == 0:
            return []

        scored: list[tuple[str, float]] = []
        for name in self.documents.keys():
            s = self.score(query_tokens, name)
            if s > 0:
                scored.append((name, s))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


# -----------------------------------------------------------------------------
# LocalBm25Recall — public strategy class
# -----------------------------------------------------------------------------


class LocalBm25Recall(BaseRecall):
    """Local BM25 lexical recall strategy.

    Mirrors ``LocalFileRecall``'s directory-scan pattern: the strategy
    enumerates SKILL.md files under a configured ``skills_dir``, loads
    each one with ``SkillLoader``, and maintains an in-memory BM25 index
    over the resulting corpus.

    The index rebuilds:

    * On first ``search()`` call after construction (lazy warm-up).
    * Whenever the ``skills_dir``'s on-disk signature changes
      (add / remove / modify of any ``SKILL.md``).
    * Whenever ``invalidate()`` is called explicitly.

    ``search()`` returns a list of ``RecallCandidate`` with
    ``match_type="bm25"`` and populated ``bm25_score``. The ``score``
    field is set to the same BM25 score for backward compatibility with
    callers that do not know about the new field.

    Args:
        skills_dir: Root directory containing one subdirectory per skill.
    """

    def __init__(self, skills_dir: Path | str) -> None:
        self._skills_dir: Path = Path(skills_dir)
        self._loader: SkillLoader = SkillLoader(self._skills_dir)
        self._index: Bm25Index = Bm25Index()
        self._index_built: bool = False
        self._dir_signature: str = ""
        self._last_build_time: float = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config: "SkillConfig") -> "LocalBm25Recall":
        """Build a ``LocalBm25Recall`` from a ``SkillConfig``.

        Mirrors the factory pattern on the other local strategies so
        ``MultiRecall.from_config`` can construct all three uniformly.

        Args:
            config: Active skill configuration.

        Returns:
            A ready-to-use ``LocalBm25Recall``. The index is *not* built
            here; the first ``search()`` call warms it up.
        """
        return cls(config.skills_dir)

    # -------------------------------------------------------------------------
    # BaseRecall interface
    # -------------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Strategy name used in logs and diagnostics."""
        return "local_bm25"

    def is_available(self) -> bool:
        """Return True when the skills directory exists."""
        return self._skills_dir.exists() and self._skills_dir.is_dir()

    async def search(
        self,
        query: str,
        k: int = 10,
        **kwargs,
    ) -> list[RecallCandidate]:
        """Execute a BM25 lexical search.

        Args:
            query: User query string. Empty / whitespace / stopword-only
                queries produce an empty result list without touching the
                index.
            k: Maximum number of results.
            **kwargs: Ignored. Accepted for signature compatibility with
                the other recall strategies.

        Returns:
            A list of ``RecallCandidate`` sorted by BM25 score descending.
            Each candidate has ``match_type="bm25"``, ``source="local"``,
            and ``bm25_score`` populated. ``score`` is set to the BM25
            score for backward compatibility with old callers.
        """
        if not query or not query.strip():
            return []

        self._ensure_index()
        if self._index.n_docs == 0:
            return []

        ranked = self._index.rank(query, k=k)
        if not ranked:
            return []

        # Map each scored skill back to a RecallCandidate. We want the
        # caller to see the full Skill object for local candidates, so we
        # reach back into the loader. This is cheap — the loader caches.
        candidates: list[RecallCandidate] = []
        for skill_name, score in ranked:
            skill = self._resolve_skill(skill_name)
            candidates.append(
                RecallCandidate(
                    name=skill_name,
                    description=(skill.description if skill else "") or "",
                    source="local",
                    score=score,
                    match_type="bm25",
                    skill=skill,
                    bm25_score=score,
                )
            )

        logger.debug(
            "[LOCAL_BM25] query='{}' → {} candidates (top_score={:.3f})",
            query,
            len(candidates),
            candidates[0].bm25_score if candidates else 0.0,
        )
        return candidates

    # -------------------------------------------------------------------------
    # Index lifecycle
    # -------------------------------------------------------------------------

    def rebuild(self) -> None:
        """Rebuild the in-memory BM25 index from scratch.

        Idempotent: calling twice in a row produces byte-identical state
        (corpus ordering is stable because ``Bm25Index.build`` iterates in
        whatever order the caller hands it; we hand it a sorted list to
        lock ordering down).
        """
        with self._lock:
            start = time.time()
            skills = self._collect_skills()
            new_index = Bm25Index.build(skills)

            # Atomic swap.
            self._index = new_index
            self._index_built = True
            self._dir_signature = self._compute_dir_signature()
            self._last_build_time = time.time()

            elapsed_ms = (time.time() - start) * 1000.0
            logger.debug(
                "[LOCAL_BM25] Index rebuilt: {} skills, avg_doc_length={:.1f}, "
                "unique_terms={}, took={:.1f}ms",
                new_index.n_docs,
                new_index.avg_doc_length,
                len(new_index.doc_freqs),
                elapsed_ms,
            )

    def invalidate(self) -> None:
        """Mark the current index as stale.

        Cheap operation — does not rebuild. The next ``search()`` call
        will trigger ``rebuild()``.

        Use when a caller adds or removes a skill outside the directory
        scan (e.g., after ``SkillStore.add_skill`` completes).
        """
        with self._lock:
            self._index_built = False

    def get_stats(self) -> dict:
        """Extended stats for diagnostics."""
        stats = super().get_stats()
        stats.update(
            {
                "skills_dir": str(self._skills_dir),
                "indexed_skills": self._index.n_docs,
                "unique_terms": len(self._index.doc_freqs),
                "avg_doc_length": self._index.avg_doc_length,
                "last_build_time": self._last_build_time,
                "index_built": self._index_built,
            }
        )
        return stats

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def _ensure_index(self) -> None:
        """Lazily build or rebuild the index if anything has changed."""
        if not self._index_built:
            self.rebuild()
            return
        current_sig = self._compute_dir_signature()
        if current_sig != self._dir_signature:
            logger.debug(
                "[LOCAL_BM25] Directory signature changed — rebuilding index"
            )
            self.rebuild()

    def _collect_skills(self) -> list[Skill]:
        """Walk the skills directory and load every skill.

        We use the loader's lightweight mode (``full=False``) because
        BM25 only needs ``name``, ``description``, and ``content`` —
        nothing from ``scripts/`` or ``references/``. That keeps rebuild
        cheap.

        Returns:
            A list of ``Skill`` objects sorted by name, for deterministic
            index construction.
        """
        if not self._skills_dir.exists():
            return []

        collected: list[Skill] = []
        for item in sorted(self._skills_dir.iterdir()):
            if not item.is_dir():
                continue
            if not (item / "SKILL.md").exists():
                continue
            try:
                skill = self._loader.load_from_dir(item, full=False)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "[LOCAL_BM25] Failed to load skill from '{}': {}", item, exc
                )
                continue
            if skill is not None:
                collected.append(skill)

        # Sorted for deterministic index state (helps with idempotence
        # testing and diffing between runs).
        collected.sort(key=lambda s: s.name)
        return collected

    def _resolve_skill(self, skill_name: str) -> Optional[Skill]:
        """Load the full ``Skill`` object for a given name.

        Called during ``search()`` so candidates carry back their
        ``Skill`` object to consumers that need it (e.g., the gateway's
        rerank path).
        """
        try:
            # Prefer the already-loaded lightweight copy from the indexing
            # pass. We do not have a direct handle to it here (the index
            # doesn't carry Skill objects on purpose — only tokens), so go
            # through the loader; it caches per-name.
            normalized = skill_name.replace("-", "_")
            return self._loader.load(normalized)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "[LOCAL_BM25] Failed to resolve skill '{}': {}", skill_name, exc
            )
            return None

    def _compute_dir_signature(self) -> str:
        """Cheap change-detection signature for the skills directory.

        Mirrors ``LocalFileRecall._compute_dir_signature`` — we do not
        share code because the two strategies have subtly different
        invalidation needs, and a shared helper would couple them.

        Returns:
            An opaque string that changes whenever any ``SKILL.md``
            inside ``skills_dir`` is added, removed, or modified.
        """
        if not self._skills_dir.exists():
            return ""
        parts: list[str] = []
        for item in sorted(self._skills_dir.iterdir()):
            if not item.is_dir():
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                stat = skill_md.stat()
                parts.append(f"{item.name}:{stat.st_mtime:.6f}:{stat.st_size}")
            except OSError:  # pragma: no cover — defensive
                continue
        return "|".join(parts)
