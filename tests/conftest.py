"""Pytest 配置文件

注册自定义标记和全局 fixtures。
"""

import pytest


def pytest_configure(config):
    """配置 pytest，注册自定义标记"""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (require network)"
    )
    config.addinivalue_line(
        "markers", "stress: marks tests as stress/load tests (slow)"
    )


#: 需要重定向到临时沙箱的可写路径。``data_dir`` 放在最前面，因为其余路径
#: 默认都以它为父目录。
_SANDBOXED_PATH_ATTRS = (
    "data_dir",
    "workspace_dir",
    "skills_dir",
    "db_dir",
    "logs_dir",
    "venv_dir",
    "context_dir",
)


@pytest.fixture(scope="session", autouse=True)
def _load_global_config(tmp_path_factory):
    """加载 g_config，并把所有可写路径重定向到临时沙箱。

    两件事，一件是必需的，一件是安全防线：

    1. **加载。** 生产链路由 ``bootstrap()`` 调用 ``g_config.load()``；测试不走
       bootstrap，因此任何触及配置的测试都会撞上 ``RuntimeError: 配置尚未加载``。

    2. **隔离。** 加载后 ``paths.*`` 指向用户真实的 ``~/memento_s``。套件会
       真实写入：session/conversation/skill 行会落进真实数据库，market 安装
       测试会把 fixture 技能装进真实 skills 目录，向量测试会散落
       ``test_vectors_*.db``。这既污染用户数据，也让套件不幂等——累积的行会让
       ``assert count <= 1`` 这类断言在第二次运行时失败。

    这里保留 "真实对象、不用 mock" 的设计（真实 SQLite、真实文件），只是把落盘
    位置换成 pytest 的临时目录。
    """
    from _pytest.monkeypatch import MonkeyPatch

    from middleware.config import g_config
    from utils.path_manager import PathManager

    sandbox = tmp_path_factory.mktemp("memento_s_home")
    mp = MonkeyPatch()

    # ``ConfigManager.load()`` force-overwrites ``paths`` from PathManager every
    # time (config_manager.py:289-297), so patching these classmethods captures
    # *every* manager instance — including the fresh ``ConfigManager()`` objects
    # several tests build for themselves. Patching only ``g_config.paths`` was
    # not enough: those tests reloaded the real paths straight off disk.
    #
    # ``get_config_file()`` is deliberately NOT patched — the user's real
    # config.json keeps being read, so "real config, no mocks" still holds. Only
    # the writable data directories move.
    for accessor in _SANDBOXED_PATH_ATTRS:
        target = sandbox / accessor.removesuffix("_dir")
        target.mkdir(parents=True, exist_ok=True)
        mp.setattr(
            PathManager,
            f"get_{accessor}",
            classmethod(lambda cls, packaged=None, _t=target: _t),
            raising=False,
        )

    # Reload so an already-loaded singleton picks up the sandboxed paths.
    g_config.load()

    yield g_config

    mp.undo()
