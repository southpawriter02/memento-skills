# `SkillGateway` — API reference

> **Translation summary:** 4 docstrings translated from mixed Han/Latin source. Originals preserved as HTML comments above each translation. Review recommended before publishing. (Classification: 3 target, 0 non_target, 4 mixed, 2 empty, 0 unknown.)

> **Module:** `core.skill.gateway`
> **Source:** [`core/skill/gateway.py`](../../core/skill/gateway.py)
> **Generated:** 2026-04-14 by the `doc-generator` skill with the MS-DES-0003 translation pass enabled. Structure extracted via AST; Chinese docstring fragments translated in-doc with originals preserved as HTML comments.

<!-- Original (han, latin): Agent-Skill 契约层：SkillGateway 实现。 DTO 定义在 schema.py 中，通过 core.skill 包导入。 -->
`SkillGateway` is the Agent-Skill contract layer — the single public entry point into the skill subsystem. DTOs live in `schema.py` and are re-exported through the `core.skill` package, so callers never have to reach into the implementation modules directly.

The gateway wraps three internal layers — the on-disk skill directory, a runtime executor, and a lightweight governance layer — behind a small, stable interface. External callers should never import from `core.skill.store`, `core.skill.execution`, or `core.skill.retrieval`; everything goes through the gateway.

Production code should construct a gateway via the `from_config` factory rather than calling `__init__` directly. The factory builds the store, the multi-recall retriever, the executor, and the LLM client for you.

## Class signature

<!-- Original (han, latin): Skill 契约实现：目录层、运行时层、治理层。 这是唯一的实现类，外部通过此接口与 Skill 系统交互。 内部管理 SkillStore，生产环境通过 core.skill.init_skill_system() 创建。 -->
The skill contract implementation across directory, runtime, and governance layers. This is the only implementation class — external callers interact with the skill system exclusively through this interface. Internally the gateway manages a `SkillStore`; in production it is constructed via `core.skill.init_skill_system()`.

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

<!-- Original (han, latin): 初始化 SkillGateway。 Args: config: SkillConfig 配置对象（必需） store: SkillStore 实例（必需，使用 SkillStore.from_config() 创建） multi_recall: 可选的 MultiRecall（内部包含 RemoteRecall 等策略） executor: 可选的 SkillExecutor llm: 可选的 LLM 客户端 注意：生产环境使用 init_skill_system() 或 from_config() 工厂方法。 -->

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config` | `SkillConfig` | yes | Runtime configuration object. |
| `store` | `SkillStore` | yes | Backing skill store. Build with `SkillStore.from_config()`. |
| `multi_recall` | `MultiRecall \| None` | no | Retrieval strategy wrapper. Internally hosts `RemoteRecall` and other strategies. Omit to run without remote recall. |
| `executor` | `SkillExecutor \| None` | no | Skill executor. Omit to build a gateway that cannot run skills (`execute()` will fail). |
| `llm` | `LLMClient \| None` | no | LLM client used by retrieval strategies that need reranking. |

> **Note:** For production use, call `SkillGateway.from_config()` or `init_skill_system()` instead of constructing directly.

## Methods

### `from_config(config=None)` — async classmethod

<!-- Original (han, latin): 异步工厂方法创建 SkillGateway。 内部自动创建所有依赖（Store, MultiRecall, RemoteRecall, Executor, LLM）。 Args: config: SkillConfig 配置，为 None 时自动从全局配置创建 Returns: 初始化好的 SkillGateway 实例 -->
Asynchronous factory that builds a fully-wired `SkillGateway`. All dependencies (`Store`, `MultiRecall`, `RemoteRecall`, `Executor`, `LLM`) are created internally, so the caller does not have to thread them through.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `config` | `SkillConfig \| None` | `None` | Runtime configuration. When `None`, the factory loads the global configuration automatically. |

**Returns:** `SkillGateway` — a ready-to-use gateway with store, retrieval, executor, and LLM client attached.

```python
gateway = await SkillGateway.from_config()
```

### `skill_store` — property

Read-only access to the underlying `SkillStore`. Exposed for inspection and for advanced callers that need to enumerate skills without going through `discover()`. Don't mutate through this handle.

### `discover(strategy, query="", k=10)` — async

Discover available skills by strategy.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `strategy` | `DiscoverStrategy \| str` | `DiscoverStrategy.LOCAL_ONLY` | `LOCAL_ONLY` returns every skill in the local file store. `MULTI_RECALL` runs the retrieval pipeline. |
| `query` | `str` | `""` | Search string. Required when `strategy == MULTI_RECALL`. |
| `k` | `int` | `10` | Maximum number of candidates to return under `MULTI_RECALL`. |

**Returns:** `list[SkillManifest]` — the matching skill manifests, or `[]` if any error occurs. Failures are logged but not raised.

### `search(query, k=10, cloud_only=false)` — async

Search for skills in the cloud Skill Market. Useful for discovering skills that aren't yet installed locally.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | — | Search string. |
| `k` | `int` | `10` | Maximum results. |
| `cloud_only` | `bool` | `False` | If `True`, skip local embedding search and only return Market hits. |

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
| `skill_name` | `str` | Name of the cloud skill to install. |

**Returns:** The installed `Skill` object on success, `None` on failure.

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

- As of the MS-DES-0003 translation pass, the extractor now reports per-docstring language classifications. This file's originals are all mixed Han/Latin, which the classifier catches automatically and which the translation pass resolves with inline comments. What used to be a manual translation step is now a structured, reviewable workflow — the `<!-- Original (han, latin): ... -->` blocks above each section give reviewers a direct audit trail.
- Parameter type annotations are sometimes quoted strings (`'SkillConfig'`), sometimes unquoted (`DiscoverStrategy | str`). The extractor preserves the original form, which means generated docs inherit that inconsistency. Minor cosmetic issue in the upstream code rather than the extractor.
- No top-level functions were found — the entire public surface of this module is the single class. The generator handled the empty-functions case cleanly.
