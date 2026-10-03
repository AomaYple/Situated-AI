"""路径与常量。

所有硬编码路径集中在这里，方便换机器时一处修改。**默认值里不含任何机器专属路径**：
用户名一律由 ``Path.home()`` 推出来，Steam 只写各平台的**规范位置**（不写盘符、不写用户名）。

三个路径走**同一条解析链**（:func:`resolve`）：

1. **环境变量优先** —— ``V3_ROOT`` / ``V3_USERDIR`` / ``V3_WORKSHOP`` 设了就赢，
   且**不判存在**（CI 与伪造环境要能把它们指到一个还没生成的目录，见
   ``tests/test_conftest.py`` 的 ``Z:/nope`` 用法）；
2. **平台候选清单逐条判存在** —— Windows / Linux / macOS 各一份
   （:func:`steam_roots` / :func:`game_candidates` / :func:`userdir_candidates`），先到先得；
3. **确定的回落值** —— 一条候选都不存在时取该平台清单的第一条。**不抛异常**：
   ``pdx.config`` 会在没装游戏的机器上被 import，import 期炸掉会让整套单测收集失败。

Workshop 目录由**找到 ROOT 的那个 Steam 根**推导（:func:`workshop_for`），
不再写第二份平台路径；App ID 也只有一个来源（:data:`APP_ID`）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Steam App ID（Victoria 3）—— Workshop 路径里的**唯一**来源
APP_ID = 529340

#: 游戏在 Steam 库里的固定相对位置：``<Steam 根>/steamapps/common/<这个名字>``
GAME_DIR_NAME = "Victoria 3"

#: Paradox 的用户数据目录名：``<Documents / XDG 数据目录>/Paradox Interactive/<游戏名>``
PUBLISHER_DIR_NAME = "Paradox Interactive"


# ── 默认路径的解析：环境变量优先 → 平台候选逐条判存在 → 确定的回落值 ──────
def _first_existing(candidates: Sequence[Path]) -> Path | None:
    """候选清单里**第一个存在**的路径；一条都不存在 ⇒ ``None``。"""
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:  # pragma: no cover - 畸形路径（超长等）只在某些平台上会抛
            continue
    return None


def resolve(env_value: str | None, candidates: Sequence[Path], fallback: Path) -> Path:
    """上面那条解析链的**唯一实现**（三个路径同一条）。

    ``env_value`` 只判"设没设"、**不判存在** —— 于是 CI 里能把三个变量指到
    ``Z:/nope`` 这种不存在的路径上，而 ``import pdx.config`` 照常成功。
    """
    if env_value:
        return Path(env_value)
    found = _first_existing(candidates)
    if found is None:
        return fallback
    return found


def steam_roots(home: Path | None = None, platform: str | None = None) -> tuple[Path, ...]:
    """Steam 安装根的**平台候选清单**（只判存在 —— 不读注册表、不扫盘）。

    * Windows：``Program Files (x86)`` / ``Program Files`` 下的 ``Steam``，
      以及二级盘符上的 ``<盘>:\\SteamLibrary``（Steam 默认装在 C:，但把库放 D:/E: 是标准做法）；
    * macOS：``~/Library/Application Support/Steam``；
    * Linux：官方包的 ``~/.steam/steam``、发行版包的 ``~/.local/share/Steam``、
      Flatpak 的 ``~/.var/app/com.valvesoftware.Steam/data/Steam``。

    ``home`` / ``platform`` 可注入 ⇒ 用例能拿假 home 逐平台核对清单，不必真装游戏。
    """
    if home is None:
        home = Path.home()
    if platform is None:
        platform = sys.platform
    if platform.startswith("win"):
        windows = (
            "C:/Program Files (x86)/Steam",
            "C:/Program Files/Steam",
            "C:/SteamLibrary",
            "D:/SteamLibrary",
            "E:/SteamLibrary",
        )
        return tuple(Path(item) for item in windows)
    if platform == "darwin":
        return (home / "Library" / "Application Support" / "Steam",)
    return (
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
    )


def game_candidates(home: Path | None = None, platform: str | None = None) -> tuple[Path, ...]:
    """游戏安装根目录候选 = 每个 Steam 根下面的 ``steamapps/common/<游戏>``。"""
    return tuple(
        steam / "steamapps" / "common" / GAME_DIR_NAME
        for steam in steam_roots(home=home, platform=platform)
    )


def default_game_root(home: Path | None = None, platform: str | None = None) -> Path:
    """该平台上**确定的**游戏安装根（候选清单第一条，**不判存在**）—— 一条候选都没有时用它。"""
    return game_candidates(home=home, platform=platform)[0]


def steam_root_of(game_root: Path) -> Path | None:
    """从 ``<Steam 根>/steamapps/common/<游戏>`` **反推** ``<Steam 根>``。

    形状不符（路径里没有 ``steamapps`` 这一段，例如环境变量指到了一个自定义目录）
    ⇒ ``None``：调用方据此退回该平台的规范 Steam 根，而不是猜。
    """
    parts = game_root.parts
    for index in range(len(parts) - 1, 0, -1):
        if parts[index] == "steamapps":
            return Path(*parts[:index])
    return None


def workshop_dir(steam_root: Path) -> Path:
    """``<Steam 根>/steamapps/workshop/content/<App ID>``（App ID 只从 :data:`APP_ID` 来）。"""
    return steam_root / "steamapps" / "workshop" / "content" / str(APP_ID)


def workshop_for(game_root: Path) -> Path:
    """由**游戏安装根**推导 Workshop 目录 —— 这就是"不再写第二份平台路径"的落点。"""
    steam = steam_root_of(game_root)
    if steam is None:
        steam = steam_roots()[0]
    return workshop_dir(steam)


def userdir_candidates(home: Path | None = None, platform: str | None = None) -> tuple[Path, ...]:
    """用户数据目录候选 —— **全部由 ``Path.home()`` 推出来**，不写任何用户名。

    * Windows / macOS：``~/Documents/Paradox Interactive/Victoria 3``；
    * Linux：Paradox 走 XDG 数据目录 ``~/.local/share/...``；旧版也在 ``~/Documents`` 下，
      两条都列上（先到先得）。
    """
    if home is None:
        home = Path.home()
    if platform is None:
        platform = sys.platform
    paradox = Path(PUBLISHER_DIR_NAME) / GAME_DIR_NAME
    if platform.startswith("win") or platform == "darwin":
        return (home / "Documents" / paradox,)
    return (home / ".local" / "share" / paradox, home / "Documents" / paradox)


def default_userdir(home: Path | None = None, platform: str | None = None) -> Path:
    """该平台上**确定的**用户数据目录（候选清单第一条，**不判存在**）。"""
    return userdir_candidates(home=home, platform=platform)[0]


#: 游戏安装根目录（环境变量 → 平台候选 → 确定的回落值）
ROOT = resolve(os.environ.get("V3_ROOT"), game_candidates(), default_game_root())

#: 游戏内容层（mod 覆盖的目标）
GAME = ROOT / "game"

#: 引擎共享层
JOMINI = ROOT / "jomini"
CLAUSEWITZ = ROOT / "clausewitz"

#: 用户数据目录（环境变量 → 平台候选（**全部由 ``Path.home()`` 推导**）→ 确定的回落值）
USERDIR = resolve(os.environ.get("V3_USERDIR"), userdir_candidates(), default_userdir())

#: 本地 mod 目录
LOCAL_MODS = USERDIR / "mod"

#: Steam Workshop 内容目录（**由找到 ROOT 的那个 Steam 根推导** —— 原先两处各写一遍平台路径）
WORKSHOP = resolve(
    os.environ.get("V3_WORKSHOP"),
    (workshop_for(ROOT),),
    workshop_for(default_game_root()),
)

#: mod 的命名空间前缀（F7：策略 `ai_strategy_sitai_*`、变量/本地化 `sitai_*`、文件 `sitai_*.txt`）。
#:
#: 两处用途**必须同源**，所以它住在这里而不是生成器里：
#:   * 生成器用它给策略 / 变量 / 本地化 / 文件起名（`modgen.NAMESPACE_PREFIX`）；
#:   * 扫描器用它认出「用户 mod 目录里哪一个是**我们自己部署**的」
#:     （`.metadata/metadata.json` 的 `id` 形如 `sitai.<档案 id…>`，见 `mods.OWN_MOD_ID_PREFIX`）。
#:
#: 为什么不下沉到 `mods.py` 自己写一份字面量：那是 P9 的重复定义；
#: 为什么不让 `mods.py` 去 import `modgen`：它是被 `analyze / verify / evidence`
#: 共用的底层模块，为一个字符串把 2200 行的生成器拉进它的依赖里不值。
NAMESPACE_PREFIX = "sitai_"

#: 本仓库根目录（tools/ 的上一级）
REPO = Path(__file__).resolve().parents[2]

#: 文档与资料目录
DOCS = REPO / "docs" / "victoria3-modding"
RESEARCH = REPO / "research"

#: 游戏自带官方 ``.md`` 的 UTF-8 无 BOM、LF 镜像（保留原始相对路径）。
#: 原件与规范化镜像分别记录哈希，原始字节副本见审计备份。
#: 由 ``tests/test_docs_mirror.py`` 在装有游戏的环境下看守其时效性 ——
#: 游戏升级后镜像会静默过期，而照过期镜像写 mod 会漏掉新规则（真实踩过）。
OFFICIAL_DOCS_MIRROR = RESEARCH / "official-docs"

#: 中间产物目录（已 gitignore）
OUT = REPO / "tools" / "out"

#: 分析产物的**分仓**目录 —— 游戏本体与 mod 分开存放，互不混杂
OUT_GAME = OUT / "game"
OUT_MODS = OUT / "mods"
OUT_CROSS = OUT / "cross"

#: 人可读报告目录
REPORTS = REPO / "docs" / "reports"

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
    "common",  # 数据定义主体，136 个子目录
    "events",  # 事件脚本
    "gui",  # 界面布局
    "map_data",  # 地图脚本部分（州区域、邻接等）
    "interface",  # 消息类型
    "notifications",  # 通知定义
    "data_binding",  # GUI 数据绑定宏
    "input_profile",  # 输入配置
    "dlc_metadata",  # DLC 元数据定义
    "tools",  # 官方开发工具配置（脚本化测试框架等）
    # ── 覆盖面审计后补入（都是 PDX 脚本，此前被误当资产跳过）──
    "gfx",  # 肖像设置 / 地图物件 / 城市数据 / 模型与实体定义
    "music",  # 音乐轨道与播放器分类
    "sound",  # 环境音、音频参数组与上限
    "content_source",  # 地图物件生成器（.txt 与 gfx 下的生成结果配套）
    "fonts",  # 字体注册表 fonts.font
    # DLC 目录本身是个**小内容根**：``dlc/<名称>/{gfx,music,sound}/``。
    # 实测 17 个 DLC 下有 83 个 .txt 与 514 个 .asset，全是 PDX 脚本，
    # 此前因为顶层目录名是 dlc 而被整体跳过。
    "dlc",
    # ``jomini/jomini/`` 是个**嵌套内容根**，里面只有 ``gui/``。
    # 因为是二级目录，``is_scriptable`` 按 rel_parts[0] 判定时看不到它，
    # 于是 jomini_encyclopedia.gui 一直落在范围外。
    "jomini",
)

#: ① 需要**深度解析**的文件扩展名
SCRIPTABLE_SUFFIXES: tuple[str, ...] = (
    ".txt",  # PDX 脚本
    ".gui",  # 界面布局（同样是花括号语法）
    ".asset",  # 模型 / 实体 / 动画定义。**同为 PDX 语法**：
    # 实测 construction_entities.asset 解析出 7 个顶层键、
    # 嵌套 4 层、0 语法错误，连 @[表达式] 都能正确处理
    ".font",  # 字体注册表（fonts/fonts.font，19 个顶层键）
    ".shortcuts",  # 快捷键绑定
    ".layout",  # 界面布局变体
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
