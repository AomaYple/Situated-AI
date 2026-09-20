"""原版真值的**统一读取口**：读游戏本体，或者读入库的精简快照。

为什么需要
----------
闸门 ①② 与 ``v3 ai-surface --check`` 都在回答同一类问题：「这个名字原版里
有没有」。而原版只在**装了游戏**的机器上才有 —— CI runner 上没有游戏，于是
这两道门禁一直只能在本机跑（G-EXIT-2 的缺口），在 CI 上只能报「前置条件缺失」。

做法：同一批真值，两种来源
--------------------------
* ``game``（默认）：现读 ``game/`` 目录，行为与改造前**逐字节一致**；
* ``snapshot``（``--offline``）：读入库的精简快照
  ``tools/out/snapshots/*.compact.json``。

两条路取到的必须是**同一个集合**，所以抽取函数只写一份：本模块的
:func:`vanilla_keys` / :func:`vocabulary_dir` / :func:`modifier_field_names` /
:func:`dir_files` 既供 ``game`` 源现算，也供 :func:`snapshot_sections` 在
**生成快照时**写域 —— 两边同源，不是抄一份常量。

未覆盖 ≠ 通过（P13）
--------------------
快照里没有那个域/目录时，访问器返回 ``None``，**不是空集**：空集会被读成
「原版里没有这个名字」，从而把「没查」变成红或绿两种错误结论。调用方必须把
``None`` 记成「离线未覆盖」并明确列出来。

口径上的两处实测结论（与计划文档不一致，以实测为准）
----------------------------------------------------
1. **不复用 ``common_entries``**：计划里写「目录顶层键用现有 ``common_entries``
   直接可用」，实测 ``common_entries["defines"]`` = 50 而 ``vanilla_keys`` = 72
   ——差 22 个 ``@变量``（快照的 ``_scriptable_names`` 过滤 ``is_variable``，
   而 ``model.top_keys`` 不过滤）。复用会让**离线池窄于在线池**，也就是
   「离线绿、在线红」的假绿。故单立 ``vanilla_keys`` 域（+287 KB）。
2. **计划里的「7 个目录 634 个文件」实测是 300 个**（那 7 个目录下 walk 到的
   全部文件）；本地化另有 1877 个文件。路径域按「键目录 + ``localization``」
   共 8 个根写入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config, defines
from .cache import parse_cached
from .model import Block
from .scan import walk_files

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from .snapshot import Snapshot

#: 闸门 ① 要比「顶层键」的原版目录（相对 ``game/`` 的 posix 路径）。
KEY_DIRS: tuple[str, ...] = (
    "common/scripted_effects",
    "common/static_modifiers",
    "common/journal_entries",
    "common/ai_strategies",
    "common/defines",
    "common/journal_entry_groups",
    "common/country_definitions",
)

#: 闸门 ② 的「原版词汇表」扫描目录（收任意深度的键名）。
VOCABULARY_DIRS: tuple[str, ...] = (
    "common/journal_entries",
    "common/scripted_effects",
    "common/scripted_triggers",
    "common/on_actions",
)

#: 修正字段池目录：修正体里**被赋过值**的字段名。
MODIFIER_FIELD_DIR = "common/static_modifiers"

#: 图标根目录：闸门 ② 的图标存在性检查只覆盖它下面。
ICON_DIR = "gfx/interface/icons"

#: 路径撞车检查覆盖的目录 = 键目录 + 本地化（我们产物可能落到的那些）。
PATH_DIRS: tuple[str, ...] = (*KEY_DIRS, "localization")

#: 快照里的域（名字必须与 :mod:`pdx.snapshot` 写入时一致）。
SECTION_KEYS = "vanilla_keys"
SECTION_VOCABULARY = "vocabulary"
SECTION_MODIFIER_FIELDS = "modifier_fields"
SECTION_PATHS = "mod_paths"
SECTION_ICONS = "icon_paths"

#: 本模块 :func:`snapshot_sections` 产出的全部域（顺序即写入顺序）。
SECTIONS: tuple[str, ...] = (
    SECTION_KEYS,
    SECTION_VOCABULARY,
    SECTION_MODIFIER_FIELDS,
    SECTION_PATHS,
    SECTION_ICONS,
)

#: 快照里**已有**的 defines 参数池（由 :mod:`pdx.snapshot` 自己写，这里只读）。
#: 不 import 那边的常量：``snapshot`` 反过来要 import 本模块，会成环。
SNAPSHOT_DEFINES = "defines"

#: 闸门 ① 离线时要用的域（缺域 ⇒ 报前置条件缺失，而不是"未覆盖"）。
KEYS_GATE_SECTIONS: tuple[str, ...] = (SECTION_KEYS, SECTION_PATHS)

#: 闸门 ② 离线时要用的域。
REFS_GATE_SECTIONS: tuple[str, ...] = (*SECTIONS, SNAPSHOT_DEFINES)


# ── 抽取（只有一份实现：game 源现算，快照源由它在生成时写入）──────
def vanilla_keys(directory: Path) -> set[str]:
    """某个原版目录下全部 ``.txt`` 的**顶层键**（含 ``@变量``）。

    口径与 :attr:`pdx.model.ParsedFile.top_keys` 一致 —— **不过滤** ``@变量``：
    闸门 ① 问的是「这个名字原版里有没有」，多收一个名字只会更严，不会放水。
    """
    if not directory.is_dir():
        return set()
    out: set[str] = set()
    for path in sorted(directory.rglob("*.txt")):
        out.update(parse_cached(path).top_keys)
    return out


def vocabulary_dir(directory: Path) -> set[str]:
    """某个原版目录下出现过的**全部键名**（任意深度）——触发器/效果词汇表。

    刻意做浅（只收键名，不问语义）：这份表的用途是回答「这个名字在原版里存
    在吗」，而「语法是否合法」要进游戏才知道（doc 04 §13 的四条配方）。
    """
    if not directory.is_dir():
        return set()
    out: set[str] = set()
    for path in sorted(directory.rglob("*.txt")):
        stack: list[Block] = [parse_cached(path).root]
        while stack:
            block = stack.pop()
            for item in block.assignments():
                out.add(item.key)
                if isinstance(item.value, Block):
                    stack.append(item.value)
    return out


def modifier_field_names(directory: Path) -> set[str]:
    """原版修正体里**被赋过值**的字段名（含嵌套块里的）。

    与 :func:`vocabulary_dir` 同一套解析口径，只换目录 —— 差别在于这里收的是
    「修正体里写了哪些字段」，于是闸门 ② 能回答「我们写的这个字段原版真的
    存在吗」。原版 ``00_code_static_modifiers.txt`` 的 ``base_values`` 也是
    顶层修正，一并收进来。
    """
    if not directory.is_dir():
        return set()
    out: set[str] = set()
    for path in sorted(directory.rglob("*.txt")):
        stack: list[Block] = [parse_cached(path).root]
        while stack:
            block = stack.pop()
            for item in block.assignments():
                if isinstance(item.value, Block):
                    stack.append(item.value)
                else:
                    out.add(item.key)
    return out


def dir_files(root: Path, rel: str) -> list[str]:
    """``root/rel`` 下全部文件的相对路径（posix，排序）。"""
    base = root / rel
    if not base.is_dir():
        return []
    out: list[str] = []
    for entry in walk_files(base):
        try:
            out.append(entry.path.relative_to(root).as_posix())
        except ValueError:  # pragma: no cover - walk_files 只产 root 下的路径
            continue
    return sorted(out)


def snapshot_sections(game: Path) -> dict[str, dict[str, list[str]]]:
    """把原版真值**编码**成快照域（供 :func:`pdx.snapshot.build` 调用）。

    每个域的形状都是 ``根目录/域键 -> 排序后的字符串列表``，与快照其它域一致；
    **目录不存在也写空列表** —— 这样「键不存在」只可能是「快照太旧」，
    离线侧才能把它判成「未覆盖」而不是「原版没有」（P13）。
    """
    return {
        SECTION_KEYS: {rel: sorted(vanilla_keys(game / rel)) for rel in KEY_DIRS},
        SECTION_VOCABULARY: {rel: sorted(vocabulary_dir(game / rel)) for rel in VOCABULARY_DIRS},
        SECTION_MODIFIER_FIELDS: {
            MODIFIER_FIELD_DIR: sorted(modifier_field_names(game / MODIFIER_FIELD_DIR))
        },
        SECTION_PATHS: {rel: dir_files(game, rel) for rel in PATH_DIRS},
        SECTION_ICONS: {ICON_DIR: dir_files(game, ICON_DIR)},
    }


# ── 索引 ────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class VanillaIndex:
    """原版真值的来源（游戏本体或入库快照）。

    ``source == "game"`` 时 ``sections`` 为空、一切现算；``source == "snapshot"``
    时 ``game`` 只用于报错文案，真值全部来自 ``sections``。
    """

    source: str
    game: Path
    #: 快照的版本标签（``snapshot`` 源才有）。
    version: str = ""
    #: 快照文件路径（人读用）。
    origin: str = ""
    sections: Mapping[str, Mapping[str, list[str]]] = field(default_factory=dict)

    @property
    def offline(self) -> bool:
        return self.source == "snapshot"

    def describe(self) -> str:
        """一句话说清「这批真值是哪来的」（P13：结论里必须能看出用了哪份真值）。"""
        if self.source == "snapshot":
            return f"入库快照 {self.origin}（版本 {self.version or '?'}）"
        return f"游戏本体 {self.game}"

    def missing_sections(self, needed: Iterable[str] = SECTIONS) -> tuple[str, ...]:
        """``needed`` 里这份来源**答不了**的域（游戏源恒为空 —— 它现算）。"""
        if self.source != "snapshot":
            return ()
        return tuple(sorted(name for name in needed if not self.sections.get(name)))

    # ── 访问器：``None`` = 离线未覆盖（**不是**「原版没有」）──────
    def keys(self, rel: str) -> set[str] | None:
        """某个原版目录的顶层键池。"""
        if self.source != "snapshot":
            return vanilla_keys(self.game / rel)
        body = self.sections.get(SECTION_KEYS)
        if body is None or rel not in body:
            return None
        return set(body[rel])

    def defines_params(self) -> dict[str, set[str]] | None:
        """``defines`` 命名空间 → 参数名（只取 ``game`` 层，与在线同一个根）。"""
        if self.source != "snapshot":
            report = defines.extract_defines(self.game / "common" / "defines")
            merged: dict[str, set[str]] = {}
            for ns in report.namespaces:
                merged.setdefault(ns.name, set()).update(ns.param_names)
            return merged
        body = self.sections.get(SNAPSHOT_DEFINES)
        if not body:
            return None
        return {
            name.split("/", 1)[1]: set(params)
            for name, params in body.items()
            if name.startswith("game/")
        }

    def vocabulary(self) -> set[str] | None:
        """:data:`VOCABULARY_DIRS` 四个目录的键名并集（与在线同一个并集）。"""
        if self.source != "snapshot":
            out: set[str] = set()
            for rel in VOCABULARY_DIRS:
                out |= vocabulary_dir(self.game / rel)
            return out
        body = self.sections.get(SECTION_VOCABULARY)
        if body is None or any(rel not in body for rel in VOCABULARY_DIRS):
            return None
        out = set()
        for rel in VOCABULARY_DIRS:
            out |= set(body[rel])
        return out

    def modifier_fields(self) -> set[str] | None:
        """修正字段池（``common/static_modifiers`` 里被赋过值的字段名）。"""
        if self.source != "snapshot":
            return modifier_field_names(self.game / MODIFIER_FIELD_DIR)
        body = self.sections.get(SECTION_MODIFIER_FIELDS)
        if body is None or MODIFIER_FIELD_DIR not in body:
            return None
        return set(body[MODIFIER_FIELD_DIR])

    def tags(self) -> set[str] | None:
        """国家 tag 池（``country_definitions`` 的顶层键）。"""
        return self.keys("common/country_definitions")

    def path_exists(self, rel: str) -> bool | None:
        """``game/<rel>`` 这个文件在不在（``None`` = 离线未覆盖该目录）。

        按**最长匹配的已覆盖根目录**判定：我们产物落在 ``common/defines/`` 下
        时用 ``mod_paths`` 里那个根的清单，落在 ``gfx/interface/icons/`` 下时用
        ``icon_paths``；两个域都没覆盖到的路径一律返回 ``None``。
        """
        if self.source != "snapshot":
            return (self.game / rel).exists()
        pools = self._pools()
        if pools is None:
            return None
        best: str | None = None
        for root in pools:
            if (rel == root or rel.startswith(root + "/")) and (
                best is None or len(root) > len(best)
            ):
                best = root
        if best is None:
            return None
        return rel in pools[best]

    def icon_exists(self, rel: str) -> bool | None:
        """图标路径在不在原版里（只有 ``gfx/interface/icons`` 下面可判）。"""
        if self.source != "snapshot":
            return (self.game / rel).is_file()
        return self.path_exists(rel)

    def ai_surface(self) -> Mapping[str, list[str]] | None:
        """原版 AI 面的原始记录（解码在 :mod:`pdx.ai_surface`）。"""
        if self.source != "snapshot":
            return None
        body = self.sections.get("ai_surface")
        return body or None

    def _pools(self) -> dict[str, set[str]] | None:
        """``路径域 -> 文件集合``；两个域都缺时返回 ``None``。"""
        paths = self.sections.get(SECTION_PATHS)
        icons = self.sections.get(SECTION_ICONS)
        if not paths and not icons:
            return None
        out: dict[str, set[str]] = {}
        for body in (paths, icons):
            for root, files in (body or {}).items():
                out[root] = set(files)
        return out


def game_index(game: Path | None = None) -> VanillaIndex | None:
    """游戏本体来源；``game/`` 不存在时返回 ``None``（= 前置条件缺失）。"""
    root = game or config.GAME
    if not (root / "common").is_dir():
        return None
    return VanillaIndex(source="game", game=root)


def snapshot_index(path: Path | None = None) -> VanillaIndex | None:
    """入库精简快照来源；仓库里一份快照都没有时返回 ``None``。

    「哪份快照算数」直接用 :func:`pdx.verify.latest_compact_snapshot_path` ——
    与 ``v3 verify --from-snapshot`` / ``v3 tables --offline`` 同一处规则，
    不在本模块再写第二份（两处各写一份，迟早出现「verify 认、闸门不认」）。
    """
    from .verify import (  # noqa: PLC0415 - 只在离线路径上需要，避免导入期变重
        latest_compact_snapshot,
        latest_compact_snapshot_path,
    )

    target = path
    if target is None:
        target = latest_compact_snapshot_path()
    if target is None:
        return None
    snap = latest_compact_snapshot() if path is None else _load(path)
    if snap is None:
        return None
    return from_snapshot(snap, origin=target)


def _load(path: Path) -> Snapshot | None:
    from .snapshot import Snapshot  # noqa: PLC0415 - 避免与 snapshot 的循环导入

    try:
        return Snapshot.load(path)
    except (OSError, ValueError):
        return None


def from_snapshot(snap: Snapshot, *, origin: Path | None = None) -> VanillaIndex:
    """把一份快照包成索引。"""
    return VanillaIndex(
        source="snapshot",
        game=config.GAME,
        version=snap.version_label,
        origin=str(origin) if origin is not None else "?",
        sections=snap.sections,
    )


def load(*, offline: bool = False, game: Path | None = None) -> VanillaIndex | None:
    """按需取真值来源。

    ``offline=True`` 时**只认快照**（即使本机装了游戏也一样）—— 否则「离线
    通道」在本机永远是走游戏那条路，等于没测过 CI 会跑的那条。
    """
    if offline:
        return snapshot_index()
    return game_index(game)


__all__ = [
    "ICON_DIR",
    "KEY_DIRS",
    "MODIFIER_FIELD_DIR",
    "PATH_DIRS",
    "SECTIONS",
    "SECTION_ICONS",
    "SECTION_KEYS",
    "SECTION_MODIFIER_FIELDS",
    "SECTION_PATHS",
    "SECTION_VOCABULARY",
    "SNAPSHOT_DEFINES",
    "VOCABULARY_DIRS",
    "VanillaIndex",
    "dir_files",
    "from_snapshot",
    "game_index",
    "load",
    "modifier_field_names",
    "snapshot_index",
    "snapshot_sections",
    "vanilla_keys",
    "vocabulary_dir",
]
