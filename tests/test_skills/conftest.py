"""test_skills 根 conftest - 所有 skill 测试共享的 fixtures

提供真实配置和常用 fixtures，不使用 mock。
所有路径都从 g_config 读取，确保测试在真实环境中运行。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path

from middleware.config import g_config
from core.skill.config import SkillConfig


@pytest.fixture(scope="session")
def test_config():
    """加载测试配置（全局单例）。

    直接加载 g_config 本身，而不是新建一个 ConfigManager 再把内部状态复制过去。
    v2 三层架构（system / user / runtime）没有 ``_config`` 属性，旧写法探测
    ``g_config._config`` 会走到 ``__getattr__`` 并直接抛 RuntimeError。
    """
    if not g_config.is_loaded():
        g_config.load()
    return g_config


@pytest.fixture(scope="session")
def skill_config(test_config) -> SkillConfig:
    """SkillConfig 实例（从全局配置创建）"""
    return SkillConfig.from_global_config()


@pytest.fixture(scope="session")
def skills_dir(skill_config) -> Path:
    """Skills 目录路径"""
    return Path(skill_config.skills_dir)


@pytest.fixture(scope="session")
def builtin_skills_dir(skill_config) -> Path:
    """Builtin skills 目录路径"""
    return Path(skill_config.builtin_skills_dir)


@pytest.fixture(scope="session")
def workspace_dir(skill_config) -> Path:
    """Workspace 目录路径"""
    return Path(skill_config.workspace_dir)


@pytest.fixture(scope="session")
def db_path(skill_config) -> Path:
    """数据库文件路径"""
    return skill_config.db_path


@pytest.fixture
def sample_skill_data():
    """示例 skill 数据（用于测试 Skill 模型）"""
    return {
        "name": "test_skill",
        "description": "A test skill for unit testing",
        "content": """---
name: test_skill
description: A test skill for unit testing
metadata:
  function_name: test_skill
  dependencies:
    - pytest
---

# Test Skill

This is a test skill content.
""",
        "dependencies": ["pytest"],
    }


@pytest_asyncio.fixture
async def db_manager(test_config):
    """数据库管理器实例"""
    from middleware.storage.core.engine import get_db_manager
    from middleware.storage.models import Base

    db_path = g_config.get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db_manager = get_db_manager()
    db_url = f"sqlite+aiosqlite:///{db_path}"

    await db_manager.init(db_url)

    # 创建表
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield db_manager

    await db_manager.dispose()


# ---------------------------------------------------------------------------
# External-service guards
#
# Several suites under tests/test_skills/ are integration tests against live
# services (the Skill Market's embedding endpoint, and whatever LLM provider
# the user has configured). When those are unconfigured or down, the correct
# outcome is a skip that names the real reason — not a failure that looks like
# a regression in this repo.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def embedding_service_status(test_config) -> str | None:
    """``None`` when the embedding service works, else a human-readable reason.

    Probes the real endpoint once per session. A configured-but-broken service
    is the case the old code missed: the fixtures only checked that
    ``embedding_base_url`` was non-empty, so a live-but-erroring Market
    produced ``None`` vectors and a bare ``assert vector is not None``.
    """
    import asyncio

    cfg = test_config.skills.retrieval
    if not cfg.embedding_base_url:
        return "embedding_base_url not configured"

    try:
        from middleware.llm.embedding_client import EmbeddingClient

        client = EmbeddingClient.from_config()
        vectors = asyncio.run(client.embed(["connectivity probe"]))
    except Exception as exc:  # noqa: BLE001 — any failure means "unusable"
        detail = str(exc).replace("\n", " ")[:300]
        return f"embedding service unusable ({type(exc).__name__}): {detail}"

    if not vectors or not vectors[0]:
        return "embedding service returned no vectors"
    return None


@pytest.fixture
def require_embedding_service(embedding_service_status):
    """Skip a test when the embedding service is unconfigured or broken."""
    if embedding_service_status:
        pytest.skip(embedding_service_status)


@pytest.fixture(scope="session")
def llm_profile_status(test_config) -> str | None:
    """``None`` when an active LLM profile exists, else the reason it doesn't."""
    try:
        llm_config = test_config.llm
        if llm_config.current_profile is None:
            return (
                "no active LLM profile configured "
                f"(active_profile={llm_config.active_profile!r}, "
                f"available={list(llm_config.profiles.keys())})"
            )
    except Exception as exc:  # noqa: BLE001
        return f"LLM config unreadable ({type(exc).__name__}): {exc}"
    return None


@pytest.fixture
def require_llm_profile(llm_profile_status):
    """Skip a test when no usable LLM profile is configured."""
    if llm_profile_status:
        pytest.skip(llm_profile_status)
