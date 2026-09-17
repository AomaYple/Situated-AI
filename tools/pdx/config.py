"""路径与常量。

所有硬编码路径集中在这里，方便换机器时一处修改。
环境变量可覆盖默认值：

* ``V3_ROOT``    游戏安装根目录
* ``V3_USERDIR`` 用户数据目录
* ``V3_WORKSHOP`` Workshop 内容目录
"""

from __future__ import annotations

import os
from pathlib import Path

#: 游戏安装根目录
ROOT = Path(
    os.environ.get(
        "V3_ROOT", r"C:\Program Files (x86)\Steam\steamapps\common\Victoria 3"
    )
)

#: 游戏内容层（mod 覆盖的目标）
GAME = ROOT / "game"

#: 引擎共享层
JOMINI = ROOT / "jomini"
CLAUSEWITZ = ROOT / "clausewitz"

#: 用户数据目录
USERDIR = Path(
    os.environ.get(
        "V3_USERDIR",
        r"C:\Users\28905\Documents\Paradox Interactive\Victoria 3",
    )
)

#: 本地 mod 目录
LOCAL_MODS = USERDIR / "mod"

#: Steam Workshop 内容目录
WORKSHOP = Path(
    os.environ.get(
        "V3_WORKSHOP",
        r"C:\Program Files (x86)\Steam\steamapps\workshop\content\529340",
    )
)

#: 本仓库根目录（tools/ 的上一级）
REPO = Path(__file__).resolve().parents[2]

#: 文档与资料目录
DOCS = REPO / "docs" / "victoria3-modding"
RESEARCH = REPO / "research"

#: 中间产物目录（已 gitignore）
OUT = REPO / "tools" / "out"

#: 分析产物的**分仓**目录 —— 游戏本体与 mod 分开存放，互不混杂
OUT_GAME = OUT / "game"
OUT_MODS = OUT / "mods"
OUT_CROSS = OUT / "cross"

#: 人可读报告目录
REPORTS = REPO / "tools" / "reports"

#: Steam App ID
APP_ID = 529340

#: 参与联机校验和的目录（来自 game/checksum_manifest.txt）
CHECKSUMMED = ("common", "events", "map_data", "gui", "localization")

#: PDX 脚本文件的扩展名
PDX_SUFFIXES = (".txt",)


# ── mod 相关性范围 ──────────────────────────────────────────
# 目标不是「读遍游戏的全部文件」，而是「提取所有与 mod 开发有关的信息」。
# 因此把文件分成三类，只对第一类做深度解析。
#
#   ① 可脚本化内容 —— mod 能定义或覆盖的，**深度解析**
#   ② 资产与引擎 —— 只做清单统计，记录路径与格式约定
#   ③ 无关文件 —— 完全跳过（二进制本体、启动器、许可证）
#
# ⚠️ 这份范围曾经是错的。2026-09 的一次覆盖面审计逐个文件核对后，
#    发现「② 类」里混着大量**确实是 PDX 脚本**的文件，它们被当成资产
#    跳过了：gfx 下的肖像设置与地图物件（213 个 .txt）、gfx 的模型定义
#    （1,621 个 .asset）、music/sound 的音乐音效定义（15 个）、
#    content_source 的地图物件生成器（31 个）、fonts 的字体注册表。
#    更糟的是 ``.font`` 与 ``.yml`` 两个后缀**声明了却永远匹配不上** ——
#    ``fonts/`` 与 ``localization/`` 不在 SCRIPTABLE_DIRS 里，
#    没有任何目录能让这两个后缀生效，等于写了个死配置。
#
#    判定依据不是「它在哪个目录」，而是**这个文件是不是 PDX 脚本语法、
#    mod 能不能改**。下面每一条都经过实际解析验证（0 语法错误）。

#: ① 需要**深度解析**的目录（相对各内容根）
SCRIPTABLE_DIRS: tuple[str, ...] = (
    "common",        # 数据定义主体，136 个子目录
    "events",        # 事件脚本
    "gui",           # 界面布局
    "map_data",      # 地图脚本部分（州区域、邻接等）
    "interface",     # 消息类型
    "notifications", # 通知定义
    "data_binding",  # GUI 数据绑定宏
    "input_profile", # 输入配置
    "dlc_metadata",  # DLC 元数据定义
    "tools",         # 官方开发工具配置（脚本化测试框架等）
    # ── 覆盖面审计后补入（都是 PDX 脚本，此前被误当资产跳过）──
    "gfx",           # 肖像设置 / 地图物件 / 城市数据 / 模型与实体定义
    "music",         # 音乐轨道与播放器分类
    "sound",         # 环境音、音频参数组与上限
    "content_source",# 地图物件生成器（.txt 与 gfx 下的生成结果配套）
    "fonts",         # 字体注册表 fonts.font
)

#: ① 需要**深度解析**的文件扩展名
SCRIPTABLE_SUFFIXES: tuple[str, ...] = (
    ".txt",        # PDX 脚本
    ".gui",        # 界面布局（同样是花括号语法）
    ".asset",      # 模型 / 实体 / 动画定义。**同为 PDX 语法**：
                   # 实测 construction_entities.asset 解析出 7 个顶层键、
                   # 嵌套 4 层、0 语法错误，连 @[表达式] 都能正确处理
    ".font",       # 字体注册表（fonts/fonts.font，19 个顶层键）
    ".shortcuts",  # 快捷键绑定
    ".layout",     # 界面布局变体
    ".settings",
    ".profile",
)
# 注：``.yml``（本地化）**刻意不在这里**。本地化不是花括号语法，而是
# ``key:版本号 "值"`` 的行式格式 —— 实测把 languages.yml 交给 PDX 解析器
# 会得到 0 个顶层键、0 个错误，也就是**静默地什么都没解析出来**。
# 本地化由 :mod:`pdx.localization` 独立提取，见那里。

#: ② 只做清单统计的目录（记录路径、大小、格式约定）
ASSET_DIRS: tuple[str, ...] = (
    "soundtrack",
    "licenses",
    "dlc",
)

#: ③ 完全跳过的目录（二进制本体与启动器，与 mod 开发无关）
IGNORED_DIRS: tuple[str, ...] = (
    "binaries",
    "launcher",
    "platform_specific_game_data",
)

#: **有据排除**的子树：不是遗漏，是有明确理由不解析。
#:
#: 与 ``ASSET_DIRS`` 的区别在于：这些文件**确实是 PDX 语法**、也确实能被
#: 解析，只是经判断不值得纳入 —— 因此必须逐条写明理由，并且仍然出现在
#: 文件清单里（不做隐藏）。这样「为什么没分析它」是可审计的，
#: 而不是像早先那样在代码里默默漏掉。
EXCLUDED_SUBTREES: tuple[tuple[str, ...], ...] = (
    # Paradox 自家工具从 content_source/ 生成的地图物件摆放数据。
    # 61 个文件占 **85.9 MB**（单个最大 24.45 MB），是机器产出而非人工脚本；
    # 纳入解析会让全量分析多花约 10 秒、产物多出数 MB，
    # 而 mod 作者不会手写这些文件 —— 要改就改 content_source/ 下的生成器
    # （那个目录**已经**在解析范围内）。
    ("gfx", "map", "map_object_data", "generated"),
)


def is_excluded(rel_parts: tuple[str, ...]) -> bool:
    """是否落在 :data:`EXCLUDED_SUBTREES` 列出的子树里。"""
    for prefix in EXCLUDED_SUBTREES:
        if len(rel_parts) >= len(prefix) and rel_parts[: len(prefix)] == prefix:
            return True
    return False


def is_scriptable(rel_parts: tuple[str, ...], suffix: str) -> bool:
    """判断一个相对路径是否需要深度解析。

    判定完全基于「目录 + 后缀」两条，不看内容 —— 因此它同时是
    :func:`pdx.scan.walk_files` 的过滤器与文档里「分析范围」的口径来源，
    两处不会分歧。
    """
    if not rel_parts:
        return False
    top = rel_parts[0]
    if top in IGNORED_DIRS:
        return False
    # 根级配置文件（checksum_manifest 等）单独处理
    if len(rel_parts) == 1:
        return False
    if top not in SCRIPTABLE_DIRS:
        return False
    if is_excluded(rel_parts):
        return False
    return suffix in SCRIPTABLE_SUFFIXES


def ensure_dirs() -> None:
    """确保全部输出目录存在。"""
    for d in (OUT, OUT_GAME, OUT_MODS, OUT_CROSS, REPORTS):
        d.mkdir(parents=True, exist_ok=True)


def game_version() -> dict[str, str]:
    """读取版本指纹。找不到的文件返回空串，不抛异常。"""
    files = {
        "caligula_branch": ROOT / "caligula_branch.txt",
        "caligula_rev": ROOT / "caligula_rev.txt",
        "clausewitz_branch": ROOT / "clausewitz_branch.txt",
        "clausewitz_rev": ROOT / "clausewitz_rev.txt",
    }
    out: dict[str, str] = {}
    for name, path in files.items():
        try:
            out[name] = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            out[name] = ""
    return out
