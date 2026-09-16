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
