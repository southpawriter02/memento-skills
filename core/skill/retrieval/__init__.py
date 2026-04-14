"""retrieval — 技能检索 / Skill retrieval layer.

Strategies:

* ``LocalFileRecall`` — enumerate every installed skill (always available).
* ``LocalDbRecall`` — dense-vector retrieval via sqlite-vec (optional
  dependency).
* ``LocalBm25Recall`` — pure-Python BM25 lexical retrieval (MS-DES-0004).
* ``RemoteRecall`` — cloud Market search (optional, config-driven).

The ``MultiRecall`` orchestrator fuses BM25 and vector rankings via RRF
with ``k = 60`` and enforces the local-before-remote tier rule. See
``docs/design/bm25-retrieval-layer.md`` for the full design.
"""

from .base import BaseRecall
from .local_bm25_recall import LocalBm25Recall
from .local_file_recall import LocalFileRecall
from .multi_recall import MultiRecall
from .remote_recall import RemoteRecall
from .schema import RecallCandidate

# LocalDbRecall 是可选的（依赖 sqlite-vec）/ Optional: depends on sqlite-vec.
try:
    from .local_db_recall import LocalDbRecall

    __all__ = [
        "BaseRecall",
        "LocalBm25Recall",
        "LocalDbRecall",
        "LocalFileRecall",
        "MultiRecall",
        "RecallCandidate",
        "RemoteRecall",
    ]
except ImportError:
    __all__ = [
        "BaseRecall",
        "LocalBm25Recall",
        "LocalFileRecall",
        "MultiRecall",
        "RecallCandidate",
        "RemoteRecall",
    ]
