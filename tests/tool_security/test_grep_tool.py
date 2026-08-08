"""grep 工具的路径边界测试。

历史说明：这个测试原先调用 ``grep_tool.__wrapped__(..., allow_roots=[...])``，
断言 grep 自己会拒绝越界路径。现在两点都变了：

* ``grep_tool`` 不再被装饰，因此没有 ``__wrapped__``；
* ``allow_roots`` 参数已从 grep 的签名中移除，其 docstring 明确写着传入的
  ``dir_path`` 是 "absolute path, pre-validated"。

边界校验被上移到了 ``core/skill/execution/tool_bridge`` —— ``ToolContext``
负责解析路径并在越界时抛 ``PermissionError``，``bridge.py`` 在调用工具前
先过这一关。所以这里保留同样的安全断言，只是打在现在真正负责校验的那一层，
另外再验证 grep 本身在拿到已校验路径时能正常工作。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builtin.tools.grep import grep_tool
from core.skill.execution.tool_bridge.context import ToolContext


def _context(workspace: Path) -> ToolContext:
    return ToolContext(
        workspace_dir=workspace,
        root_dir=workspace,
        allow_roots=(workspace,),
    )


async def test_grep_tool_reads_prevalidated_path(tmp_path: Path) -> None:
    """校验通过的路径下，grep 能正常命中内容。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "data.txt").write_text("hello world", encoding="utf-8")

    resolved = _context(workspace).resolve_path(str(workspace))

    result = await grep_tool(pattern="hello", dir_path=str(resolved))

    assert "hello" in result


def test_path_inside_allow_roots_resolves(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "data.txt"
    target.write_text("hello world", encoding="utf-8")

    assert _context(workspace).resolve_path(str(target)) == target.resolve()


def test_path_outside_allow_roots_is_rejected(tmp_path: Path) -> None:
    """越界路径必须被拒绝——这是本文件存在的意义。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(PermissionError):
        _context(workspace).resolve_path(str(outside / "secret.txt"))


def test_traversal_escape_is_rejected(tmp_path: Path) -> None:
    """``..`` 逃逸同样要被拒绝，而不是解析后放行。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "outside").mkdir()

    with pytest.raises(PermissionError):
        _context(workspace).resolve_path(str(workspace / ".." / "outside"))
