"""覆盖面测试：把「全量」变成可执行的定义，而不是一句口头保证。

为什么需要它
------------
「全量分析」此前是一句**无法证伪**的说法。2026-09 的审计逐个文件核对后
发现它并不全：4,700 多个确实是 PDX 脚本的文件被当成资产跳过了
（gfx 的肖像设置与模型定义、music/sound 的音频定义、content_source 的
地图物件生成器、fonts 的字体注册表、DLC 下的全部脚本），
而 ``.font`` 与 ``.yml`` 两个后缀更是**声明了却永远匹配不上** ——
没有任何目录能让它们生效。

根因是判定标准错了：原先看「文件在哪个目录」，而正确的标准是
「它是不是 PDX 语法、mod 能不能改」。

本文件把那次审计的口径固化成断言：每个文件必须落在**四类之一**，
且每一类都有明确的判据。这样「全量」就是可执行的、可回归的，
而不是靠谁记得。

四类
----
1. **深度解析** —— ``config.is_scriptable`` 认可，进 PDX 解析器
2. **有据排除** —— ``config.EXCLUDED_SUBTREES``，逐条写明理由
3. **另有专用提取器** —— 不是 PDX 语法，交给对应模块（本地化、DLC 描述符…）
4. **与 mod 开发无关** —— 许可证、二进制、应用配置

任何落不进这四类的文件都会让测试失败。
"""

from __future__ import annotations

import pytest

from pdx import config
from pdx.scan import walk_files

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_needs_game = pytest.mark.skipif(
    not (config.GAME / "common").is_dir(), reason="游戏目录不可用"
)

#: 会被 PDX 解析器处理的扩展名。**这是判断「是否脚本」的唯一依据** ——
#: 不按目录名判断，因为同一个目录里可能既有脚本也有二进制。
PDX_SUFFIXES = frozenset(
    {".txt", ".asset", ".gui", ".font", ".settings", ".profile",
     ".shortcuts", ".layout", ".info"}
)

#: 许可证类文件名。实测 ``clausewitz/imgui_fonts/20/LICENSE.txt`` 就在一个
#: 与授权无关的目录里（字体目录），所以判据只能看**文件名**不能看目录。
_LICENSE_NAME_HINTS = ("license", "licence", "copying", "ofl", "notice", "eula")

#: 由**专用提取器**处理、因此不走 PDX 解析器的文件类型。
#: 每条都写明为什么不能用 PDX 解析器 —— 它们不是花括号语法。
DEDICATED_EXTRACTORS: dict[str, str] = {
    ".yml": "本地化：`key:版本 \"值\"` 行式格式，见 pdx.localization。"
            "实测交给 PDX 解析器会得到 0 键 0 错误，即静默解析失败",
    ".dlc": "DLC 描述符：`key=value` 平铺，见 analyze._analyse_dlc",
    ".json": "应用配置与 DLC 元数据，JSON 格式",
    ".csv": "分号分隔的表格（如 map_data/adjacencies.csv），非花括号语法",
    ".info": "散文式说明文档（如 _script_values.info），与 .md 同类，非脚本",
}

#: 与 mod 开发无关的目录。判据是「mod 改它没有意义或不被加载」。
IRRELEVANT_DIRS = frozenset({"licenses", "binaries", "launcher",
                             "platform_specific_game_data", "soundtrack"})

#: 内容根的根级文件（``checksum_manifest.txt`` / ``paths.settings`` 等），
#: 由 ``analyze._read_root_file`` 单独处理。
ROOT_FILES_HANDLED = True


def _classify(rel, suffix: str, name: str) -> str:
    """把一个文件归入四类之一。"""
    top = rel.parts[0] if len(rel.parts) > 1 else "<根>"
    if len(rel.parts) == 1:
        return "根级文件（_read_root_file 处理）"
    if any(h in name.lower() for h in _LICENSE_NAME_HINTS):
        return "许可证文本"
    if top in IRRELEVANT_DIRS:
        return "与 mod 开发无关"
    if suffix in DEDICATED_EXTRACTORS:
        return "专用提取器：" + suffix
    if config.is_excluded(rel.parts):
        return "有据排除"
    if config.is_scriptable(rel.parts, suffix):
        return "深度解析"
    return "❌ 未归类"


@_needs_game
def test_每个脚本类文件都落在四类之内() -> None:
    """核心断言：不存在「既没解析、也没被有据排除」的脚本文件。

    这条失败就意味着出现了覆盖面缺口 —— 而且会直接列出是哪些文件。
    """
    unclassified: list[str] = []
    for root, label in (
        (config.GAME, "game"),
        (config.JOMINI, "jomini"),
        (config.CLAUSEWITZ, "clausewitz"),
    ):
        if not root.is_dir():
            continue
        for f in walk_files(root):
            if f.suffix not in PDX_SUFFIXES:
                continue
            rel = f.path.relative_to(root)
            if _classify(rel, f.suffix, f.path.name) == "❌ 未归类":
                unclassified.append(f"{label}/{rel}")

    assert not unclassified, (
        f"有 {len(unclassified)} 个 PDX 脚本文件既没被解析、也没被有据排除：\n"
        + "\n".join("  " + p for p in unclassified[:25])
        + "\n\n请把它所在的目录加入 config.SCRIPTABLE_DIRS，"
        "或加入 config.EXCLUDED_SUBTREES 并写明理由。"
    )


@_needs_game
def test_声明的后缀都真的能生效() -> None:
    """``SCRIPTABLE_SUFFIXES`` 里的每一项都必须至少匹配到一个真实文件。

    这条抓的是「死配置」：``.font`` 与 ``.yml`` 曾在列表里躺了很久，
    但 ``fonts/`` 与 ``localization/`` 都不在 ``SCRIPTABLE_DIRS`` 中，
    没有任何目录能让它们生效 —— 写了等于没写。
    """
    matched: set[str] = set()
    for root in (config.GAME, config.JOMINI, config.CLAUSEWITZ):
        if not root.is_dir():
            continue
        for f in walk_files(root):
            if f.suffix in config.SCRIPTABLE_SUFFIXES:
                rel = f.path.relative_to(root)
                if config.is_scriptable(rel.parts, f.suffix):
                    matched.add(f.suffix)
    dead = sorted(set(config.SCRIPTABLE_SUFFIXES) - matched)
    assert not dead, (
        f"以下后缀在 SCRIPTABLE_SUFFIXES 里但匹配不到任何文件，属于死配置：{dead}\n"
        "要么给它一个所在的目录，要么从列表里删掉。"
    )


@_needs_game
def test_有据排除的子树确实存在且确实被排除() -> None:
    """排除项不能是空头支票 —— 目录要真实存在，且里面的文件真的没被解析。"""
    for prefix in config.EXCLUDED_SUBTREES:
        d = config.GAME.joinpath(*prefix)
        assert d.is_dir(), f"排除项 {prefix} 指向的目录不存在"
        files = list(walk_files(d))
        assert files, f"排除项 {prefix} 下没有任何文件"
        for f in files:
            rel = f.path.relative_to(config.GAME)
            assert not config.is_scriptable(rel.parts, f.suffix), (
                f"{rel} 声明被排除，实际仍会被解析"
            )


@_needs_game
def test_覆盖规模没有缩水() -> None:
    """把当前规模钉住。数字掉下来就说明有目录被移出了范围。

    这个下限是 2026-09 覆盖面审计后的实测值，留了一点余量 ——
    游戏升级时文件数只会增不会减，所以下限是安全的。
    """
    parsed = 0
    for root in (config.GAME, config.JOMINI, config.CLAUSEWITZ):
        if not root.is_dir():
            continue
        for f in walk_files(root):
            rel = f.path.relative_to(root)
            if config.is_scriptable(rel.parts, f.suffix):
                parsed += 1
    assert parsed >= 6_000, (
        f"只有 {parsed} 个文件进入深度解析，低于 6,000 的下限 —— "
        "很可能有目录被移出了 SCRIPTABLE_DIRS"
    )


@_needs_game
def test_本地化由专用提取器覆盖() -> None:
    """本地化的 2,176 个文件不走 PDX 解析器，但必须有别的路走。

    这条防的是「范围看起来扩大了、实际那个格式还是没人管」——
    ``.yml`` 曾经就处在这个状态：挂在后缀列表里，却没有任何提取器。
    """
    from pdx.localization import extract_localization

    r = extract_localization(config.GAME)
    assert r.files > 1_800, f"本地化只覆盖了 {r.files} 个文件"
    assert r.unique_keys > 100_000, f"只提取到 {r.unique_keys} 个键"
