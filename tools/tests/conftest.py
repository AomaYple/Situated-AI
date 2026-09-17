"""全局 fixture。

临时目录
--------
直接用 pytest 的 ``tmp_path``（会话级 basetemp 由 pytest 自行管理）。
不再自己用 ``tempfile``/``uuid`` 造目录 —— 那是早先沙箱限制下的妥协，
现已无必要。

游戏可用性
----------
依赖真实游戏安装的测试统一打 ``integration`` 标记。游戏不在本机时，
:func:`pytest_collection_modifyitems` 会**自动跳过**它们，而不是让整套
测试报错 —— 这样在别的机器上仍能跑单元测试与属性测试。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pdx import analyze, config
from pdx.scan import walk_files

if TYPE_CHECKING:
    from pathlib import Path

#: 游戏内容层是否可用（mod 相关文件都在 game/ 下）
GAME_OK = (config.GAME / "common").is_dir()


def pytest_collection_modifyitems(config, items):
    """游戏不在本机时，自动跳过所有 integration 测试。

    参数名必须是 ``config`` —— pluggy 按 hookspec 的形参名注入，
    改成 ``config_`` 会直接抛 ``PluginValidationError``。
    """
    if GAME_OK:
        return
    skip = pytest.mark.skip(reason=f"游戏目录不可用：{config.GAME}")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# ── 真实语料 ────────────────────────────────────────────────
@pytest.fixture(scope="session")
def corpus_files() -> list[Path]:
    """游戏本体中所有需要深度解析的文件（约 4,400 个）。

    这是差分测试与模糊测试的**真实输入来源** —— 用真实语料而不是
    自造样本，才能覆盖官方脚本里那些古怪写法。
    """
    if not GAME_OK:
        return []
    out: list[Path] = []
    for root in (config.GAME, config.JOMINI, config.CLAUSEWITZ):
        if not root.is_dir():
            continue
        for f in walk_files(root):
            try:
                rel = f.path.relative_to(root)
            except ValueError:
                continue
            if config.is_scriptable(rel.parts, f.suffix):
                out.append(f.path)
    return sorted(out)


@pytest.fixture(scope="session")
def corpus_texts(corpus_files: list[Path]) -> list[tuple[str, str]]:
    """语料文本，``(路径, 内容)``。只读一次，session 内共享。"""
    out: list[tuple[str, str]] = []
    for p in corpus_files:
        try:
            out.append((str(p), p.read_text(encoding="utf-8-sig", errors="replace")))
        except OSError:
            continue
    return out


# ── 全量分析结果（整轮只跑一次）────────────────────────────
@pytest.fixture(scope="session")
def ga():
    """游戏本体分析结果。"""
    return analyze.game_analysis()


@pytest.fixture(scope="session")
def ma():
    """mod 分析结果。"""
    return analyze.mods_analysis()


@pytest.fixture(scope="session")
def ca(ga, ma):
    """交叉分析结果。"""
    return analyze.cross_analysis(ma)
