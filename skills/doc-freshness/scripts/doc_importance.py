#!/usr/bin/env python3
"""doc_importance.py — per-doc importance scoring for the doc-freshness skill.

This module implements MS-DES-0009 (doc-freshness relevance v2). It produces a
normalized importance score in [0.0, 1.0] for every Markdown document in a
corpus, combining two BM25-derived signals:

1. **Intrinsic content density.** For each doc, the sum of inverse-document-
   frequencies (IDFs) of its top-K most distinctive terms. A doc heavy on
   boilerplate scores low; a doc dense with distinctive technical vocabulary
   scores high. This is the static proxy for "high-traffic doc" that the
   Phase 3 interim retrospective called for.

2. **Inbound reference authority.** The count of other docs in the corpus
   that link to or mention this doc via Markdown links, inline-code spans,
   or bare prose paths. A doc referenced from many places is probably more
   central to the tree than a doc referenced by none.

Both components are max-normalized against the scanned corpus, then combined
via ``importance_score = W_INTRINSIC * intrinsic + W_REFERENCE * reference``.

The BM25 tokenizer and index primitives here are a faithful port of the ones
in ``core/skill/retrieval/local_bm25_recall.py`` (MS-DES-0004). The port is
deliberate — see MS-DES-0009 "Why a ported BM25 module" for why we don't
just import the upstream. The port preserves the tuning constants
(``BM25_K1=1.2``, ``BM25_B=0.75``, ``MIN_TOKEN_LENGTH=2``, same stopword set,
same ``[^\\W_]+`` Unicode tokenization regex) so future divergence is
intentional rather than accidental.

Public surface:

    compute_importance_scores(docs_root, doc_paths) -> dict[str, float]
    classify_priority(score) -> str  # "low" | "medium" | "high"
    PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW  # module-level cutpoints

The scanner (``doc_freshness_scanner.py``) imports these to attach
``importance_score`` and ``priority`` to every doc record.

This module is stdlib-only — it depends only on ``math``, ``re``, and
``unicodedata``. It does *not* import ``doc_freshness_scanner`` (the reverse
dependency direction is preserved).
"""

from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path


# ---------------------------------------------------------------------------
# Tuning constants — ported from core/skill/retrieval/local_bm25_recall.py
# (MS-DES-0004). Changing these changes scoring behavior; any change should
# be accompanied by a regression test and a design-note update.
# ---------------------------------------------------------------------------

#: BM25 k1 parameter — term-frequency saturation knob.
#: 1.2 is the canonical default from Robertson & Zaragoza.
BM25_K1: float = 1.2

#: BM25 b parameter — length-normalization knob (0 = off, 1 = full).
#: 0.75 is the canonical default.
BM25_B: float = 0.75

#: Minimum token length to keep after tokenization. Single characters almost
#: always reduce precision (e.g., stray letters from hyphenated words).
#: Must match ``local_bm25_recall.MIN_TOKEN_LENGTH`` for tokenizer-parity
#: AC #3 in MS-DES-0009.
MIN_TOKEN_LENGTH: int = 2

#: A small hand-curated English stopword set, identical to the upstream set
#: in ``local_bm25_recall.py``. Kept short on purpose — BM25's IDF already
#: downweights common words, but dropping these produces cleaner rank output
#: and matches the upstream tokenizer behavior.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "has", "have", "he", "in", "is", "it", "its", "of", "on", "or",
        "that", "the", "this", "to", "was", "were", "will", "with",
        "you", "your",
    }
)

#: Tokenization regex. ``[^\W_]+`` under the UNICODE flag keeps sequences
#: of Unicode letters and digits, dropping underscores and punctuation.
#: This intentionally leaves CJK runs intact (they are "word" characters
#: under the Unicode flag) so they tokenize into single runs rather than
#: being split character-by-character. Must produce the same token stream
#: as ``local_bm25_recall._TOKEN_RE``.
_TOKEN_RE: re.Pattern[str] = re.compile(r"[^\W_]+", re.UNICODE)


# ---------------------------------------------------------------------------
# Importance-scoring tuning constants — specific to MS-DES-0009
# ---------------------------------------------------------------------------

#: Weight of the intrinsic (BM25-IDF-based) signal in the combined score.
#: W_INTRINSIC + W_REFERENCE must equal 1.0 — the combination is a convex
#: combination so the output stays in [0.0, 1.0] after max-normalization.
W_INTRINSIC: float = 0.6

#: Weight of the inbound-reference-count signal in the combined score.
#: See W_INTRINSIC for the constraint.
W_REFERENCE: float = 0.4

#: Number of "top distinctive terms" to sum IDFs over when computing the
#: per-doc intrinsic score. 10 is a middle-ground choice — small enough
#: to emphasize the most distinctive vocabulary, large enough to survive
#: a doc with 2-3 dominant terms.
TOP_K_TERMS: int = 10

#: Priority bucket cutpoints (tertile-inspired defaults). A doc with
#: ``importance_score >= PRIORITY_HIGH`` is in the "high" bucket; between
#: ``PRIORITY_MEDIUM`` and ``PRIORITY_HIGH`` is "medium"; below is "low".
#: These are deliberately not CLI-configurable — priority is a three-bucket
#: filter per MS-DES-0009, not a continuous knob.
PRIORITY_HIGH: float = 0.66
PRIORITY_MEDIUM: float = 0.33
PRIORITY_LOW: float = 0.0  # lower bound; present for documentation symmetry.


# ---------------------------------------------------------------------------
# Tokenizer — ported from local_bm25_recall._tokenize
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Tokenize ``text`` for BM25 indexing.

    Pipeline (must match ``local_bm25_recall._tokenize`` exactly):

    1. NFKC-normalize (collapses full-width punctuation, compatibility forms,
       etc. into their canonical Latin equivalents).
    2. Lowercase.
    3. Split on non-word characters (anything that is not a Unicode letter
       or digit).
    4. Drop tokens shorter than ``MIN_TOKEN_LENGTH``.
    5. Drop tokens that match the ``STOPWORDS`` set.

    Intentionally language-naive. No stemming, lemmatization, or language-
    specific morphology.

    Args:
        text: Raw input text. Empty string or ``None`` acceptable.

    Returns:
        A list of tokens in original order.
    """
    if not text:
        return []
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens = _TOKEN_RE.findall(normalized)
    return [
        t for t in tokens
        if len(t) >= MIN_TOKEN_LENGTH and t not in STOPWORDS
    ]


# ---------------------------------------------------------------------------
# DocBm25Index — simplified in-memory BM25 index over a doc corpus
# ---------------------------------------------------------------------------
#
# This is a stripped-down sibling of ``local_bm25_recall.Bm25Index``. We drop
# the field-weighting machinery (name/description/body repetition) because
# Markdown docs don't have name-vs-description-vs-body structure the way
# skills do. Each doc is a flat bag of tokens. All other BM25 math —
# term frequencies, document frequencies, average document length, the
# Robertson-Spärck-Jones smoothed IDF formula — is preserved verbatim.


class DocBm25Index:
    """Pure-Python BM25 index over a fixed Markdown doc corpus.

    Build once, query zero or more times. Not thread-safe.

    Per-document state is kept in flat dicts keyed by the doc's string path
    (matches how the scanner addresses docs). The index owns:

    * ``term_freqs[doc_path][term]`` — term frequencies within each doc
    * ``doc_length[doc_path]`` — token count per doc, for BM25 length-norm
    * ``doc_freqs[term]`` — corpus-wide document frequency per term
    * ``n_docs``, ``avg_doc_length`` — corpus aggregates
    """

    def __init__(self) -> None:
        # Per-doc term-frequency maps. Keyed by string doc path so callers
        # can address docs the same way ``doc_freshness_scanner`` does.
        self.term_freqs: dict[str, dict[str, int]] = {}
        # Per-doc total token count (after tokenization + stopword removal).
        self.doc_length: dict[str, int] = {}
        # Corpus-wide: how many docs contain each term at least once.
        self.doc_freqs: dict[str, int] = {}
        # Corpus aggregates.
        self.n_docs: int = 0
        self.avg_doc_length: float = 0.0

    # -------------------------------------------------------------------
    # Construction
    # -------------------------------------------------------------------

    @classmethod
    def build(cls, docs: dict[str, str]) -> "DocBm25Index":
        """Build a fresh index from a mapping of doc-path -> doc-text.

        Args:
            docs: Dict keyed by the doc's string path, valued by the doc's
                raw text (including Markdown syntax — the tokenizer drops
                punctuation so a small amount of markup noise is harmless).

        Returns:
            A fully populated ``DocBm25Index``. Empty input produces an
            index with ``n_docs=0``; all score methods handle this cleanly.
        """
        index = cls()
        for doc_path, text in docs.items():
            tokens = _tokenize(text)

            # Per-document term frequency. Count only — order doesn't matter
            # for BM25 scoring.
            tf: dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1

            index.term_freqs[doc_path] = tf
            index.doc_length[doc_path] = len(tokens)

            # Corpus-wide document frequency: a term counts once per doc,
            # no matter how many times it appears within that doc.
            for term in tf.keys():
                index.doc_freqs[term] = index.doc_freqs.get(term, 0) + 1

        index.n_docs = len(index.term_freqs)
        if index.n_docs > 0:
            total = sum(index.doc_length.values())
            index.avg_doc_length = total / index.n_docs
        else:
            index.avg_doc_length = 0.0

        return index

    # -------------------------------------------------------------------
    # Scoring
    # -------------------------------------------------------------------

    def idf(self, term: str) -> float:
        """Smoothed BM25 IDF for a single term.

        Uses the Robertson-Spärck-Jones formula with +0.5 / +1 smoothing
        from the BM25+ family (identical to upstream ``local_bm25_recall``)::

            idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
        """
        df = self.doc_freqs.get(term, 0)
        if self.n_docs == 0:
            return 0.0
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def top_k_terms(self, doc_path: str, k: int = TOP_K_TERMS) -> list[tuple[str, float]]:
        """Return the top-k most distinctive terms in a single doc.

        "Distinctive" here means highest IDF weighted by the doc's own term
        frequency — a term that appears many times in this doc AND rarely
        across the corpus is the most distinctive.

        Args:
            doc_path: The doc to inspect.
            k: Number of terms to return.

        Returns:
            A list of ``(term, score)`` tuples sorted by score descending.
            ``score = tf * idf`` for that term in that doc. Empty list if
            the doc isn't in the index.
        """
        tf_map = self.term_freqs.get(doc_path)
        if not tf_map:
            return []

        scored = [
            (term, freq * self.idf(term))
            for term, freq in tf_map.items()
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


# ---------------------------------------------------------------------------
# Inbound-reference counting
# ---------------------------------------------------------------------------
#
# For the "reference authority" signal we need to know, for each doc in the
# corpus, how many *other* docs point to it. The doc_freshness_scanner.py
# module already has a robust path-extraction function
# (``extract_path_references``) that handles Markdown links, inline-code
# spans, and bare prose paths with all the repo-boundary and relative-path
# normalization corner cases correctly. Reusing that function would be the
# docs-first move — but to keep this module importable in isolation for
# unit testing (no scanner-side setup needed), we use a small local
# reimplementation that's intentionally narrower: it just needs to find
# which docs reference which OTHER docs, not the full repo-code-reference
# extraction the scanner does. The logic is duplicated by design; the
# scanner's version is the canonical one for code references, this one
# is the canonical one for doc-to-doc references.


# Match Markdown link targets: [text](path) — capturing the path.
_MD_LINK_RE: re.Pattern[str] = re.compile(r"\]\(([^)]+)\)")

# Match inline-code spans that look like a path: `some/path.md`,
# `../other.md`, etc. We require at least one forward slash or a `.md`
# extension to avoid firing on general code snippets like `foo()`.
_INLINE_CODE_PATH_RE: re.Pattern[str] = re.compile(
    r"`([^`]*(?:/|\.md)[^`]*)`"
)


def _extract_doc_references(doc_text: str) -> set[str]:
    """Extract a set of raw path strings that this doc refers to.

    Args:
        doc_text: The raw Markdown text of a single doc.

    Returns:
        A set of raw reference strings (not yet resolved or validated).
        The caller is responsible for resolving these to canonical doc paths.
    """
    refs: set[str] = set()
    for m in _MD_LINK_RE.finditer(doc_text):
        raw = m.group(1).strip()
        # Strip URL fragments (e.g., "foo.md#section") — they point at the
        # same doc, not a different one.
        if "#" in raw:
            raw = raw.split("#", 1)[0]
        # Skip external URLs (http://, https://, mailto:, etc.).
        if "://" in raw or raw.startswith("mailto:"):
            continue
        if raw:
            refs.add(raw)
    for m in _INLINE_CODE_PATH_RE.finditer(doc_text):
        raw = m.group(1).strip()
        if raw:
            refs.add(raw)
    return refs


def _resolve_reference(raw_ref: str, from_doc: Path, docs_root: Path) -> str | None:
    """Resolve a raw reference string to a canonical doc path, if any.

    Args:
        raw_ref: The raw path as it appeared in the doc.
        from_doc: The path of the doc that contained the reference.
        docs_root: The docs-tree root used to compute canonical paths.

    Returns:
        The canonical doc path (relative to ``docs_root``) as a POSIX-style
        string, or ``None`` if the reference doesn't resolve to an existing
        Markdown file under ``docs_root``.
    """
    try:
        # Resolve relative to the doc containing the reference.
        candidate = (from_doc.parent / raw_ref).resolve()
    except (OSError, RuntimeError):
        # Malformed path — don't let a weird input break the scan.
        return None

    # Must live under docs_root. Use resolve() on the root too to handle
    # symlinks identically.
    try:
        docs_root_resolved = docs_root.resolve()
        rel = candidate.relative_to(docs_root_resolved)
    except (ValueError, OSError):
        return None

    # Only count Markdown targets. A reference to a PNG or source file
    # doesn't count as a doc-to-doc reference for authority purposes.
    if candidate.suffix.lower() != ".md":
        return None

    return rel.as_posix()


def _compute_inbound_reference_counts(
    docs_root: Path,
    doc_texts: dict[str, str],
) -> dict[str, int]:
    """Count how many OTHER docs reference each doc in the corpus.

    Args:
        docs_root: Absolute path to the docs tree root.
        doc_texts: Dict keyed by canonical doc path (POSIX-style, relative
            to ``docs_root``), valued by raw Markdown text.

    Returns:
        Dict keyed by canonical doc path, valued by inbound reference count.
        Every doc in ``doc_texts`` appears in the output (count may be 0).
    """
    counts: dict[str, int] = {p: 0 for p in doc_texts.keys()}
    for source_path, text in doc_texts.items():
        source_abs = docs_root / source_path
        for raw_ref in _extract_doc_references(text):
            resolved = _resolve_reference(raw_ref, source_abs, docs_root)
            if resolved is None:
                continue
            if resolved == source_path:
                # Self-reference doesn't count as inbound authority.
                continue
            if resolved in counts:
                counts[resolved] += 1
    return counts


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_importance_scores(
    docs_root: Path,
    doc_paths: list[Path],
) -> dict[str, float]:
    """Compute normalized importance scores for a set of docs.

    Args:
        docs_root: The docs-tree root. Used to resolve relative paths and
            to key the returned dict with stable POSIX-style strings.
        doc_paths: Absolute paths to every Markdown file to score.

    Returns:
        A dict keyed by the doc's POSIX-style path relative to ``docs_root``,
        valued by a float importance score in [0.0, 1.0]. An empty input
        list produces an empty dict. A single-doc corpus produces
        ``{the_one_doc: 1.0}`` (max-normalization denominator is itself).

    Scoring combines two max-normalized signals per MS-DES-0009:

    1. Intrinsic content density: sum of the doc's top-K term IDFs.
    2. Inbound reference authority: count of other docs pointing at it.

    Combined as:

        importance_score = W_INTRINSIC * intrinsic + W_REFERENCE * reference

    where W_INTRINSIC + W_REFERENCE == 1.0, guaranteeing the output stays
    in [0.0, 1.0] after component max-normalization.
    """
    # Empty corpus — return empty dict. AC #1.
    if not doc_paths:
        return {}

    # -----------------------------------------------------------------------
    # Step 1: read each doc exactly once. Build two parallel dicts:
    #   doc_texts keyed by canonical POSIX path -> raw text
    # The canonical path is also the key used in the returned scores dict.
    # -----------------------------------------------------------------------
    docs_root_resolved = docs_root.resolve()
    doc_texts: dict[str, str] = {}
    for abs_path in doc_paths:
        try:
            rel = abs_path.resolve().relative_to(docs_root_resolved)
        except ValueError:
            # Path outside docs_root — skip. Shouldn't happen if caller is
            # well-behaved, but be defensive.
            continue
        canonical = rel.as_posix()
        try:
            doc_texts[canonical] = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Unreadable file — treat as empty text. Scanner already logs
            # read errors elsewhere; don't duplicate that here.
            doc_texts[canonical] = ""

    if not doc_texts:
        return {}

    # -----------------------------------------------------------------------
    # Step 2: build the BM25 index once. All per-doc intrinsic scores come
    # from this single index; no per-doc rebuild cost.
    # -----------------------------------------------------------------------
    index = DocBm25Index.build(doc_texts)

    # -----------------------------------------------------------------------
    # Step 3: compute per-doc intrinsic score = sum of top-K term-idf scores.
    # Then max-normalize across the corpus so the top doc scores 1.0.
    # -----------------------------------------------------------------------
    intrinsic_raw: dict[str, float] = {}
    for doc_path in doc_texts.keys():
        top_terms = index.top_k_terms(doc_path, k=TOP_K_TERMS)
        intrinsic_raw[doc_path] = sum(score for _, score in top_terms)

    max_intrinsic = max(intrinsic_raw.values(), default=0.0)
    if max_intrinsic <= 0:
        # No distinctive terms anywhere — can happen with an all-stopword
        # corpus. Every doc gets 0.0 for the intrinsic component.
        intrinsic_norm = {p: 0.0 for p in intrinsic_raw.keys()}
    else:
        intrinsic_norm = {
            p: raw / max_intrinsic for p, raw in intrinsic_raw.items()
        }

    # -----------------------------------------------------------------------
    # Step 4: compute inbound reference counts and max-normalize.
    # -----------------------------------------------------------------------
    reference_raw = _compute_inbound_reference_counts(docs_root, doc_texts)
    max_reference = max(reference_raw.values(), default=0)
    if max_reference <= 0:
        reference_norm = {p: 0.0 for p in reference_raw.keys()}
    else:
        reference_norm = {
            p: count / max_reference for p, count in reference_raw.items()
        }

    # -----------------------------------------------------------------------
    # Step 5: combine via convex combination. The output is guaranteed to
    # stay in [0.0, 1.0] because both component arrays are in [0.0, 1.0]
    # and W_INTRINSIC + W_REFERENCE == 1.0.
    # -----------------------------------------------------------------------
    scores: dict[str, float] = {}
    for doc_path in doc_texts.keys():
        intrinsic = intrinsic_norm.get(doc_path, 0.0)
        reference = reference_norm.get(doc_path, 0.0)
        combined = W_INTRINSIC * intrinsic + W_REFERENCE * reference
        # Defensive clamp. The arithmetic above cannot exceed 1.0 given the
        # constraints, but floating-point accumulation can technically go
        # a hair above 1.0 — clamp to guarantee the AC #2 invariant.
        if combined > 1.0:
            combined = 1.0
        elif combined < 0.0:
            combined = 0.0
        scores[doc_path] = combined

    return scores


def classify_priority(score: float) -> str:
    """Map a continuous importance score into a discrete priority bucket.

    Args:
        score: An importance score, typically in [0.0, 1.0]. Scores outside
            that range are accepted (clamped to the same bucket as the
            nearest boundary).

    Returns:
        One of ``"low"``, ``"medium"``, ``"high"``. Cutpoints are
        ``PRIORITY_HIGH`` (0.66) and ``PRIORITY_MEDIUM`` (0.33).
    """
    if score >= PRIORITY_HIGH:
        return "high"
    if score >= PRIORITY_MEDIUM:
        return "medium"
    return "low"
