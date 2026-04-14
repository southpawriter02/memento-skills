# `SkillGateway` — API reference

> **Module:** `core.skill.gateway`
> **Source:** [`core/skill/gateway.py`](../../core/skill/gateway.py)
> **Generated:** 2026-04-13 by the `doc-generator` skill from an AST extraction, then lightly edited for prose and to translate Chinese docstrings.

`SkillGateway` is the single public entry point into the skill subsystem. It wraps three internal layers — the on-disk skill directory, a runtime executor, and a lightweight governance layer — behind a small, stable interface. External callers should never import directly from `core.skill.store`, `core.skill.execution`, or `core.skill.retrieval`; everything goes through the gateway.

Production code should construct a gateway via the `from_config` factory rather than calling `__init__` directly. The factory builds the store, the multi-recall retriever, the executor, and the LLM client for you.

## Class signature

```python
class SkillGateway:
    def __init__(
        self,
        config: SkillConfig,
        store: SkillStore,
        multi_recall: MultiRecall | None = None,
        executor: SkillExecutor | None = None,
        llm: LLMClient | None = None,
    ) -> None: ...
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config` | `SkillConfig` | yes | Runtime configuration object. |
| `store` | `SkillStore` | yes | Backing skill store. Build with `SkillStore.from_config()`. |
| `multi_recall` | `MultiRecall \| None` | no | Retrieval strategy wrapper. If omitted, remote recall is unavailable. |
| `executor` | `SkillExecutor \| None` | no | Skill executor. If omitted, `execute()` will fail. |
| `llm` | `LLMClient \| None` | no | LLM client used by retrieval strategies that need reranking. |

For production use, call `SkillGateway.from_config()` instead of constructing directly.

## Methods

### `from_config(config=None)` — async classmethod

Factory that builds a fully-wired gateway from a `SkillConfig`. If `config` is `None`, the global configuration is loaded automatically.

```python
gateway = await SkillGateway.from_config()
```

**Returns:** `SkillGateway` — a ready-to-use gateway with store, retrieval, executor, and LLM client attached.

### `skill_store` — property

Read-only access to the underlying `SkillStore`. Exposed for inspection and for advanced callers that need to enumerate skills without going through `discover()`. Don't mutate through this handle.

### `discover(strategy, query="", k=10)` — async

Discover available skills by strategy.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `strategy` | `DiscoverStrategy \| str` | `DiscoverStrategy.LOCAL_ONLY` | `LOCAL_ONLY` returns every skill in the local store. `MULTI_RECALL` runs the retrieval pipeline. |
| `query` | `str` | `""` | Search string. Required when `strategy == MULTI_RECALL`. |
| `k` | `int` | `10` | Maximum number of candidates to return under `MULTI_RECALL`. |

**Returns:** `list[SkillManifest]` — the matching skill manifests, or `[]` if any error occurs. Failures are logged but not raised.

### `search(query, k=10, cloud_only=false)` — async

Search for skills in the cloud Skill Market. Useful for discovering skills that aren't yet installed locally.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | — | Search string. |
| `k` | `int` | `10` | Maximum results. |
| `cloud_only` | `bool` | `False` | If `True`, skip local results and return only Market hits. |

**Returns:** `list[SkillManifest]` — zero-or-more matching manifests.

### `execute(skill_name, params=none, options=none, session_id=none, on_step=none)` — async

Run an installed skill end-to-end inside the sandboxed executor.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skill_name` | `str` | — | Name of the skill to run. Must already be installed locally. |
| `params` | `dict \| None` | `None` | Parameters passed to the skill. |
| `options` | `ExecuteOptions \| None` | `None` | Runtime options (timeouts, resource limits, etc.). |
| `session_id` | `str \| None` | `None` | Groups related executions into a single session for logging and context. |
| `on_step` | `Callable \| None` | `None` | Optional async callback invoked on every ReAct step. Useful for live UIs. |

**Returns:** The skill's output, shape-dependent on the skill. Raises on skill failure — unlike `discover`, errors here are meant to be handled by the caller.

### `install(skill_name)` — async

Install a skill from the cloud Skill Market into the local store. Idempotent: reinstalling an already-installed skill is a no-op unless the Market has a newer version.

| Parameter | Type | Description |
|-----------|------|-------------|
| `skill_name` | `str` | Name of the skill to install. |

**Returns:** The installed `SkillManifest`, or raises if installation fails (network error, manifest invalid, signature mismatch).

## Typical usage

```python
from core.skill import SkillGateway

gateway = await SkillGateway.from_config()

# 1. Find candidate skills by semantic search
manifests = await gateway.discover(
    strategy="multi_recall",
    query="summarize a Git changelog",
    k=5,
)

# 2. If the best candidate isn't installed, pull it from the Market
if manifests and not manifests[0].is_local:
    await gateway.install(manifests[0].name)

# 3. Run it
result = await gateway.execute(
    skill_name=manifests[0].name,
    params={"since": "v0.2.0"},
    session_id="release-prep-2026-04",
)
```

## Observations from generating this doc

- Most docstrings in the source are in Chinese. The `extract_signatures.py` script captures them verbatim; translating them is currently a manual step. Candidate for Phase 2: add an optional translation pass to the generator.
- Parameter type annotations are sometimes quoted strings (`'SkillConfig'`), sometimes unquoted (`DiscoverStrategy | str`). The extractor preserves the original form, which means generated docs inherit that inconsistency. Minor cosmetic issue in the upstream code rather than the extractor.
- No top-level functions were found — the entire public surface of this module is the single class. The generator handled the empty-functions case cleanly.
