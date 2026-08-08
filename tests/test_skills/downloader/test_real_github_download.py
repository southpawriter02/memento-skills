"""Downloader real GitHub integration test."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.skill.config import SkillConfig
from core.skill.downloader.factory import create_default_download_manager


@pytest.mark.integration
def test_download_real_skill_from_github():
    """Real GitHub download for a published skill."""
    from middleware.config import g_config

    # 确保全局配置已加载
    if not g_config.is_loaded():
        g_config.load()

    url = "https://github.com/ruvnet/ruflo/tree/main/.agents/skills/agentdb-learning"
    config = SkillConfig.from_global_config()
    manager = create_default_download_manager()

    result = manager.download(url, config.skills_dir, "feishu-doc")

    assert result is not None
    assert result.exists()
    assert result.is_dir()
    assert (result / "SKILL.md").exists()
