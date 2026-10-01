"""安装目录卫生：安装树里多出文件会悄悄改变「game 全树」的数字。

为什么单独一条
-------------
`v3 verify` 里有一族**安装树**断言（文件数、字节数、各目录规模）。它们数的是
「那个文件夹里有什么」——**包括**任何被别的程序丢进去的东西。实测踩过：
多出 `.XnViewSort` 与一个 `.dmp` 之后，五条断言集体报红（`27,728 → 27,730`、
体积 `+151,932 B`），而排查方向很容易跑偏成「Paradox 更新了？」。

⚠️ **2026-09-24 更正（这条测试的第一次结论是错的）**
--------------------------------------------------
当时把这两个文件判成「看图工具留下的垃圾，移出即可」。**错了**：Steam 的校验
日志（`logs\\content_log.txt`）从 09-19 起**九次**把它们报成
``Validation: missing file``，09-24 的一次 depot 更新又把它们**逐字写回**
（``2 updated, 0 moved, 0 deleted files``），落点与大小和删除前一模一样
—— 也就是说**它们属于原版 depot**，删掉只会被补回来。

所以判据从「有没有异物」改成两件事：
1. **原版自带的这两个文件在不在、大小对不对**（不在 ⇒ 安装不完整，报出来）；
2. **有没有别的新异物**（除了这两个，命中已知垃圾模式就点名）。

两件都是**信号**：第 1 件对应「Steam 又补回来了 ⇒ 该重新冻结安装树基线」，
第 2 件对应「有外部程序在写游戏目录」。
"""

from __future__ import annotations

import pytest

from pdx import config
from pdx.scan import walk_files

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_needs_game = pytest.mark.skipif(not config.GAME.is_dir(), reason="游戏目录不可用")

#: 已知的**外部程序**文件模式：看图工具 / 系统 / 崩溃转储留下的东西。
#: 每一条都写清来源，免得以后有人以为是游戏文件。
#: ⚠️ `.dmp` **不在**这里 —— 原版 depot 里那一个也是 `.dmp`，见 :data:`VANILLA_ODDITIES`；
#: 把它列进垃圾模式会让「原版自带的转储」永远报红（这是更正前那版的错）。
DEBRIS: dict[str, str] = {
    ".xnviewsort": "XnView 的排序缓存（翻一次图片目录就会生成）",
    "thumbs.db": "Windows 资源管理器的缩略图缓存",
    "desktop.ini": "Windows 的文件夹显示配置",
    ".ds_store": "macOS 的 Finder 元数据",
}

#: **原版 depot 里就有、但看着像垃圾**的文件：相对 `game\\` 的路径 → 字节数。
#: 它们必须**在**：不在说明 Steam 还没把安装补全，安装树的数字会比基线小。
#: 证据（2026-09-24）：`content_log.txt` 里九次 `Validation: missing file`，
#: 以及 09-24 20:24:29 那次 `2 updated, 0 moved, 0 deleted files` 的写回。
VANILLA_ODDITIES: dict[str, int] = {
    "gfx\\cursors\\.XnViewSort": 2854,
    "gfx\\portraits\\accessory_variations\\fee87a16-c1d5-44f8-88b7-992d92b82be8.dmp": 149078,
}


def _debris() -> list[tuple[str, str]]:
    """除 :data:`VANILLA_ODDITIES` 之外，还命中已知外部程序模式的文件。"""
    if not config.GAME.is_dir():
        return []
    known = {name.lower() for name in VANILLA_ODDITIES}
    out: list[tuple[str, str]] = []
    for entry in walk_files(config.GAME):
        rel = str(entry.path.relative_to(config.GAME))
        if rel.lower() in known:
            continue
        name = entry.path.name.lower()
        for pattern, why in DEBRIS.items():
            if name == pattern or name.endswith(pattern):
                out.append((rel, why))
                break
    return out


@_needs_game
def test_原版自带的那两个异样文件都在且大小一致() -> None:
    """它们属于原版 depot —— 不在就说明安装不完整，安装树基线会整体偏小。"""
    missing: list[str] = []
    wrong: list[str] = []
    for rel, size in VANILLA_ODDITIES.items():
        path = config.GAME / rel
        if not path.is_file():
            missing.append(rel)
        elif path.stat().st_size != size:
            wrong.append(f"{rel}：期望 {size:,} B，实得 {path.stat().st_size:,} B")
    assert not missing, (
        "原版自带的异样文件不见了（证据见本模块注释）：\n  "
        + "\n  ".join(missing)
        + "\n处置：先让 Steam 校验/更新把安装补全，再跑 `v3 tables --write` + `v3 verify --fix` 重冻基线。"
    )
    assert not wrong, "原版自带的异样文件大小对不上：\n  " + "\n  ".join(wrong)


@_needs_game
def test_游戏目录里没有别家的垃圾文件() -> None:
    """除原版那两个之外，再混进外部程序的文件时，安装树断言会集体报红。"""
    found = _debris()
    assert not found, (
        f"游戏目录里有 {len(found)} 个外部程序文件，它们会让『安装树』那族断言全部报红：\n  "
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
