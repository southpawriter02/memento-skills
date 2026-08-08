"""Tool Dispatcher Gateway fixtures

Note: These tests need to be updated to use the new SkillProvider API
which no longer accepts store parameter.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Abandoned mid-migration, and the target API moved underneath it. Three "
    "separate problems, none of which a fixture rename fixes:\n"
    "  1. `real_dispatcher` below is a stub that returns None, with the "
    "author's own TODO pointing at init_skill_system(). All 17 tests in this "
    "package depend on it, so none of them has actually run in a long time.\n"
    "  2. The import of `builtin.tools.registry.configure` has never resolved "
    "on this branch - no `def configure` appears anywhere in builtin/ in the "
    "git history. Builtin tools are registered declaratively via "
    "BUILTIN_TOOL_REGISTRY and reached through `core.shared.tools_facade`.\n"
    "  3. 12 of the 17 tests exercise tools the dispatcher no longer has. "
    "ToolDispatcher.execute() now handles search_skill / execute_skill / "
    "download_skill / create_skill / ask_user; the tests call skill_list (x6), "
    "read_skill (x4) and skill_install (x2). Only execute_skill (x2) and "
    "search_skill (x1) still map. test_unknown_tool_raises expects ValueError, "
    "but unknown names now go to _handle_hallucinated_skill_call, which tries "
    "to resolve them as skill names first.\n"
    "Reviving this package is a rewrite against a changed tool surface, not a "
    "repair, and it needs a decision about the 12 tests whose tools are gone.",
    allow_module_level=True,
)


from pathlib import Path

import pytest

from builtin.tools.registry import configure as configure_builtin_tools
from core.memento_s.policies import PolicyManager
from core.memento_s.tool_dispatcher import ToolDispatcher


@pytest.fixture
def real_dispatcher() -> ToolDispatcher:
    """Fixture using the new init_skill_system API.

    TODO: Update to use init_skill_system() which returns the gateway
    """
    workspace = Path(__file__).resolve().parents[2]
    configure_builtin_tools(workspace)

    # TODO: Use new API
    # from core.skill import init_skill_system
    # from core.skill.config import SkillConfig
    # config = SkillConfig(...)
    # gateway = await init_skill_system(config)

    # For now, return None to skip tests
    return None
