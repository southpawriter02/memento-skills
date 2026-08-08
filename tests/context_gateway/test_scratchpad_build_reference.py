from __future__ import annotations

from core.context.scratchpad import Scratchpad


def test_build_reference_no_sections(scratchpad: Scratchpad):
    """No archived sections -> empty reference (compact never triggered)."""
    ref = scratchpad.build_reference()
    assert ref == ""


def test_build_reference_after_archive(scratchpad: Scratchpad):
    """After write (archive), returns reference with path and instructions."""
    scratchpad.write("Archived", "x" * 500)

    ref = scratchpad.build_reference()
    assert "## Scratchpad (archived context)" in ref
    # scratchpad.py:337 起输出 $SCRATCHPAD 占位符，由调用方替换为真实路径，
    # 避免把绝对路径直接写进 prompt。
    assert "$SCRATCHPAD" in ref
    assert str(scratchpad.path) not in ref
    assert "filesystem" in ref
    assert "search_grep" in ref
