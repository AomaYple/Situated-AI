"""安装目录卫生：非游戏文件会悄悄改变「安装树」的数字。

为什么单独一条
--------------
`v3 verify` 里有一族**安装树**断言（文件数、字节数、各目录规模）。它们数的是
「那个文件夹里有什么」——**包括**任何被别的程序丢进去的东西。实测踩过：
用图片查看器翻了一次 `game/gfx/cursors`，多出 `.XnViewSort` 与一个 `.dmp`，
于是四条断言集体报红（`27,723 → 27,725`、体积 `+151,932 B`），
而排查方向很容易跑偏成「Paradox 更新了？」。

这条测试把「先看有没有垃圾文件」变成自动的一步：命中已知的非游戏文件模式就
直接点名，并给出处置建议（移出游戏目录，别删游戏本体）。
"""

from __future__ import annotations

import pytest

from pdx import config
from pdx.scan import walk_files

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_needs_game = pytest.mark.skipif(not config.GAME.is_dir(), reason="游戏目录不可用")

#: 已知的**非游戏**文件模式：看图工具 / 系统 / 崩溃转储留下的东西。
#: 每一条都写清来源，免得以后有人以为是游戏文件。
DEBRIS: dict[str, str] = {
    ".xnviewsort": "XnView 的排序缓存（翻一次图片目录就会生成）",
    ".dmp": "转储文件（看图工具的缩略图缓存或崩溃转储）",
    "thumbs.db": "Windows 资源管理器的缩略图缓存",
    "desktop.ini": "Windows 的文件夹显示配置",
    ".ds_store": "macOS 的 Finder 元数据",
}


def _debris() -> list[tuple[str, str]]:
    if not config.GAME.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for entry in walk_files(config.GAME):
        name = entry.path.name.lower()
        for pattern, why in DEBRIS.items():
            if name == pattern or name.endswith(pattern):
                out.append((str(entry.path.relative_to(config.GAME)), why))
                break
    return out


@_needs_game
def test_游戏目录里没有非游戏垃圾文件() -> None:
    """游戏目录里混进非游戏文件时，安装树断言会集体报红 —— 这里先把它点出来。"""
    found = _debris()
    assert not found, (
        f"游戏目录里有 {len(found)} 个非游戏文件，它们会让『安装树』那族断言全部报红：\n  "
        + "\n  ".join(f"{rel} —— {why}" for rel, why in found[:10])
        + "\n处置：把它们**移出**游戏目录（不要删游戏本体），再跑 `v3 verify`。"
    )


def test_垃圾文件模式表本身有据可依() -> None:
    """模式表不能是空壳：每条都要有来源说明，且模式是小写、形状可信。"""
    assert DEBRIS
    for pattern, why in DEBRIS.items():
        assert pattern == pattern.lower()
        assert pattern.startswith(".") or "." in pattern, f"{pattern} 看着不像文件名后缀或文件名"
        assert len(why) > 8, f"{pattern} 的来源说明太短"
