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
)

#: ① 需要**深度解析**的文件扩展名
SCRIPTABLE_SUFFIXES: tuple[str, ...] = (
    ".txt",   # PDX 脚本
    ".gui",   # 界面布局（同样是花括号语法）
    ".yml",   # 本地化
    ".font",  # 字体注册表
    ".settings",
    ".profile",
)

#: ② 只做清单统计的目录（记录路径、大小、格式约定）
ASSET_DIRS: tuple[str, ...] = (
    "gfx",
    "sound",
    "music",
    "soundtrack",
    "fonts",
    "localization",
    "content_source",
    "licenses",
    "dlc",
)

#: ③ 完全跳过的目录（二进制本体与启动器，与 mod 开发无关）
IGNORED_DIRS: tuple[str, ...] = (
    "binaries",
    "launcher",
    "platform_specific_game_data",
)


def is_scriptable(rel_parts: tuple[str, ...], suffix: str) -> bool:
    """判断一个相对路径是否需要深度解析。"""
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
