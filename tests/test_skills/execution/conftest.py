"""SkillExecutor 测试的共享前置条件。

``SkillExecutor.__init__`` 会构造 LLM 客户端，未配置 profile 时直接抛
``ValueError: No active LLM profile found``。这些是真实环境集成测试，
未配置 LLM 时应当跳过而不是报错。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _skip_without_llm_profile(llm_profile_status):
    if llm_profile_status:
        pytest.skip(llm_profile_status)
