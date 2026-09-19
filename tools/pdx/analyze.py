"""全量分析：把游戏本体与 mod 本体的全部可提取信息一次性产出。

「全量」的含义
--------------
**不挑目录、不抽样**。具体覆盖：

游戏本体
    * 三个内容根（``game`` / ``jomini`` / ``clausewitz``）的逐目录统计
    * ``common/`` 下每个数据目录的**条目与字段**级提取
    * ``events/`` 等其余可解析目录的条目级提取
    * ``localization/`` 的语言、文件与键名
    * ``gui/`` 的界面文件清单
    * 根级配置文件（校验和清单、路径映射）
    * DLC 描述符与结构
    * 官方 ``.md`` 文档清单
    * 原版是否使用功能前缀（预期为 0）

mod 本体
    * 元数据、文件清单、顶层条目
    * **覆盖**（与原版同相对路径）与**新增**的区分
    * 功能前缀使用与样例
    * 各类型文件分布（脚本 / 本地化 / 图形 / 界面 / 音频）
    * 改动了哪些原版目录与条目

交叉
    * 每个目录被多少 mod 触及
    * 被改动的原版**条目级**清单
    * 同一原版路径被多个 mod 覆盖的**冲突检测**

性能说明：整个游戏树只解析一次（见 :mod:`pdx.cache`）。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import config
from .cache import parse_cached
from .extract import DirExtract, extract_file, global_usage
from .localization import LocalizationReport, extract_localization

# Assignment / Scalar / Block 必须在**运行期**导入：dump_node 用 isinstance
# 区分节点类型，放进 TYPE_CHECKING 会在运行时 NameError（已踩过）。
from .model import Assignment, Block, ParsedFile, Scalar
from .mods import ModInfo, aggregate_prefixes, analyse_all
from .parser import TOLERATED_ERRORS
from .scan import DirStats, FileEntry, stats_for, subdir_stats, walk_files
from .tabular import extract_tables

if TYPE_CHECKING:
    from pathlib import Path

#: 参与分析的内容根
CONTENT_ROOTS: dict[str, Path] = {
    "game": config.GAME,
    "jomini": config.JOMINI,
    "clausewitz": config.CLAUSEWITZ,
}

#: mod 常见文件类型的归类
FILE_CLASSES: dict[str, tuple[str, ...]] = {
    "脚本": (".txt",),
    "本地化": (".yml", ".yaml"),
    "界面": (".gui",),
    "图形": (".dds", ".tga", ".png", ".jpg", ".jpeg", ".webp", ".bmp"),
    "音频": (".wav", ".ogg", ".mp3", ".bank", ".fsb", ".flac"),
    "模型": (".mesh", ".asset", ".anim", ".bin"),
    "文档": (".md",),
}


def classify(suffix: str) -> str:
    for name, exts in FILE_CLASSES.items():
        if suffix in exts:
            return name
    return "其他"


# ── 数据结构 ────────────────────────────────────────────────
@dataclass
class RootFile:
    """根级配置文件的内容摘要。"""

    name: str
    size: int
    kind: str  # text / binary
    summary: dict[str, Any] = field(default_factory=dict)
    text: str = ""  # 仅对小型文本文件保留


@dataclass
class DlcInfo:
    """一个 DLC 的结构与描述符。"""

    name: str
    path: Path
    descriptor: dict[str, str] = field(default_factory=dict)
    top_entries: list[str] = field(default_factory=list)
    files: int = 0
    size: int = 0
    by_class: Counter = field(default_factory=Counter)

    @property
    def has_script_dir(self) -> bool:
        """DLC 是否自带 ``common/`` 等脚本目录（实测全部为否）。"""
        return any(t in ("common", "events", "gui") for t in self.top_entries)


@dataclass
class GameAnalysis:
    """游戏本体的完整画像。"""

    version: dict[str, str] = field(default_factory=dict)
    roots: dict[str, DirStats] = field(default_factory=dict)
    top_dirs: dict[str, list[DirStats]] = field(default_factory=dict)
    #: common 下每个数据目录
    common: dict[str, DirExtract] = field(default_factory=dict)
    #: 其他脚本目录：``"events" -> DirExtract``
    scripts: dict[str, DirExtract] = field(default_factory=dict)
    #: 本地化：``语言 -> {文件, 键出现次数, 去重键}``
    localization: dict[str, dict[str, int]] = field(default_factory=dict)
    #: 本地化的**完整键名清单**（14 万+ 键）。
    #:
    #: 与上面那个 ``localization`` 的区别：那个只有计数，这个有键名本身。
    #: 键名是 mod 作者最需要的信息之一（"这个键存不存在"、"汉化要覆盖哪些键"），
    #: 此前只数了个数、一个键都没记 —— 覆盖面审计里最大的一处遗漏。
    #: 因为体量大，它单独落一个产物文件，不塞进主 JSON。
    localization_detail: LocalizationReport | None = None
    #: GUI 文件清单
    gui_files: list[str] = field(default_factory=list)
    #: 根级配置文件
    root_files: dict[str, RootFile] = field(default_factory=dict)
    #: 校验和清单里列出的目录
    checksummed: list[str] = field(default_factory=list)
    #: 路径映射
    paths: dict[str, str] = field(default_factory=dict)
    #: DLC
    dlcs: list[DlcInfo] = field(default_factory=list)
    #: 官方 .md：相对路径 -> 字节数
    official_docs: dict[str, int] = field(default_factory=dict)
    #: 原版功能前缀使用（预期为空）
    vanilla_prefixes: Counter = field(default_factory=Counter)
    parse_errors: list[tuple[str, str]] = field(default_factory=list)

    # ── 汇总 ────────────────────────────────────────────
    @property
    def total_files(self) -> int:
        return sum(s.files for s in self.roots.values())

    @property
    def total_size(self) -> int:
        return sum(s.size for s in self.roots.values())

    @property
    def total_entries(self) -> int:
        return sum(e.unique_entries for e in self.common.values()) + sum(
            e.unique_entries for e in self.scripts.values()
        )

    def all_keys(self) -> dict[str, list[str]]:
        """``目录名 -> 排序后的全部条目名``（含 common 与 scripts）。"""
        out = {n: sorted(e.entries) for n, e in self.common.items()}
        out.update({n: sorted(e.entries) for n, e in self.scripts.items()})
        return out

    def all_fields(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for name, e in list(self.common.items()) + list(self.scripts.items()):
            merged: set[str] = set()
            for fset in e.fields.values():
                merged |= fset
            out[name] = sorted(merged)
        return out

    def field_usage(self) -> Counter:
        """全局字段使用次数。

        直接用 :func:`pdx.extract.global_usage` —— 这个属性此前把它
        原地重写了一遍（同样是遍历 ``field_usage`` 累加），
        而 ``global_usage`` 因为「没人用」差点被当成死代码删掉。
        """
        return global_usage([*self.common.values(), *self.scripts.values()])

    def summary(self) -> dict[str, Any]:
        return {
            "版本": self.version,
            "内容根": {
                k: {"文件": v.files, "目录": v.dirs, "MB": v.size_mb} for k, v in self.roots.items()
            },
            "文件总计": self.total_files,
            "体积MB": round(self.total_size / 1048576, 1),
            "common 目录数": len(self.common),
            "common 条目数": sum(e.unique_entries for e in self.common.values()),
            "其他脚本目录": {k: v.unique_entries for k, v in self.scripts.items()},
            "本地化语言数": len(self.localization),
            "GUI 文件": len(self.gui_files),
            "根级配置": len(self.root_files),
            "DLC": len(self.dlcs),
            "官方md": len(self.official_docs),
            "原版前缀使用": sum(self.vanilla_prefixes.values()),
            "解析错误": len(self.parse_errors),
        }


# ── 游戏本体分析 ────────────────────────────────────────────
def _read_root_file(path: Path) -> RootFile:
    """读取一个根级配置文件并给出摘要。"""
    rf = RootFile(name=path.name, size=path.stat().st_size, kind="text")
    suffix = path.suffix.lower()
    if suffix in (".tga", ".png", ".dds"):
        rf.kind = "binary"
        return rf
    try:
        rf.text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        rf.kind = "binary"
        return rf

    if path.name == "checksum_manifest.txt":
        rf.summary["目录"] = [
            ln.split("=", 1)[1].strip()
            for ln in rf.text.splitlines()
            if ln.strip().startswith("name")
        ]
    elif path.name == "paths.settings":
        rf.summary["映射"] = {
            parts[0].strip(): parts[1].strip().strip('"')
            for ln in rf.text.splitlines()
            if "=" in ln
            for parts in [ln.split("=", 1)]
        }
    return rf


def _analyse_localization(root: Path) -> dict[str, dict[str, int]]:
    """统计每个语言目录的文件数与键数。

    语言由文件**首行的 ``l_xx:``** 决定，而不是目录名 ——
    ``localization/modifiers/`` 这种目录名并不是语言码。
    """
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"文件": 0, "键": 0})
    loc = root / "localization"
    if not loc.is_dir():
        return {}
    for f in walk_files(loc):
        if f.suffix not in (".yml", ".yaml"):
            continue
        try:
            text = f.path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        lang = "?"
        keys = 0
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.endswith(":") and s.startswith("l_"):
                lang = s[:-1]
                continue
            if ":" in s and not s.startswith("l_"):
                keys += 1
        out[lang]["文件"] += 1
        out[lang]["键"] += keys
    return dict(out)


def _analyse_dlc(root: Path) -> list[DlcInfo]:
    """分析 ``game/dlc/`` 下的每个 DLC。"""
    out: list[DlcInfo] = []
    base = root / "dlc"
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        info = DlcInfo(name=d.name, path=d)
        info.top_entries = sorted(p.name for p in d.iterdir() if p.is_dir()) + sorted(
            p.name for p in d.iterdir() if p.is_file()
        )
        for f in walk_files(d):
            info.files += 1
            info.size += f.size
            info.by_class[classify(f.suffix)] += 1
        # 描述符：同目录下的 .dlc（PDX 格式）
        for desc in d.glob("*.dlc"):
            try:
                txt = desc.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            for line in txt.splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    info.descriptor[k.strip()] = v.strip().strip('"')
            break
        out.append(info)
    return out


def _scriptable_files(root: Path) -> list:
    """收集某个内容根下**需要深度解析**的文件。

    只取 ``SCRIPTABLE_DIRS`` 下、扩展名属 ``SCRIPTABLE_SUFFIXES`` 的文件。
    ``gfx/``、``sound/``、``dlc/`` 等资产目录只做清单统计，不解析 ——
    目标不是读遍游戏，而是**提取所有与 mod 开发有关的信息**。
    """
    out = []
    for f in walk_files(root):
        try:
            rel = f.path.relative_to(root)
        except ValueError:
            continue
        if config.is_scriptable(rel.parts, f.suffix):
            out.append(f)
    return out


def game_analysis(*, verbose: bool = False) -> GameAnalysis:
    """对游戏本体做分析。整棵树只遍历一次，只深度解析 mod 相关文件。"""
    ga = GameAnalysis(version=config.game_version())
    common_root = config.GAME / "common"

    # ── 一次遍历：只解析可脚本化的文件 ───────────────────
    targets: list[tuple[str, FileEntry]] = [
        (name, f)
        for name, root in CONTENT_ROOTS.items()
        if root.is_dir()
        for f in _scriptable_files(root)
    ]
    if verbose:
        print(f"  [游戏] 待解析的 mod 相关文件：{len(targets):,} 个")

    per_common: dict[str, DirExtract] = {}
    per_script: dict[str, DirExtract] = {}
    loose_common = 0

    # 先为**每一个**子目录建好空结果。
    # 不能等遇到 .txt 才创建 —— `scripted_modifiers` 目录下只有 .md 没有 .txt，
    # 那样会让目录数从 136 变成 135，是个真实踩过的错。
    for child in sorted(p for p in common_root.iterdir() if p.is_dir()):
        per_common[child.name] = DirExtract(name=child.name, path=child)
    for name in config.SCRIPTABLE_DIRS:
        if name == "common":
            continue
        d = config.GAME / name
        if d.is_dir():
            per_script[name] = DirExtract(name=name, path=d)

    for i, (root_name, f) in enumerate(targets, 1):
        try:
            pf = parse_cached(f.path)
        except Exception as exc:
            ga.parse_errors.append((str(f.path), f"未捕获异常: {exc}"))
            continue

        root = CONTENT_ROOTS[root_name]
        try:
            rel = f.path.relative_to(root)
        except ValueError:
            continue

        # 原版是否使用功能前缀（含 jomini / clausewitz 层）
        for a in pf.top_assignments:
            if a.prefix:
                ga.vanilla_prefixes[a.prefix] += 1

        # 只有 game 层参与目录级提取；jomini/clausewitz 只计前缀
        if root_name != "game":
            continue

        top = rel.parts[0] if rel.parts else ""
        if top == "common":
            # 散装文件（common/xxx.txt 直接放在 common 根下，不属于任何子目录）
            # 注意 rel 是相对 GAME 的，所以散装文件形如 ("common", "xxx.txt")，
            # 判据是 parts[1] 是不是目录，**不能**用 len(rel.parts) 判断。
            if len(rel.parts) < 2 or not (common_root / rel.parts[1]).is_dir():
                loose_common += 1
                continue
            name = rel.parts[1]
            res = per_common.get(name)
            if res is None:
                res = DirExtract(name=name, path=common_root / name)
                per_common[name] = res
            extract_file(pf, res)
        elif top in config.SCRIPTABLE_DIRS:
            # DLC 下按 ``dlc/<名称>`` 分桶 —— 全糊进一个 "dlc" 会丢掉
            # 「是哪个 DLC 定义的」这个关键信息。
            key = f"dlc/{rel.parts[1]}" if top == "dlc" and len(rel.parts) > 1 else top
            res = per_script.get(key)
            if res is None:
                res = DirExtract(name=key, path=config.GAME / key)
                per_script[key] = res
            extract_file(pf, res)
        if verbose and i % 1000 == 0:
            print(f"    已解析 {i:,}/{len(targets):,} …")

    ga.common = dict(sorted(per_common.items()))
    ga.scripts = dict(sorted(per_script.items()))
    for res in list(ga.common.values()) + list(ga.scripts.values()):
        for path, err in res.errors:
            ga.parse_errors.append((str(path), err))

    # ── 各内容根与一级目录 ─────────────────────────────
    for name, root in CONTENT_ROOTS.items():
        if not root.is_dir():
            continue
        ga.roots[name] = stats_for(root)
        ga.top_dirs[name] = _subdirs(root)
        if verbose:
            s = ga.roots[name]
            print(f"  [{name}] {s.files:,} 文件 / {s.size_mb:,} MB")
    # ── 本地化 ─────────────────────────────────────────
    # 两件事分开做：``_analyse_localization`` 给出各语言的计数（快，
    # 只看行数），``extract_localization`` 给出**完整键名清单**（慢一些，
    # 实测 3.8 秒 / 14.5 万键）。后者此前完全没有，是覆盖面审计发现的
    # 最大一处遗漏 —— 本地化对 mod 来说是最常用的东西。
    ga.localization = _analyse_localization(config.GAME)
    ga.localization_detail = extract_localization(config.GAME)
    if verbose:
        print(f"  [本地化] {len(ga.localization)} 种语言")

    # ── GUI 文件清单 ───────────────────────────────────
    gui_root = config.GAME / "gui"
    if gui_root.is_dir():
        ga.gui_files = sorted(
            str(f.path.relative_to(config.GAME)).replace("\\", "/")
            for f in walk_files(gui_root, suffix=".gui")
        )
    # ── 根级配置文件 ───────────────────────────────────
    # **三个内容根都要看**，不能只读 game 的 —— jomini 与 clausewitz 的根下
    # 也有 PDX 文件（``settings_layout.txt`` / ``compound_settings.txt``），
    # 此前完全没被读到。键名带上内容根前缀以免同名互相覆盖。
    for label, root in CONTENT_ROOTS.items():
        if not root.is_dir():
            continue
        for f in walk_files(root):
            if f.path.parent != root:
                continue
            key = f.path.name if label == "game" else f"{label}/{f.path.name}"
            ga.root_files[key] = _read_root_file(f.path)
    man = ga.root_files.get("checksum_manifest.txt")
    if man:
        ga.checksummed = list(man.summary.get("目录", []))
    ps = ga.root_files.get("paths.settings")
    if ps:
        ga.paths = dict(ps.summary.get("映射", {}))

    # ── DLC ────────────────────────────────────────
    ga.dlcs = _analyse_dlc(config.GAME)
    if verbose:
        n_script = sum(1 for d in ga.dlcs if d.has_script_dir)
        print(f"  [DLC] {len(ga.dlcs)} 个，其中自带脚本目录的 {n_script} 个")

    # ── 官方 .md ───────────────────────────────────────
    # 键带内容根前缀（``game/…`` / ``jomini/…``）：只写相对路径时，
    # 不同内容根下的同名相对路径会**互相覆盖**，篇数悄悄变少而无人察觉。
    for name, root in CONTENT_ROOTS.items():
        if not root.is_dir():
            continue
        for f in walk_files(root, suffix=".md"):
            doc_rel = str(f.path.relative_to(root)).replace("\\", "/")
            ga.official_docs[f"{name}/{doc_rel}"] = f.size
    if verbose and loose_common:
        print(f"  注：common 根下有 {loose_common} 个散装 .txt")
    return ga


def _subdirs(root: Path) -> list[DirStats]:
    """root 下每个直接子目录的统计。

    直接用 :func:`pdx.scan.subdir_stats`：它做的就是这件事，
    而这里此前把同一段逻辑（排序 + 逐个 ``stats_for``）又写了一遍。
    """
    return subdir_stats(root)


# ── mod 分析 ────────────────────────────────────────────────
@dataclass
class ModsAnalysis:
    mods: list[ModInfo] = field(default_factory=list)
    prefixes: Counter = field(default_factory=Counter)
    path_conflicts: dict[str, list[str]] = field(default_factory=dict)
    #: mod 目标 -> 各类型文件数
    by_class: dict[str, Counter] = field(default_factory=dict)
    #: mod 目标 -> 本地化语言 -> 文件数
    localization: dict[str, Counter] = field(default_factory=dict)

    @property
    def total_files(self) -> int:
        return sum(m.files for m in self.mods)

    def summary(self) -> dict[str, Any]:
        return {
            "mod 数": len(self.mods),
            "文件总计": self.total_files,
            "前缀总计": sum(self.prefixes.values()),
            "被多个 mod 覆盖的原版路径": sum(1 for v in self.path_conflicts.values() if len(v) > 1),
        }


def mods_analysis(*, verbose: bool = False) -> ModsAnalysis:
    """对全部 mod 做全量分析。"""
    ma = ModsAnalysis()
    ma.mods = analyse_all()
    ma.prefixes = aggregate_prefixes(ma.mods)

    for m in ma.mods:
        target = m.target
        cls: Counter = Counter()
        loc: Counter = Counter()
        for f in walk_files(m.root):
            rel = f.path.relative_to(m.root)
            if rel.parts and rel.parts[0] == ".metadata":
                continue
            cls[classify(f.suffix)] += 1
            if f.suffix in (".yml", ".yaml") and "localization" in rel.parts:
                idx = rel.parts.index("localization")
                if idx + 1 < len(rel.parts):
                    loc[rel.parts[idx + 1]] += 1
        ma.by_class[target] = cls
        ma.localization[target] = loc

        # 注意别复用 rel —— 上面那个 rel 是 Path，这里是 str
        for rel_str in m.overrides:
            ma.path_conflicts.setdefault(rel_str, []).append(target)

        if verbose:
            print(
                f"  [{target}] {m.name or '(无名)':<38} "
                f"覆盖 {len(m.overrides):>4}  新增 {len(m.additions):>5}"
            )
    return ma


# ── 交叉分析 ────────────────────────────────────────────────
@dataclass
class CrossAnalysis:
    dir_touched_by: Counter = field(default_factory=Counter)
    changed_entries: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    mod_prefixes: dict[str, Counter] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "被 mod 触及的目录数": len(self.dir_touched_by),
            "被改动的原版条目数": sum(len(v) for v in self.changed_entries.values()),
        }


def cross_analysis(ma: ModsAnalysis, *, verbose: bool = False) -> CrossAnalysis:
    """交叉分析：哪些原版条目被哪些 mod 改动过。

    刻意**不收** ``GameAnalysis``：早先签名里有 ``ga``，但函数体从未读过
    它 —— 原版条目是从 ``config.GAME`` 下按相对路径直接解析的，
    不依赖游戏本体分析的中间结果。挂一个用不上的参数只会误导调用方
    以为两者有依赖关系。
    """
    ca = CrossAnalysis()
    for m in ma.mods:
        target = m.target
        ca.mod_prefixes[target] = Counter(m.prefixes)
        for rel in m.overrides:
            top = rel.split("/")[0]
            ca.dir_touched_by[top] += 1

            src = m.root / rel
            dst = config.GAME / rel
            if src.suffix != ".txt" or not dst.is_file():
                continue
            try:
                mf = parse_cached(src)
                vf = parse_cached(dst)
            except Exception:
                continue
            vanilla_keys = set(vf.top_keys)
            bucket = ca.changed_entries.setdefault(top, {})
            for a in mf.top_assignments:
                if a.key in vanilla_keys or a.prefix:
                    bucket.setdefault(a.key, []).append(target)
            if verbose:
                print(f"  [{target}] {rel}")
    return ca


# ── 序列化 ──────────────────────────────────────────────────
def dump_node(node: Any) -> Any:
    """把一个 AST 节点还原成纯数据（嵌套 dict / list / 字符串）。

    这是「**记录信息**」与「**记录名字**」的分界线。

    此前产物对每个条目只记了**第一层字段名**，例如 ``building_angkor_wat``
    只留下 15 个名字：``['background', 'building_group', 'potential', …]``。
    而原文件里是::

        building_group = bg_monuments
        potential = { state_region = s:STATE_CAMBODIA }
        city_gfx_interactions = { clear_size_area = yes  size = 5 }

    值、嵌套结构、列表元素全都没有 —— mod 作者无法据此回答
    「这个字段默认值是多少」「这个块里能写什么」。那不是信息，是目录。

    表示法约定
    ----------
    * 块内有具名赋值 → ``{"键": 值, …}``（键带功能前缀，如 ``REPLACE:foo``）
    * 块内全是裸标量 → ``["a", "b", "c"]``（PDX 的列表写法）
    * 混合 → 保留**顺序**的列表，具名赋值表示为单键 dict
    * 标量 → 字符串原样（不做类型推断：``yes`` / ``1`` / ``foo`` 在语法层
      没有区别，语义由使用处决定）
    * 空值（``key =`` 后直接换行）→ ``None``

    体积实测：与源文件基本同量级（1.68 MB 源 → 1.59 MB 数据），
    全部可解析文本约 45 MB，转储约 42 MB。

    重复键
    ------
    PDX **允许同级出现重复键**，而且真实文件里大量使用 —— 实测全库有
    ``gfx/portraits/accessory_variations/european.txt`` 里 ``variation``
    一个键在同一层出现 **383 次**，全库共 1,299 个顶层条目存在重复。
    若直接建成字典，这些都会被静默覆盖成最后一个，是实打实的信息丢失。

    因此：**只有当键全不重复时才用字典**，一旦检测到重复就退回保序列表
    （每项是单键字典）。判据来自实测数据，不是理论洁癖。
    """
    if node is None:
        return None
    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Block):
        items = node.items
        if all(isinstance(i, Assignment) for i in items):
            assignments = [i for i in items if isinstance(i, Assignment)]
            keys = [f"{a.prefix}:{a.key}" if a.prefix else a.key for a in assignments]
            if len(set(keys)) == len(keys):
                return {k: dump_node(a.value) for k, a in zip(keys, assignments, strict=True)}
        # 含裸标量、匿名块，或**存在重复键** —— 顺序与重数都有意义，用列表
        out: list[Any] = []
        for item in items:
            if isinstance(item, Assignment):
                key = f"{item.prefix}:{item.key}" if item.prefix else item.key
                out.append({key: dump_node(item.value)})
            else:
                out.append(dump_node(item))
        return out
    return None  # pragma: no cover - Node 联合类型已穷尽


def build_entry_index(pf: ParsedFile, prev_line: int = 0) -> dict[str, Any]:
    """为一个已解析文件建立 ``条目 -> {行, 注释}`` 的位置索引。

    注释关联规则：归给**它下方最近的那个条目**，也就是「上一条目之后、
    本条目前面」的注释行。这是 PDX 文件的书写惯例 —— 说明写在被说明的
    条目上方。与条目同行的行尾注释也归它。

    为什么单独建索引而不塞进数据里：数据部分要保持纯净（它就是游戏数据的
    还原），行号与注释属于**元信息**，混进去会让每个嵌套节点都背上额外字段。
    """
    by_line: dict[int, list[str]] = {}
    for lineno, raw in pf.comments:
        text = raw.lstrip("#").strip()
        if text:
            by_line.setdefault(lineno, []).append(text)

    out: dict[str, Any] = {}
    last = prev_line
    for a in pf.top_assignments:
        key = f"{a.prefix}:{a.key}" if a.prefix else a.key
        leading = [text for ln in range(last + 1, a.line + 1) for text in by_line.get(ln, [])]
        out[key] = {"行": a.line, "注释": leading} if leading else {"行": a.line}
        last = a.line
    return out


def to_data_dict() -> dict[str, Any]:
    """把全部分析过的脚本内容**还原成结构化数据**。

    与 ``游戏本体.json`` 的分工：
    * ``游戏本体.json`` 记的是**统计**（每个目录多少条目、多少字段、哪些键）
    * 本产物记的是**内容**（每个条目的字段、值、嵌套结构、位置与注释）

    两者都需要：统计用来做断言与文档，内容用来真正写 mod。

    返回 ``{"数据": …, "索引": …}`` 两层：``数据`` 是纯净的游戏数据还原，
    ``索引`` 是每个条目的行号与上方注释。分开是为了让查询数据的人
    不必过滤元信息。
    """
    data: dict[str, dict[str, Any]] = {}
    index: dict[str, dict[str, Any]] = {}
    for name, root in CONTENT_ROOTS.items():
        if not root.is_dir():
            continue
        bucket: dict[str, Any] = {}
        idx: dict[str, Any] = {}
        for f in _scriptable_files(root):
            try:
                pf = parse_cached(f.path)
            except TOLERATED_ERRORS:  # pragma: no cover - 与主流程同口径
                continue
            rel = f.path.relative_to(root)
            key = "/".join(rel.parts)
            try:
                # **复用 dump_node**，不要在这里另写一遍字典推导式：
                # 文件顶层同样可能有重复键（实测 european.txt 里
                # ``variation`` 出现 383 次），自己写的那份会把它们压掉。
                # 这个 bug 正是「修了 dump_node 却在调用处又绕过去」造成的。
                bucket[key] = dump_node(pf.root)
                idx[key] = build_entry_index(pf)
            except RecursionError:  # pragma: no cover - 病态嵌套
                continue
        if bucket:
            data[name] = bucket
            index[name] = idx
    return {"数据": data, "索引": index}


def _dir_to_dict(d: DirStats) -> dict[str, Any]:
    return {
        "目录": d.name,
        "文件": d.files,
        "子目录": d.dirs,
        "MB": d.size_mb,
        "文本文件": d.text_files,
        "二进制文件": d.binary_files,
        "扩展名分布": dict(d.by_suffix.most_common()),
    }


def _extract_to_dict(e: DirExtract) -> dict[str, Any]:
    return {
        "文件": e.files,
        "顶层条目数": e.unique_entries,
        "条目": sorted(e.entries),
        "@变量数": len(e.variables),
        "@变量": sorted(e.variables),
        "字段数": len(e.fields),
        "字段": {k: sorted(v) for k, v in sorted(e.fields.items())},
        "字段使用次数": dict(e.field_usage.most_common()),
        "功能前缀": dict(e.prefixed),
        "带BOM文件": e.bom_files,
        "最大深度": e.max_depth,
        "解析错误": [{"文件": str(p), "消息": m} for p, m in e.errors],
    }


def to_game_dict(ga: GameAnalysis) -> dict[str, Any]:
    """游戏本体的完整数据。**不含任何 mod 内容。**"""
    return {
        "概览": ga.summary(),
        "内容根": {k: _dir_to_dict(v) for k, v in ga.roots.items()},
        "一级目录": {k: [_dir_to_dict(d) for d in v] for k, v in ga.top_dirs.items()},
        "common": {k: _extract_to_dict(v) for k, v in ga.common.items()},
        "其他脚本目录": {k: _extract_to_dict(v) for k, v in ga.scripts.items()},
        "本地化": ga.localization,
        "GUI文件": ga.gui_files,
        "根级配置": {
            k: {"字节": v.size, "类型": v.kind, "摘要": v.summary} for k, v in ga.root_files.items()
        },
        "校验和目录": ga.checksummed,
        "路径映射": ga.paths,
        "DLC": [
            {
                "名称": d.name,
                "文件": d.files,
                "MB": round(d.size / 1048576, 2),
                "顶层条目": d.top_entries,
                "类型分布": dict(d.by_class),
                "描述符": d.descriptor,
                "自带脚本目录": d.has_script_dir,
            }
            for d in ga.dlcs
        ],
        "官方文档": ga.official_docs,
        "原版功能前缀": dict(ga.vanilla_prefixes),
        "解析错误": [{"文件": p, "消息": m} for p, m in ga.parse_errors],
    }


def to_mods_dict(ma: ModsAnalysis) -> dict[str, Any]:
    """全部 mod 的完整数据。**不含游戏本体内容。**"""
    return {
        "概览": ma.summary(),
        "各mod": [
            {
                **m.summary(),
                "顶层条目": m.top_entries,
                "覆盖的文件": m.overrides,
                "新增的文件": m.additions,
                "功能前缀": dict(m.prefixes),
                "前缀样例": [{"前缀": p, "键": k, "文件": f} for p, k, f in m.prefix_samples[:200]],
                "改动的原版目录": dict(m.touched_vanilla),
                "新增条目所在目录": dict(m.added_entries),
                "文件类型分布": dict(ma.by_class.get(m.target, {})),
                "本地化语言": dict(ma.localization.get(m.target, {})),
            }
            for m in ma.mods
        ],
        "全部功能前缀": dict(ma.prefixes),
        "路径冲突": {k: sorted(set(v)) for k, v in ma.path_conflicts.items() if len(v) > 1},
    }


def to_cross_dict(ca: CrossAnalysis) -> dict[str, Any]:
    """交叉数据。引用两侧，但自身独立成文件。"""
    return {
        "概览": ca.summary(),
        "目录被触及次数": dict(ca.dir_touched_by.most_common()),
        "被改动的原版条目": {
            k: {ek: sorted(set(ev)) for ek, ev in v.items()} for k, v in ca.changed_entries.items()
        },
    }


# ── 报告 ────────────────────────────────────────────────────
#: 输出**分开存放**：游戏本体与 mod 各自独立成文件，互不混杂。
#: 目录常量集中在 :mod:`pdx.config`，便于统一调整。
GAME_OUT = config.OUT_GAME
MODS_OUT = config.OUT_MODS
CROSS_OUT = config.OUT_CROSS


def write_reports(ga: GameAnalysis, ma: ModsAnalysis, ca: CrossAnalysis) -> dict[str, Path]:
    """落盘。游戏本体、mod、交叉三者**分别存放**。"""
    for d in (GAME_OUT, MODS_OUT, CROSS_OUT, config.REPORTS):
        d.mkdir(parents=True, exist_ok=True)

    def dump(obj: Any, path: Path, *, compact: bool = False) -> None:
        """落盘 JSON。

        ``compact=True`` 用无空白的紧凑格式。游戏数据产物有 **12 万条目**，
        缩进版 122 MB、紧凑版 52 MB —— 差了 70 MB 的纯空白，
        写盘还多花约 7 秒。它是给程序读的数据文件，不是给人读的报告；
        要看内容用 ``jq`` 或查询工具。其余产物仍用缩进，保留可读与可 diff。
        """
        if compact:
            text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        else:
            text = json.dumps(obj, ensure_ascii=False, indent=2)
        # newline="\n" 是**必须**的：不传时 Python 按平台翻译换行，Windows 上
        # 写出 CRLF、Linux 上写出 LF，于是同一份数据在两边的**字节数不同** ——
        # 而黄金回归冻结的正是逐字节 sha256。那会让「冻结值」变成
        # 「Windows 专属值」，CI（Linux）上根本对不上，还查不出来。
        path.write_text(text, encoding="utf-8", newline="\n")

    out: dict[str, Path] = {}

    g = GAME_OUT / "游戏本体.json"
    dump(to_game_dict(ga), g)
    out["游戏本体 JSON"] = g

    m = MODS_OUT / "mod.json"
    dump(to_mods_dict(ma), m)
    out["mod JSON"] = m

    if ca.dir_touched_by or ca.changed_entries:
        c = CROSS_OUT / "交叉.json"
        dump(to_cross_dict(ca), c)
        out["交叉 JSON"] = c

    # 表格类数据。全库只有 map_data/adjacencies.csv 一个，但它定义
    # **海峡与陆地连通性**，mod 改地图边界时必动 —— 此前它既不是 PDX
    # 脚本、也没有专用读取器，落在所有范围之外。不是 PDX 语法，
    # 因此单独一个产物。
    tables = {name: extract_tables(root) for name, root in CONTENT_ROOTS.items()}
    if any(r.tables for r in tables.values()):
        tb = GAME_OUT / "表格数据.json"
        dump(
            {
                "概览": {k: r.summary() for k, r in tables.items()},
                "表格": {
                    k: {tb_.rel: tb_.to_dict() for tb_ in r.tables}
                    for k, r in tables.items()
                    if r.tables
                },
            },
            tb,
        )
        out["表格数据 JSON"] = tb

    # 结构化游戏数据：每个条目的字段、值、嵌套结构、位置与注释。
    # 与主 JSON 的分工 —— 那个记统计，这个记内容。
    data = GAME_OUT / "游戏数据.json"
    dump(to_data_dict(), data, compact=True)
    out["游戏数据 JSON"] = data

    # 本地化的完整键名清单单独一个文件：14 万+ 键、数 MB，
    # 塞进主 JSON 会让那份 8 MB 的文件翻倍，而查询键名的人
    # 本来就不需要同时看 common 目录的字段表。
    if ga.localization_detail is not None:
        loc = GAME_OUT / "本地化.json"
        dump(ga.localization_detail.to_dict(), loc)
        out["本地化 JSON"] = loc

    p = config.REPORTS / "游戏本体分析.md"
    p.write_text(render_game_markdown(ga), encoding="utf-8", newline="\n")
    out["游戏本体报告"] = p

    p = config.REPORTS / "mod分析.md"
    p.write_text(render_mods_markdown(ma, ca), encoding="utf-8", newline="\n")
    out["mod 报告"] = p

    return out


def render_game_markdown(ga: GameAnalysis) -> str:
    """游戏本体报告。"""
    out: list[str] = []
    add = out.append
    add("# Victoria 3 游戏本体全量分析")
    add("")
    add("> 由 `tools/pdx/analyze.py` 自动生成，请勿手工编辑。")
    add("> 本文件只含**游戏本体**内容，mod 相关内容见 `mod分析.md`。")
    add("")

    v = ga.version
    add("## 一、概览")
    add("")
    add("| 项目 | 值 |")
    add("|---|---|")
    add(f"| 版本 | **{v.get('caligula_branch', '?')}** |")
    add(f"| Clausewitz | `{v.get('clausewitz_branch', '?')}` |")
    add(f"| 文件总计 | **{ga.total_files:,}** |")
    add(f"| 体积 | **{ga.total_size / 1048576:,.1f} MB** |")
    add(f"| `common` 目录数 | **{len(ga.common)}** |")
    add(f"| `common` 条目总数 | **{sum(e.unique_entries for e in ga.common.values()):,}** |")
    add(f"| 本地化语言 | **{len(ga.localization)}** |")
    add(f"| GUI 文件 | **{len(ga.gui_files)}** |")
    add(f"| DLC | **{len(ga.dlcs)}** |")
    add(f"| 官方 `.md` | **{len(ga.official_docs)}** |")
    add(f"| 原版功能前缀使用 | **{sum(ga.vanilla_prefixes.values())}**（应为 0，该机制专供 mod） |")
    add(f"| 解析错误 | **{len(ga.parse_errors)}** |")
    add("")

    add("## 二、内容根")
    add("")
    add("| 根 | 文件 | 目录 | MB | 文本 | 二进制 |")
    add("|---|---:|---:|---:|---:|---:|")
    for k, s in sorted(ga.roots.items()):
        add(
            f"| `{k}` | {s.files:,} | {s.dirs:,} | {s.size_mb:,.1f} | {s.text_files:,} | {s.binary_files:,} |"
        )
    add("")

    add("## 三、联机校验和范围")
    add("")
    add("来自 `game/checksum_manifest.txt` —— 只有这些目录参与校验：")
    add("")
    for d in ga.checksummed:
        add(f"- `{d}`")
    add("")
    add("> 改动这些目录会影响联机兼容性；改 `gfx/`、`sound/`、`music/`、`fonts/` 则不会。")
    add("")

    add("## 四、common 各目录（按条目数排序）")
    add("")
    add("| 目录 | 文件 | 条目 | 字段 | 带BOM | 错误 |")
    add("|---|---:|---:|---:|---:|---:|")
    for name, e in sorted(ga.common.items(), key=lambda kv: -kv[1].unique_entries):
        add(
            f"| `{name}` | {e.files} | {e.unique_entries:,} | {len(e.fields)} | {e.bom_files} | {len(e.errors)} |"
        )
    add("")

    if ga.scripts:
        add("## 五、其他脚本目录")
        add("")
        add("| 目录 | 文件 | 条目 |")
        add("|---|---:|---:|")
        for name, e in sorted(ga.scripts.items()):
            add(f"| `{name}` | {e.files} | {e.unique_entries:,} |")
        add("")

    add("## 六、本地化")
    add("")
    add("| 语言 | 文件 | 键 |")
    add("|---|---:|---:|")
    for lang, st in sorted(ga.localization.items(), key=lambda kv: -kv[1]["键"]):
        add(f"| `{lang}` | {st['文件']:,} | {st['键']:,} |")
    add("")

    add("## 七、DLC")
    add("")
    add("| DLC | 文件 | MB | 自带脚本目录 |")
    add("|---|---:|---:|:--:|")
    # 同样避开 d：本函数上半部分用 d 表示目录名字符串
    for dlc in ga.dlcs:
        add(
            f"| `{dlc.name}` | {dlc.files:,} | {dlc.size / 1048576:.2f} | "
            f"{'是' if dlc.has_script_dir else '否'} |"
        )
    add("")
    add("> 实测全部 DLC 均不自带 `common/` 等脚本目录，只含 `gfx`/`sound`/`music` 资产。")
    add("")

    return "\n".join(out)


def render_mods_markdown(ma: ModsAnalysis, ca: CrossAnalysis) -> str:
    """mod 报告。"""
    out: list[str] = []
    add = out.append
    add("# Victoria 3 Mod 全量分析")
    add("")
    add("> 由 `tools/pdx/analyze.py` 自动生成，请勿手工编辑。")
    add("> 本文件只含 **mod** 内容，游戏本体相关内容见 `游戏本体分析.md`。")
    add("")

    add("## 一、概览")
    add("")
    add(f"- mod 数：**{len(ma.mods)}**")
    add(f"- 文件总计：**{ma.total_files:,}**")
    add(f"- 功能前缀总计：**{sum(ma.prefixes.values()):,}**")
    add("")

    add("## 二、功能前缀分布")
    add("")
    add("引擎内置的键级覆盖机制。原版一处不用，全部来自 mod。")
    add("")
    add("| 前缀 | 次数 |")
    add("|---|---:|")
    for k, n in ma.prefixes.most_common():
        add(f"| `{k}:` | {n:,} |")
    add("")

    add("## 三、各 mod")
    add("")
    add("| 目标 | 名称 | 文件 | 覆盖原版 | 新增 | 前缀 | 支持版本 |")
    add("|---|---|---:|---:|---:|---:|---|")
    for m in ma.mods:
        add(
            f"| `{m.target}` | {m.name or '—'} | {m.files:,} | {len(m.overrides):,} "
            f"| {len(m.additions):,} | {sum(m.prefixes.values()):,} "
            f"| {m.supported_game_version or '—'} |"
        )
    add("")

    add("## 四、文件类型分布")
    add("")
    add("| 目标 | " + " | ".join(FILE_CLASSES) + " |")
    add("|---" * (len(FILE_CLASSES) + 1) + "|")
    for m in ma.mods:
        cls = ma.by_class.get(m.target, Counter())
        cells = " | ".join(str(cls.get(k, 0)) for k in FILE_CLASSES)
        add(f"| `{m.target}` | {cells} |")
    add("")

    add("## 五、交叉：被 mod 触及的原版目录")
    add("")
    if ca.dir_touched_by:
        # 表头必须写清口径：`dir_touched_by` 数的是「被覆盖的**文件**数」
        # （跨 mod 累加，同一文件被两个 mod 覆盖算两次），不是 mod 数。
        # 早先写成「被多少个 mod 覆盖过」，于是出现「gfx 被 51 个 mod 覆盖」
        # 这种与全库只有 23 个 mod 自相矛盾的数字（实测 gfx 只涉及 3 个 mod）。
        add("| 目录 | 被覆盖的原版文件数<sup>①</sup> | 涉及的 mod 数<sup>②</sup> |")
        add("|---|---:|---:|")
        for k, n in ca.dir_touched_by.most_common():
            n_mods = sum(
                1 for m in ma.mods if any(p == k or p.startswith(f"{k}/") for p in m.overrides)
            )
            add(f"| `{k}` | {n} | {n_mods} |")
        add("")
        add("> ① 跨 mod 累加，同一文件被两个 mod 覆盖算两次；**不含新增文件**。")
        add("> ② 在该目录下有覆盖行为的 mod 个数（去重）。两者量级不同，勿混用 ——")
        add("> 例如 `gfx` 是「51 个文件被覆盖、涉及 3 个 mod」。")
    else:
        add("（无覆盖行为）")
    add("")

    add("## 六、路径冲突检测")
    add("")
    conflicts = {k: v for k, v in ma.path_conflicts.items() if len(v) > 1}
    if conflicts:
        add("| 原版路径 | 覆盖它的 mod |")
        add("|---|---|")
        for path, mods in sorted(conflicts.items()):
            add(f"| `{path}` | {', '.join(sorted(set(mods)))} |")
    else:
        add("**无冲突** —— 没有任何原版路径被两个及以上 mod 覆盖。")
    add("")

    return "\n".join(out)
