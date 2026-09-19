"""核对：把知识库文档里的数量断言变成可自动运行的检查。

设计取舍
--------
有两种做法：

A. 从文档散文里正则抽取数字，再猜它指的是什么。
B. 维护一份**显式断言注册表**，每条断言写明「查什么、期望多少、出自哪篇文档」。

本模块选 **B**，并额外提供 :func:`find_unregistered_claims` 做覆盖率扫描，
防止文档里新增了断言却忘了登记。理由：A 太脆弱 —— 同一句话里的
「3,099 个文件」到底是含 .md 的全部文件数还是只算 .txt，正则无法判断，
而这两种口径在本项目里确实给出不同数字（3099 vs 3024）。

断言类型
--------
每条断言声明一个 ``kind``，由对应的检查函数实现。新增类型只需在
``_CHECKS`` 里注册一个函数。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .extract import extract_dir
from .model import Block
from .mods import aggregate_prefixes, analyse_all, vanilla_prefix_count
from .scan import count_files
from .snapshot import SNAPSHOT_DIR, Snapshot

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


# ── 数据结构 ────────────────────────────────────────────────
@dataclass(slots=True)
class Claim:
    """一条待核对的断言。"""

    id: str  # 唯一标识
    doc: str  # 出处文档（文件名）
    text: str  # 断言内容的人类可读描述
    kind: str  # 检查类型
    target: str  # 目标（目录名 / 文件 / 命名空间等）
    expected: object  # 期望值
    note: str = ""  # 补充说明（口径等）


@dataclass(slots=True)
class CheckResult:
    claim: Claim
    actual: object
    ok: bool
    error: str = ""

    def line(self) -> str:
        mark = "✅" if self.ok else "❌"
        detail = f"期望 {self.claim.expected}，实得 {self.actual}"
        if self.error:
            detail = f"执行失败：{self.error}"
        return f"{mark} [{self.claim.id}] {self.claim.text} — {detail}"


# ── 检查实现 ────────────────────────────────────────────────
def _dir_entries(target: str) -> int:
    """目录的顶层条目数（花括号深度判定，与缩进无关）。"""
    return extract_dir(config.GAME / "common" / target).unique_entries


def _dir_txt_files(target: str) -> int:
    return count_files(config.GAME / "common" / target, ".txt")


def _dir_all_files(target: str) -> int:
    return count_files(config.GAME / "common" / target)


def _dir_subdirs(target: str) -> int:
    """子目录数。target 一律相对 ``common/``，空串表示 common 本身。"""
    base = config.GAME / "common" / target
    return sum(1 for p in base.iterdir() if p.is_dir()) if base.is_dir() else 0


def _defines_params(target: str) -> int:
    """defines 文件里某个命名空间块下的参数个数。

    ``target`` 形如 ``00_ai.txt:NAI``。
    """
    fname, _, ns = target.partition(":")
    pf = parse_cached(config.GAME / "common" / "defines" / fname)
    for a in pf.top_assignments:
        if a.key == ns and isinstance(a.value, Block):
            return len(list(a.value.assignments()))
    return -1


def _defines_blocks(_target: str) -> int:
    """defines 目录下的命名空间块总数。

    只数**命名空间块**（大写开头、非 ``@变量``、是块）。
    ``00_defines.txt`` 顶部有 22 个 ``@变量`` 定义，若一并计入
    会得到 97 而非正确的 75。
    """
    total = 0
    for f in (config.GAME / "common" / "defines").rglob("*.txt"):
        total += len(parse_cached(f).namespace_blocks())
    return total


def _defines_namespaces(_target: str) -> int:
    """defines 目录下去重的命名空间名数量。"""
    names: set[str] = set()
    for f in (config.GAME / "common" / "defines").rglob("*.txt"):
        names.update(a.key for a in parse_cached(f).namespace_blocks())
    return len(names)


def _block_param_kinds(blk: Block) -> tuple[int, int, int]:
    """命名空间块内的 ``(标量, 内联列表, 嵌套块)`` 三项计数。

    口径与 doc 05 §0.3 一一对应：
    * 标量 —— 深度 1 的 ``KEY = value``
    * 内联列表 —— 深度 1 的 ``KEY = { a b c }``，**同一行闭合**
    * 嵌套块 —— 深度 1 的 ``KEY = {``，**跨多行**

    区分后两者靠「块内的裸标量是否都落在同一行」：跨行的键值对一定是
    嵌套块，而只含裸标量且只占一行的才是内联列表。注释在词法阶段已剥离，
    所以不会把注释里的花括号算进来（那是早期 PowerShell 版最大的坑）。
    """
    scal = inline = nested = 0
    for a in blk.assignments():
        if not isinstance(a.value, Block):
            scal += 1
            continue
        scalars = list(a.value.scalars())
        if list(a.value.assignments()) or len({s.line for s in scalars}) > 1:
            nested += 1
        else:
            inline += 1
    return scal, inline, nested


def _defines_param_total(_target: str) -> int:
    """defines 全部命名空间块内的参数条目总数（标量 + 内联列表 + 嵌套块）。

    doc 05 最大的两张表（§2.1 文件总览、§2.2 逐块明细）都由这个口径汇总，
    此前只有「块数 75 / 命名空间 50」进了断言表，总数与逐块值无人看守 ——
    结果 1.14.3 给 ``NMilitary`` 加了 1 个参数、给 ``NDiplomacy`` 加了 39 个，
    文档里的 3434 却一直没动。这条就是为那类漂移加的。
    """
    total = 0
    for f in (config.GAME / "common" / "defines").rglob("*.txt"):
        for a in parse_cached(f).namespace_blocks():
            assert isinstance(a.value, Block)
            total += sum(_block_param_kinds(a.value))
    return total


def _defines_param_names(_target: str) -> int:
    """defines 全部命名空间块内**去重**后的参数名数量。"""
    names: set[str] = set()
    for f in (config.GAME / "common" / "defines").rglob("*.txt"):
        for a in parse_cached(f).namespace_blocks():
            assert isinstance(a.value, Block)
            names.update(x.key for x in a.value.assignments())
    return len(names)


def _prefix_in_mods(target: str) -> int:
    """某个功能前缀在全部 mod 中的使用次数。"""
    return aggregate_prefixes(analyse_all()).get(target, 0)


def _mods_prefix_total(_target: str) -> int:
    """全部 mod 使用功能前缀的总次数。"""
    return sum(aggregate_prefixes(analyse_all()).values())


def _vanilla_prefix_total(_target: str) -> int:
    """原版脚本使用功能前缀的**总次数**（实测应为 0）。

    这是本项目最核心的结论之一 —— ``INJECT:`` / ``REPLACE:`` 这套机制
    是引擎**专供 mod** 的。它曾被写进多篇文档却从未被任何断言核验：
    :func:`pdx.mods.vanilla_prefix_count` 早就写好了，也注册进了
    ``_CHECKS``，但**没有任何 claim 引用它**，于是 ``run_verify``
    长期报「37/37 全绿」，而这条结论实际上无人看守。
    """
    return sum(_vanilla_counter().values())


def _prefix_in_vanilla(target: str) -> int:
    """某个功能前缀在原版中的使用次数（实测应为 0）。

    ``vanilla_prefix_count()`` 要扫全棵 ``game/`` 树，而下面登记了 6 条
    分项断言 —— 不缓存的话就是 6 遍全树扫描。这里按「整份 counter」缓存一次。
    """
    return _vanilla_counter().get(target, 0)


@lru_cache(maxsize=1)
def _vanilla_counter() -> Counter:
    """原版前缀计数的**单次**结果，供 ``vanilla_prefix_total`` 与 6 条分项共享。"""
    return Counter(vanilla_prefix_count())


def _mods_total(_target: str) -> int:
    return len(analyse_all())


def _mods_files(_target: str) -> int:
    """全部 mod 的内容文件总数（``metadata.json`` 不计）。

    为什么要单列：doc 12 与索引页关于「23 个 mod 一共有多少文件」的说法
    长期停在 3,046，而实测是 4,777 —— 这个数字没进断言表，
    所以它漂了多久都没人知道。
    """
    return sum(m.files for m in analyse_all())


def _history_wrappers(_target: str) -> int:
    """history 目录下出现过的顶层包装块种类数。"""
    base = config.GAME / "common" / "history"
    names: set[str] = set()
    for f in base.rglob("*.txt"):
        names.update(parse_cached(f).top_keys)
    return len(names)


def _md_files(_target: str) -> int:
    """游戏自带的官方 .md 总数。

    必须跨三个内容根统计 —— 实测 ``game`` 树 91 篇 + ``jomini`` 树 1 篇
    = **92**。只扫 ``game/`` 会少算一篇
    （``jomini/common/audio_persistent_objects.md``）。
    """
    return sum(
        1
        for root in (config.GAME, config.JOMINI, config.CLAUSEWITZ)
        if root.is_dir()
        for _ in root.rglob("*.md")
    )


def _official_docs() -> list[tuple[str, int]]:
    """全部官方 ``.md``，``(键, 字节数)``；键形如 ``game/common/x/x.md``。

    键**带内容根前缀** —— 三个内容根下可能有同名相对路径，只写相对路径
    会互相覆盖、篇数悄悄变少（与 :func:`pdx.analyze.game_analysis` 同口径）。
    """
    out: list[tuple[str, int]] = []
    for name, root in (
        ("game", config.GAME),
        ("jomini", config.JOMINI),
        ("clausewitz", config.CLAUSEWITZ),
    ):
        if not root.is_dir():
            continue
        for p in root.rglob("*.md"):
            try:
                out.append((f"{name}/{p.relative_to(root).as_posix()}", p.stat().st_size))
            except OSError:
                continue
    return out


def _md_total_bytes(_target: str) -> int:
    """全部官方 ``.md`` 的字节总数。

    存在的理由：doc 07 的总字节数曾长期等于**镜像**（1.14.2）的值，
    而本体已随 1.14.3 增长 —— 只钉「篇数 92」是看不出这种漂移的。
    """
    return sum(size for _key, size in _official_docs())


def _md_max_bytes(_target: str) -> int:
    """最大的官方 ``.md`` 的字节数（实测为 ``treaty_articles.md``）。

    这条钉住的是**单篇文档的尺寸**。它踩过一次真坑：doc 07 把这个数写成
    镜像里的 25,364（1.14.2），而本体 1.14.3 已是 28,171 —— 该篇新增的
    ``scope:other_country`` / ``requirement_to_maintain`` 等规则镜像里没有，
    照镜像写条约 mod 会漏。内容一致性另由 ``tools/tests/test_docs_mirror.py``
    用 sha256 逐篇比对本体看守。
    """
    sizes = [size for _key, size in _official_docs()]
    return max(sizes) if sizes else 0


def _file_top_keys(target: str) -> int:
    """单个文件（相对 game/）的顶层键数。"""
    pf = parse_cached(config.GAME / target)
    return len(pf.top_keys)


def _dlc_count(_target: str) -> int:
    """``game/dlc/`` 下的 DLC 目录数。

    实测 **17**（编号 001–018，其中缺 ``dlc005``）。
    这个数字曾在 doc 01 与 doc 19 里被误写成 18，故单列断言钉住。
    """
    base = config.GAME / "dlc"
    return sum(1 for p in base.iterdir() if p.is_dir()) if base.is_dir() else 0


def _common_dir_count(_target: str) -> int:
    """``common/`` 下的子目录数。

    实测 **136**。注意不能靠「有哪些目录含有 .txt」来数 ——
    ``scripted_modifiers`` 目录下只有 ``.md`` 没有 ``.txt``，
    按后者口径会得到 135。
    """
    base = config.GAME / "common"
    return sum(1 for p in base.iterdir() if p.is_dir()) if base.is_dir() else 0


def _tree_path(target: str) -> Path:
    """把 ``"game/gfx"`` / ``"binaries"`` 这样的键解析成安装树里的真实路径。

    键以**内容根名**开头（``game`` / ``jomini`` / ``clausewitz``）或直接用
    安装根下的一级目录名。刻意不接受绝对路径：断言表里出现 ``C:\\...``
    就会把仓库钉死在一台机器上。
    """
    head, _, tail = target.partition("/")
    base = {
        "game": config.GAME,
        "jomini": config.JOMINI,
        "clausewitz": config.CLAUSEWITZ,
    }.get(head, config.ROOT / head)
    return base / tail if tail else base


def _tree_files(target: str) -> int:
    """安装树里某个目录的**递归文件数**。

    这条断言服务的对象在 doc 08：那份文档里 19 张表的数字现在由
    ``v3 tables`` 生成，但**章节标题**（``## 13. game\\gfx\\（19,162 文件 …）``）
    与 §17 汇总表仍是手写的 —— 生成器管不到散文，只能靠断言钉住。
    实测这些标题整整落后了一个游戏版本（``gfx`` 少了 1 个文件、
    ``binaries`` 少了 0.15 MB）。
    """
    path = _tree_path(target)
    return sum(1 for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


def _tree_dirs(target: str) -> int:
    """安装树里某个目录的**递归子目录数**（不含自身）。"""
    path = _tree_path(target)
    return sum(1 for p in path.rglob("*") if p.is_dir()) if path.is_dir() else 0


def _tree_subdirs(target: str) -> int:
    """安装树里某个目录的**直接**子目录数（不递归）。

    与 :func:`_tree_dirs` 是两个口径，doc 08 里两个都在用：
    「``game\\`` 下有 19 个一级目录」（直接）与「game 全树 1,986 个目录」（递归）。
    混用会让数字差两个数量级，所以分成两个 kind 而不是加个开关参数。
    """
    path = _tree_path(target)
    return sum(1 for p in path.iterdir() if p.is_dir()) if path.is_dir() else 0


def _tree_bytes(target: str) -> int:
    """安装树里某个目录的**递归字节数**。

    钉字节而不是 MB：MB 是展示格式（四舍五入到两位小数），
    换一种舍入规则就会假报；字节数是唯一没有歧义的那个量。
    """
    path = _tree_path(target)
    if not path.is_dir():
        return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


_CHECKS: dict[str, Callable[[str], object]] = {
    "dir_entries": _dir_entries,
    "dir_txt_files": _dir_txt_files,
    "dir_all_files": _dir_all_files,
    "dir_subdirs": _dir_subdirs,
    "defines_params": _defines_params,
    "defines_blocks": _defines_blocks,
    "defines_namespaces": _defines_namespaces,
    "defines_param_total": _defines_param_total,
    "defines_param_names": _defines_param_names,
    "prefix_in_mods": _prefix_in_mods,
    "prefix_in_vanilla": _prefix_in_vanilla,
    "mods_prefix_total": _mods_prefix_total,
    "vanilla_prefix_total": _vanilla_prefix_total,
    "mods_total": _mods_total,
    "mods_files": _mods_files,
    "history_wrappers": _history_wrappers,
    "md_files": _md_files,
    "md_total_bytes": _md_total_bytes,
    "md_max_bytes": _md_max_bytes,
    "file_top_keys": _file_top_keys,
    "dlc_count": _dlc_count,
    "common_dir_count": _common_dir_count,
    "tree_files": _tree_files,
    "tree_dirs": _tree_dirs,
    "tree_subdirs": _tree_subdirs,
    "tree_bytes": _tree_bytes,
}


# ── 断言注册表 ──────────────────────────────────────────────
#: 依赖外部数据的检查（需扫描全部 mod / 整个 game 树）较慢，
#: 由 ``slow`` 标记区分，便于快速模式下跳过。
SLOW_KINDS = frozenset(
    {
        "prefix_in_mods",
        "prefix_in_vanilla",
        "mods_prefix_total",
        "vanilla_prefix_total",
        "mods_total",
        "mods_files",
        "md_files",
        "md_total_bytes",
        "md_max_bytes",
    }
)


CLAIMS: list[Claim] = [
    # ── 环境 ────────────────────────────────────────────
    Claim(
        "env.common_dirs", "08-目录全量清单.md", "common 有 136 个子目录", "dir_subdirs", "", 136
    ),
    Claim(
        "env.dlc",
        "01-环境与版本.md",
        "game/dlc 下有 17 个 DLC",
        "dlc_count",
        "",
        17,
        "编号 001–018，缺 dlc005。doc 01 与 doc 19 早期误写为 18",
    ),
    Claim(
        "env.common_txt",
        "08-目录全量清单.md",
        "common 有 3026 个 .txt",
        "dir_txt_files",
        "",
        3026,
        "1.14.2 时为 3024，1.14.3 新增 2 个。注意 3101 是含 .md 的全部文件数",
    ),
    Claim(
        "env.common_all",
        "08-目录全量清单.md",
        "common 共 3101 个文件",
        "dir_all_files",
        "",
        3101,
        "1.14.2 时为 3099",
    ),
    Claim("env.md_total", "07-官方文档索引.md", "游戏自带 92 篇官方 .md", "md_files", "", 92),
    Claim(
        "docs.total_bytes",
        "07-官方文档索引.md",
        "92 篇官方 .md 总字节数",
        "md_total_bytes",
        "",
        232980,
        "1.14.2 时为 230,173（doc 07 曾长期写着这个镜像值）",
    ),
    Claim(
        "docs.max_bytes",
        "07-官方文档索引.md",
        "最大官方 .md treaty_articles.md 的字节数",
        "md_max_bytes",
        "",
        28171,
        "镜像曾停在 1.14.2 的 25,364 B / 604 行；本体 1.14.3 为 28,171 B / 648 行。"
        "内容一致性由 test_docs_mirror.py 用 sha256 逐篇比对本体看守",
    ),
    # ── 经济与生产（doc 14）────────────────────────────
    Claim(
        "eco.buildings",
        "14-经济与生产系统.md",
        "buildings 有 115 个",
        "dir_entries",
        "buildings",
        115,
    ),
    Claim(
        "eco.pm",
        "14-经济与生产系统.md",
        "production_methods 有 436 个",
        "dir_entries",
        "production_methods",
        436,
        "早期缩进法误得 433，漏掉 3 个含连字符的键",
    ),
    Claim(
        "eco.pmg",
        "14-经济与生产系统.md",
        "production_method_groups 有 197 个",
        "dir_entries",
        "production_method_groups",
        197,
    ),
    Claim(
        "eco.bg",
        "14-经济与生产系统.md",
        "building_groups 有 69 个",
        "dir_entries",
        "building_groups",
        69,
    ),
    Claim("eco.goods", "14-经济与生产系统.md", "goods 有 53 个", "dir_entries", "goods", 53),
    Claim(
        "eco.companies",
        "14-经济与生产系统.md",
        "company_types 有 221 个",
        "dir_entries",
        "company_types",
        221,
    ),
    # ── 政治人口（doc 15）──────────────────────────────
    Claim("pol.laws", "15-政治人口与社会.md", "laws 有 138 个", "dir_entries", "laws", 138),
    Claim(
        "pol.ig",
        "15-政治人口与社会.md",
        "interest_groups 有 8 个",
        "dir_entries",
        "interest_groups",
        8,
    ),
    Claim(
        "pol.ig_traits",
        "15-政治人口与社会.md",
        "interest_group_traits 有 99 个",
        "dir_entries",
        "interest_group_traits",
        99,
    ),
    Claim(
        "pol.ideologies",
        "15-政治人口与社会.md",
        "ideologies 有 172 个",
        "dir_entries",
        "ideologies",
        172,
    ),
    Claim(
        "pol.gov",
        "15-政治人口与社会.md",
        "government_types 有 444 个",
        "dir_entries",
        "government_types",
        444,
    ),
    Claim(
        "pol.cultures", "15-政治人口与社会.md", "cultures 有 317 个", "dir_entries", "cultures", 317
    ),
    Claim(
        "pol.disc",
        "15-政治人口与社会.md",
        "discrimination_traits 有 324 个",
        "dir_entries",
        "discrimination_traits",
        324,
    ),
    Claim(
        "pol.amend", "15-政治人口与社会.md", "amendments 有 67 个", "dir_entries", "amendments", 67
    ),
    # ── 角色科技（doc 17）──────────────────────────────
    Claim(
        "chr.templates",
        "17-角色科技与呈现.md",
        "character_templates 有 2011 个",
        "dir_entries",
        "character_templates",
        2011,
        "早期缩进法误得 1983，漏掉 27 个含连字符的键",
    ),
    Claim(
        "chr.traits",
        "17-角色科技与呈现.md",
        "character_traits 有 121 个",
        "dir_entries",
        "character_traits",
        121,
    ),
    Claim(
        "chr.tech", "17-角色科技与呈现.md", "technology 有 184 个", "dir_entries", "technology", 184
    ),
    Claim(
        "chr.concepts",
        "17-角色科技与呈现.md",
        "game_concepts 有 612 个",
        "dir_entries",
        "game_concepts",
        612,
    ),
    # ── 外交军事（doc 16）──────────────────────────────
    Claim(
        "dip.actions",
        "16-外交军事与地图.md",
        "diplomatic_actions 有 55 个",
        "dir_entries",
        "diplomatic_actions",
        55,
    ),
    Claim(
        "dip.treaty",
        "16-外交军事与地图.md",
        "treaty_articles 有 34 个",
        "dir_entries",
        "treaty_articles",
        34,
    ),
    Claim(
        "dip.wargoal",
        "16-外交军事与地图.md",
        "war_goal_types 有 39 个",
        "dir_entries",
        "war_goal_types",
        39,
    ),
    Claim(
        "dip.state_traits",
        "16-外交军事与地图.md",
        "state_traits 有 239 个",
        "dir_entries",
        "state_traits",
        239,
    ),
    Claim(
        "dip.strategic",
        "16-外交军事与地图.md",
        "strategic_regions 有 142 个",
        "dir_entries",
        "strategic_regions",
        142,
    ),
    Claim(
        "dip.ships",
        "16-外交军事与地图.md",
        "ship_modifications 有 259 个",
        "dir_entries",
        "ship_modifications",
        259,
    ),
    # ── defines / 修饰符（doc 05）──────────────────────
    Claim(
        "def.nai_count",
        "05-defines与修饰符.md",
        "NAI 有 1017 个参数",
        "defines_params",
        "00_ai.txt:NAI",
        1017,
        "1.14.2 时为 1013，1.14.3 增至 1017（+4）；文件 1307 行 → 1311 行",
    ),
    Claim(
        "def.blocks",
        "05-defines与修饰符.md",
        "defines 共 75 个顶层命名空间块",
        "defines_blocks",
        "",
        75,
    ),
    Claim(
        "def.namespaces",
        "05-defines与修饰符.md",
        "defines 共 50 个去重命名空间",
        "defines_namespaces",
        "",
        50,
    ),
    Claim(
        "def.param_total",
        "05-defines与修饰符.md",
        "defines 共 3488 个参数条目",
        "defines_param_total",
        "",
        3488,
        "标量 3313 + 内联列表 175 + 嵌套块 0。1.14.2 时为 3434；"
        "1.14.3 给 NMilitary +1、NDiplomacy +39，§2.1/§2.2 两张表已按 1.14.3 重算",
    ),
    Claim(
        "def.param_names",
        "05-defines与修饰符.md",
        "defines 共 3481 个去重参数名",
        "defines_param_names",
        "",
        3481,
        "1.14.2 时为 3427；跨块重复出现 7 次",
    ),
    Claim(
        "def.modtypes",
        "05-defines与修饰符.md",
        "modifier_type_definitions 有 2364 个",
        "dir_entries",
        "modifier_type_definitions",
        2364,
    ),
    Claim(
        "def.static",
        "05-defines与修饰符.md",
        "static_modifiers 有 6128 个",
        "dir_entries",
        "static_modifiers",
        6128,
        "早期缩进法误得 6121；实测 68/68 文件带 BOM 且存在缩进的顶层键",
    ),
    # ── 脚本系统（doc 04）──────────────────────────────
    Claim(
        "scr.on_actions",
        "04-脚本系统.md",
        "on_actions 有 264 个键",
        "dir_entries",
        "on_actions",
        264,
        "doc 04 早期记 263（其中 00_code_on_actions.txt 记 218，实为 219）。"
        "漏掉的是 on_diplo_play_overlord_protects_subject，位于该文件第 4321 行、缩进 0",
    ),
    # ── defines 各文件的顶层块数（doc 05 §2.1）────────────
    # 这 6 条用 `file_top_keys` 检查类型 —— 它早就注册好了却无人引用。
    # 钉的是 doc 05 §2.1「文件总览」表的「顶层块数」列，那一列此前
    # 完全没有看守，整张表因此落后了一个游戏版本（见 def.param_total）。
    Claim(
        "def.file_ai",
        "05-defines与修饰符.md",
        "00_ai.txt 有 1 个顶层块",
        "file_top_keys",
        "common/defines/00_ai.txt",
        1,
    ),
    Claim(
        "def.file_audio",
        "05-defines与修饰符.md",
        "00_audio.txt 有 1 个顶层块",
        "file_top_keys",
        "common/defines/00_audio.txt",
        1,
    ),
    Claim(
        "def.file_defines",
        "05-defines与修饰符.md",
        "00_defines.txt 有 41 个顶层键",
        "file_top_keys",
        "common/defines/00_defines.txt",
        41,
        "= 19 个命名空间块 + 22 个 `@变量`。本断言数的是**文件顶层键**（含 @变量），"
        "doc 05 §2.1 那一列写的是「顶层块数 19」；两个数都对，口径不同。"
        "命名空间块总数见 def.blocks（75）",
    ),
    Claim(
        "def.file_graphics",
        "05-defines与修饰符.md",
        "00_graphics.txt 有 19 个顶层块",
        "file_top_keys",
        "common/defines/00_graphics.txt",
        19,
    ),
    Claim(
        "def.file_interfaces",
        "05-defines与修饰符.md",
        "00_interfaces.txt 有 27 个顶层块",
        "file_top_keys",
        "common/defines/00_interfaces.txt",
        27,
        "27 个块里有 24 个叫 NGUI（同名重复块），如实保留",
    ),
    Claim(
        "def.file_shaders",
        "05-defines与修饰符.md",
        "00_shaders.txt 有 5 个顶层块",
        "file_top_keys",
        "common/defines/00_shaders.txt",
        5,
        "该文件第 1-2 行是 `NShadersCommon =` 与 `{` 分行，解析器必须能处理",
    ),
    # ── common 子目录数的**独立口径交叉验证** ──────────────
    Claim(
        "env.common_dirs_direct",
        "08-目录全量清单.md",
        "直接枚举 common 得到 136 个子目录",
        "common_dir_count",
        "",
        136,
        "与 env.common_dirs 是**两条独立实现**：那条走 extract_dir 的扫描口径，"
        "这条直接 iterdir。两者必须给出同一个数，否则说明扫描把某个目录吞了",
    ),
    # ── 六个前缀在**原版**的用量：逐个为 0（doc 02 §5.1.2）──
    # 此前只有总和为 0 被看守；分项为 0 才是 doc 02 那张表的完整主张。
    Claim(
        "pfx.vanilla_inject",
        "02-Mod结构与加载.md",
        "原版零使用 INJECT 前缀",
        "prefix_in_vanilla",
        "INJECT",
        0,
        "6 条分项共享一次全树扫描（_vanilla_counter 有 lru_cache）",
    ),
    Claim(
        "pfx.vanilla_replace",
        "02-Mod结构与加载.md",
        "原版零使用 REPLACE 前缀",
        "prefix_in_vanilla",
        "REPLACE",
        0,
    ),
    Claim(
        "pfx.vanilla_replace_or_create",
        "02-Mod结构与加载.md",
        "原版零使用 REPLACE_OR_CREATE 前缀",
        "prefix_in_vanilla",
        "REPLACE_OR_CREATE",
        0,
    ),
    Claim(
        "pfx.vanilla_try_replace",
        "02-Mod结构与加载.md",
        "原版零使用 TRY_REPLACE 前缀",
        "prefix_in_vanilla",
        "TRY_REPLACE",
        0,
    ),
    Claim(
        "pfx.vanilla_try_inject",
        "02-Mod结构与加载.md",
        "原版零使用 TRY_INJECT 前缀",
        "prefix_in_vanilla",
        "TRY_INJECT",
        0,
    ),
    Claim(
        "pfx.vanilla_inject_or_create",
        "02-Mod结构与加载.md",
        "原版零使用 INJECT_OR_CREATE 前缀",
        "prefix_in_vanilla",
        "INJECT_OR_CREATE",
        0,
    ),
    # ── history（doc 18）───────────────────────────────
    Claim(
        "hist.wrappers",
        "18-history初始状态系统.md",
        "history 有 22 种顶层包装块",
        "history_wrappers",
        "",
        22,
    ),
    # ── mod 分析（doc 12）──────────────────────────────
    Claim(
        "mod.total",
        "12-真实mod解剖与改造面地图.md",
        "订阅了 23 个 Workshop mod",
        "mods_total",
        "",
        23,
    ),
    Claim(
        "mod.files",
        "12-真实mod解剖与改造面地图.md",
        "23 个 Workshop mod 共 4777 个内容文件",
        "mods_files",
        "",
        4777,
        "不含各 mod 的 metadata.json（每 mod 1 个，共 23 个）；"
        "去重后为 4,750 个相对路径。doc 12 与索引页曾长期写作 3,046",
    ),
    # ── 引擎级功能前缀（doc 02 / doc 14，本项目最核心的结论之一）──
    #: 这条长期缺席：函数写好了、注册了，却没有 claim 引用它，
    #: 导致 run_verify 报「全绿」而该结论实际上无人看守。
    Claim(
        "pfx.vanilla_zero",
        "02-Mod结构与加载.md",
        "原版脚本零使用功能前缀（INJECT/REPLACE 等专供 mod）",
        "vanilla_prefix_total",
        "",
        0,
        "范围限定为 config.is_scriptable 认可的文件，与全量分析其余部分一致",
    ),
    Claim(
        "pfx.mods_total",
        "02-Mod结构与加载.md",
        "全部 mod 共使用 2737 次功能前缀",
        "mods_prefix_total",
        "",
        2737,
        "六个前缀之和见下面 6 条分项断言（2716 之外的旧注释把 REPLACE 与 "
        "TRY_REPLACE 写反过，已删掉那串手抄分项，改用断言本身表达）",
    ),
    # ── 六个前缀的**分项** ────────────────────────────────
    # 为什么要有分项：此前只有总数进了断言表，于是 doc 02 §5.1 那张分项表
    # 里的 1,115 / 737 / 439 长期过期（真值 1,116 / 740 / 440），
    # 而总数断言照样全绿 —— 漂移检测只认「锚点 + 数字」，抓不到表格里的分项。
    # 这 6 条同时把原先**注册了却无人引用**的 `prefix_in_mods` 检查用起来。
    Claim(
        "pfx.replace_or_create",
        "02-Mod结构与加载.md",
        "REPLACE_OR_CREATE 前缀在 mod 中使用 1116 次",
        "prefix_in_mods",
        "REPLACE_OR_CREATE",
        1116,
    ),
    Claim(
        "pfx.inject",
        "02-Mod结构与加载.md",
        "INJECT 前缀在 mod 中使用 740 次",
        "prefix_in_mods",
        "INJECT",
        740,
        "注意 `INJECT:` 与 `INJECT_OR_CREATE:` 是两个不同前缀，别用子串匹配",
    ),
    Claim(
        "pfx.try_inject",
        "02-Mod结构与加载.md",
        "TRY_INJECT 前缀在 mod 中使用 440 次",
        "prefix_in_mods",
        "TRY_INJECT",
        440,
    ),
    Claim(
        "pfx.try_replace",
        "02-Mod结构与加载.md",
        "TRY_REPLACE 前缀在 mod 中使用 221 次",
        "prefix_in_mods",
        "TRY_REPLACE",
        221,
    ),
    Claim(
        "pfx.replace",
        "02-Mod结构与加载.md",
        "REPLACE 前缀在 mod 中使用 174 次",
        "prefix_in_mods",
        "REPLACE",
        174,
    ),
    Claim(
        "pfx.inject_or_create",
        "02-Mod结构与加载.md",
        "INJECT_OR_CREATE 前缀在 mod 中使用 46 次",
        "prefix_in_mods",
        "INJECT_OR_CREATE",
        46,
    ),
    # ── doc 08 的安装树规模 ────────────────────────────────
    # 这些数在 doc 08 里出现在**章节标题**与 §17 汇总表里 —— 两处都是散文，
    # `v3 tables` 管不到。而它们实测漂过：`gfx` 19,162 → 19,163、
    # `binaries` 260.80 → 260.95 MB、`victoria3.exe` 97,128,568 → 97,292,920。
    # 断言描述里的英文标识符就是漂移扫描的**锚点**（标题行里的 `gfx` 等），
    # 所以 text 必须带上目录名，否则锚点抽不出来、这条断言等于没登记。
    Claim(
        "tree.game",
        "08-目录全量清单.md",
        "game 全树递归文件数（不含安装根下的松散文件）",
        "tree_files",
        "game",
        27723,
    ),
    Claim("tree.game_dirs", "08-目录全量清单.md", "game 全树子目录数", "tree_dirs", "game", 1986),
    Claim(
        "tree.game_bytes",
        "08-目录全量清单.md",
        "game 全树的字节总数（等价 17,055.76 MB）",
        "tree_bytes",
        "game",
        17884255692,
    ),
    Claim(
        "tree.binaries_files",
        "08-目录全量清单.md",
        "binaries 目录文件数",
        "tree_files",
        "binaries",
        40,
    ),
    Claim(
        "tree.binaries_bytes",
        "08-目录全量清单.md",
        "binaries 目录字节总数（等价 260.95 MB）",
        "tree_bytes",
        "binaries",
        273630477,
    ),
    Claim(
        "tree.clausewitz_files",
        "08-目录全量清单.md",
        "clausewitz 目录文件数",
        "tree_files",
        "clausewitz",
        753,
    ),
    Claim(
        "tree.jomini_files", "08-目录全量清单.md", "jomini 目录文件数", "tree_files", "jomini", 493
    ),
    Claim(
        "tree.launcher_files",
        "08-目录全量清单.md",
        "launcher 目录文件数",
        "tree_files",
        "launcher",
        12,
    ),
    Claim(
        "tree.psgd_files",
        "08-目录全量清单.md",
        "platform_specific_game_data 目录文件数",
        "tree_files",
        "platform_specific_game_data",
        2,
    ),
    Claim(
        "tree.gfx_files",
        "08-目录全量清单.md",
        "game/gfx 目录文件数",
        "tree_files",
        "game/gfx",
        19161,
    ),
    Claim(
        "tree.gfx_bytes",
        "08-目录全量清单.md",
        "game/gfx 目录字节总数（等价 9,690.00 MB）",
        "tree_bytes",
        "game/gfx",
        10160700313,
    ),
    Claim(
        "tree.events_files",
        "08-目录全量清单.md",
        "game/events 目录文件数",
        "tree_files",
        "game/events",
        328,
    ),
    Claim(
        "tree.localization_files",
        "08-目录全量清单.md",
        "game/localization 目录文件数",
        "tree_files",
        "game/localization",
        1877,
    ),
    Claim(
        "tree.gui_files", "08-目录全量清单.md", "game/gui 目录文件数", "tree_files", "game/gui", 207
    ),
    Claim(
        "tree.map_data_files",
        "08-目录全量清单.md",
        "game/map_data 目录文件数",
        "tree_files",
        "game/map_data",
        28,
    ),
    Claim(
        "tree.dlc_files",
        "08-目录全量清单.md",
        "game/dlc 目录文件数",
        "tree_files",
        "game/dlc",
        2747,
    ),
    Claim(
        "tree.game_level1",
        "08-目录全量清单.md",
        "game 一级目录数（直接子目录，不递归）",
        "tree_subdirs",
        "game",
        19,
    ),
    Claim(
        "tree.gfx_subdirs",
        "08-目录全量清单.md",
        "game/gfx 一级子目录数（doc 08 §13 那张表就是这么多行）",
        "tree_subdirs",
        "game/gfx",
        19,
    ),
]


# ── 执行 ────────────────────────────────────────────────────
def check(claim: Claim) -> CheckResult:
    fn = _CHECKS.get(claim.kind)
    if fn is None:
        return CheckResult(claim, None, False, f"未知的检查类型 {claim.kind!r}")
    try:
        actual = fn(claim.target)
    except Exception as exc:
        return CheckResult(claim, None, False, f"{type(exc).__name__}: {exc}")
    return CheckResult(claim, actual, actual == claim.expected)


def run_claims(
    claims: list[Claim] | None = None, *, include_slow: bool = True
) -> list[CheckResult]:
    """执行断言。``include_slow=False`` 时跳过需要全库扫描的检查。"""
    selected = claims if claims is not None else CLAIMS
    if not include_slow:
        selected = [c for c in selected if c.kind not in SLOW_KINDS]
    return [check(c) for c in selected]


def summarize(results: list[CheckResult]) -> dict[str, object]:
    passed = sum(1 for r in results if r.ok)
    by_doc = Counter(r.claim.doc for r in results if not r.ok)
    return {
        "总数": len(results),
        "通过": passed,
        "失败": len(results) - passed,
        "失败分布": dict(by_doc),
    }


# ── 文档一致性 ──────────────────────────────────────────────
#: 从断言描述里抽锚点词时，这些词太通用，不能当作定位依据。
#: 例如「common 有 136 个子目录」里的 ``common`` 在全库出现上千次，
#: 单靠它在文档里找「common + 136」会撞上无关的行。
_GENERIC_ANCHORS = frozenset(
    {"common", "mod", "mods", "defines", "history", "有", "个", "共", "全部"}
)

#: 锚点词的形态：拉丁字母/数字/下划线组成、长度 ≥3。
#: 刻意不收录中文词 —— 中文分词是另一个量级的问题，而本项目的
#: 数量断言几乎都以英文标识符开头（``on_actions`` / ``NAI`` / ``laws``）。
_ANCHOR_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


@dataclass(slots=True)
class DocDrift:
    """文档正文与断言表不一致的一处。"""

    claim: Claim
    doc: str
    line: int
    text: str
    found: int

    def describe(self) -> str:
        return (
            f"{self.doc}:{self.line} 写着 {self.found}，"
            f"断言表期望 {self.claim.expected} —— {self.text.strip()[:80]}"
        )


def _in_dotted_number(line: str, pos: int) -> bool:
    """``pos`` 处的数字是否属于一个点分数字串（``1.14.2`` / ``2.6`` / ``2,532.4``）。"""
    return any(m.start() <= pos < m.end() for m in _DOTTED_NUM_RE.finditer(line))


#: 漂移检测器的已知**度量口径错配**。
#:
#: 这些行的共同点是：同一行里并列了好几个不同口径的指标（条目数 / 文件数 /
#: 被引用次数），静态文本无法判断断言要的是哪一个。逐条实测确认过
#: 「文档其实是对的」，因此登记为已知项而不是改文档。
#:
#: 每一条都必须写清理由 —— 没有理由的豁免就是放任漂移。
#:
#: **键是 ``(断言 id, 文档里出现的数字)``，不是行号。** 早先用
#: ``文件名:行号`` 做键，结果给文档加两行版本提示就整份清单失效 ——
#: 那是清单设计的问题，不是文档的问题。断言 id 唯一，配上数字足以定位，
#: 且天然抗行号漂移。
#:
#: 放在**本模块**而不是测试文件里：``v3 verify`` 与测试都要用它来区分
#: 「真漂移」与「口径不同」，两边各维护一份必然会分叉。
KNOWN_METRIC_MIXUPS: dict[tuple[str, int], str] = {
    ("eco.goods", 52): "52 是 goods 作为字段被引用的次数，不是 goods 条目数（条目数为 53）",
    ("eco.goods", 51): "51 是另一处引用次数，与 goods 条目数无关",
    ("pol.cultures", 316): "316 描述的是某字段列表长度，与 cultures 目录条目数（317）不同口径",
    ("chr.concepts", 609): "609 是单个文件 00_game_concepts.txt 内的条目数，目录合计为 612",
    ("dip.treaty", 35): "35 是 treaty_articles 的**文件数**，条目数为 34；实测两者确实不同",
    ("dip.treaty", 33): "33 是某字段被使用的条目数，不是目录条目总数",
    ("dip.wargoal", 40): "40 是 war_goal_types 的**文件数**，条目数为 39；实测两者确实不同",
    ("dip.wargoal", 41): "41 指的是官方 .md 里 settings 列表的条目数，非游戏数据条目数",
}


def drift_key(d: DocDrift) -> tuple[str, int]:
    """漂移项的稳定标识：``(断言 id, 文档里出现的数字)``。

    刻意**不含行号** —— 给文档加两行版本提示就会让整份已知清单失效，
    那是清单设计的问题，不是文档的问题。
    """
    return (d.claim.id, d.found)


def unknown_doc_drift(docs_dir: Path | None = None) -> list[DocDrift]:
    """**未被登记为已知口径错配**的漂移 —— 也就是真正需要修的那些。

    :func:`find_doc_drift` 返回的是原始信号（含已知的口径不同），
    本函数在其上减掉 :data:`KNOWN_METRIC_MIXUPS`。``v3 verify`` 用这个判退出码，
    测试也用它做断言 —— 两边同一套判据。
    """
    return [d for d in find_doc_drift(docs_dir) if drift_key(d) not in KNOWN_METRIC_MIXUPS]


def anchors_of(claim: Claim) -> list[str]:
    """从断言描述里抽出可用于在文档中定位的锚点词。"""
    out: list[str] = []
    for token in _ANCHOR_RE.findall(claim.text):
        low = token.lower()
        if low in _GENERIC_ANCHORS or token in _GENERIC_ANCHORS:
            continue
        if token not in out:
            out.append(token)
    return out


#: 独立的数字。两侧不能紧邻字母、下划线或连字符，否则这些都会被当成数量：
#:   ``dlc018_ep2`` 里的 ``018``、``1.14.2`` 里的 ``14``（实测最大的误报源）
#:   ``19-game根级文件与工具链.md`` 里的 ``19`` —— 那是**文档编号**不是数量
#:   （索引页新增扫描后立刻撞上的一处误报）。
_STANDALONE_NUM_RE = re.compile(r"(?<![A-Za-z0-9_-])(\d[\d,]*)(?![A-Za-z0-9_-])")

#: **点分数字串**：版本号 ``1.14.2``、章节号 ``2.6``、小数 ``2,532.4``。
#:
#: 整段跳过，不做逐个数判断。理由有两条：
#:
#: * 章节号里的 ``2.6`` 会撞进小期望值（``interest_groups`` 期望 8）的容差 ——
#:   实测是一处稳定误报。
#: * 靠「紧邻点号就排除」写不干净：``17,172.9`` 里 ``\d[\d,]*`` 会回溯成 ``17``，
#:   于是 ``(?=\.\d)`` 失效、``17`` 照样被当成候选（实测踩过）。
#:   先按**整串**取跨度再排除，才不受回溯影响。
#:
#: 注意句末的 ``27,722.`` 不匹配（点号后面不是数字），应当保留 ——
#: 那是真数量。
_DOTTED_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)+")


def find_doc_drift(docs_dir: Path | None = None) -> list[DocDrift]:
    """扫描文档，找出「锚点词 + 数字」与断言表对不上的地方。

    这是把「文档里的数字会不会过期」变成可自动检查的关键一步。

    判定规则（四条都是被误报与漏报逼出来的）：

    1. 以断言描述里的**英文标识符**为锚点（``on_actions`` / ``NAI`` / ``laws``），
       只看锚点**在作用范围内**的行 —— 否则 264 这种数字在两千行文档里
       到处都可能出现，写错了也照样"通过"。
    2. 数字必须**独立成词**。``dlc018_*`` 里的 018、版本号 1.14.2 里的 14
       都不是数量。
    3. 同一行里量级接近期望值的**任意一个**独立数字都算候选（不是只取第一个）——
       表格行 ``| NAI | 1 | 1013 |`` 里第一个数字是文件数 1（实测漏报过 9 处）。
    4. **「作用范围」= 本行 + 本行所属章节的标题链**（见 :func:`_section_context`）。
       这是补第 4 条规则的原因：``05`` 的 ``### 3.3 全部 1013 个参数名`` 是
       **标题行本身**，标题里没有 ``NAI`` 这个词，于是它在旧规则下永远不被扫到 ——
       而它的上一级标题 ``## 3. NAI 命名空间块`` 里有。只看「本行含锚点」
       会漏掉"章节标题级"的漂移，那是文档里最显眼的位置。

    仍会有少量误报 —— 同一行里既有"条目数"又有"文件数"时，
    静态文本无法判断哪个是断言要的那个。因此这个函数是**给人看的线索**，
    不是自动改文档的依据。
    """
    docs_dir = docs_dir or config.DOCS
    out: list[DocDrift] = []
    if not docs_dir.is_dir():
        return out

    cache: dict[str, list[str]] = {}
    ctx_cache: dict[str, list[str]] = {}

    def lines_of(name: str) -> list[str]:
        if name not in cache:
            path = docs_dir / name
            cache[name] = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        return cache[name]

    def context_of(name: str) -> list[str]:
        """每一行的**章节标题链**（本行是标题时含本行）。"""
        if name not in ctx_cache:
            ctx_cache[name] = _section_context(lines_of(name))
        return ctx_cache[name]

    for claim in CLAIMS:
        if not isinstance(claim.expected, int) or not claim.expected:
            continue
        if claim.id in TEXT_SCAN_EXEMPT:
            continue
        # 出处文档 + **索引页**。
        #
        # 索引页（docs/README.md）此前不在扫描范围内，于是它成了盲区：
        # 实测正文改对之后，索引页里仍然写着 263 / 1013 —— 而那正是
        # 读者第一眼看到的地方。
        for doc_name in (claim.doc, *_ALWAYS_SCANNED):
            lines = lines_of(doc_name)
            if not lines:
                continue

            anchors = anchors_of(claim)
            if not anchors:
                continue
            context = context_of(doc_name)
            tolerance = max(2, claim.expected // 100)
            expected_str = f"{claim.expected:,}"

            for n, line in enumerate(lines, start=1):
                # 锚点在本行，或在本行所属章节的标题链里（见规则 4）
                if not any(a in line or a in context[n - 1] for a in anchors):
                    continue
                # 期望值已经出现在这一行 —— 说明文档是对的
                if expected_str in line or str(claim.expected) in line:
                    continue
                # 找出这一行里量级接近期望值的独立数字；有就说明多半是漂移。
                #
                # 不能只看锚点后的**第一个**数字：表格行 `| NAI | 1 | 1013 |`
                # 里第一个数字是文件数 1，真正的参数数在后面（实测漏报过 9 处）。
                for hit in _STANDALONE_NUM_RE.finditer(line):
                    if _in_dotted_number(line, hit.start()):
                        continue
                    value = int(hit.group(1).replace(",", ""))
                    if value in _COMMON_NOISE:
                        continue
                    if 0 < abs(value - claim.expected) <= tolerance:
                        out.append(DocDrift(claim, doc_name, n, line, value))
                        break
    return out


#: **每个断言都要额外扫一遍**的文档。
#:
#: ``docs/README.md`` 是索引页 —— 读者第一眼看到的地方，也是此前
#: 漂移扫描的盲区：正文改对之后它仍写着旧值（实测 263 / 1013 两处）。
_ALWAYS_SCANNED: tuple[str, ...] = ("README.md",)

#: ATX 标题：``## 3. `NAI` 命名空间块``。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


#: **不参与「文档正文数字漂移」扫描**的断言。
#:
#: 与「抽不出锚点」是**两个不同的原因**，所以分开列：
#:
#: 这里的每一条**都有锚点**，但锚点是从文件名碎片里抽出来的
#: （``txt`` / ``shaders`` / ``graphics``），这些词在 doc 05 里满篇都是，
#: 而期望值又很小（1、5、19），容差 ±2 会命中几十上百处无关数字 ——
#: 实测一次就报了 222 处，把真信号彻底淹没。
#:
#: 它们的证据在**由工具生成的表格**里而不是散文里，因此看守交给
#: ``tools/tests/test_defines_tables.py``：那个测试直接比对
#: 「文档现值 vs `pdx.defines.doc_table_rows()` 的输出」，比文本扫描强得多
#: （文本扫描只能发现「某个数字不对」，那个测试能发现**哪一行**不对）。
TEXT_SCAN_EXEMPT: dict[str, str] = {
    "def.file_ai": "锚点退化成 'txt'，doc 05 里到处是；由 test_defines_tables.py 看守",
    "def.file_audio": "同上",
    "def.file_defines": "同上",
    "def.file_graphics": "锚点 'graphics' 在 doc 05 里出现几十次，期望值 19 → 误报 16 处",
    "def.file_interfaces": "同上",
    "def.file_shaders": "锚点 'shaders' 在 doc 05 里出现上百次，期望值 5 → 误报 89 处",
    # 这两条是 doc 08 的「一级目录数」。锚点只能是 `game` / `gfx` —— 而 doc 08
    # 是逐目录清单，`game` 在它里面出现上百次，期望值又只有 19，容差 ±2 于是
    # 撞上「占 `game\` 全树 17 GB」里的 17（实测 2 处稳定误报）。
    # 它们要钉的那个数字（§17 的「一级目录数 19」）**由生成表看守**：
    # §8 与 §13 的表各有 19 行，行数就是目录数，`v3 tables` 每次都会核对。
    "tree.game_level1": "锚点 'game' 在 doc 08 里太通用（实测误报 2 处）；由 §8 生成表的行数看守",
    "tree.gfx_subdirs": "同上，锚点 'gfx'；由 §13 生成表的行数看守",
}


def _section_context(lines: list[str]) -> list[str]:
    """每行的**锚点作用文本**：正文行就是本行，标题行额外附带各级祖先标题。

    为什么需要它：``05-defines与修饰符.md`` 里
    ``### 3.3 全部 1013 个参数名`` 是**标题行本身**，标题里没有 ``NAI``，
    于是「本行必须含锚点」的旧规则永远扫不到它 —— 而它的上一级标题
    ``## 3. `NAI` 命名空间块`` 里有。这类「章节标题级漂移」正好落在
    读者最先看到的位置，却是检测器的盲区（实测潜伏了很久）。

    为什么**只**放宽标题行，不放宽正文行：试过让整节都继承锚点，
    命中数从 12 涨到 36，绝大多数是「同一节里另外一个指标的同行数字」
    （``production_method_groups`` 那一节里的 ``| texture | 196 |``）。
    检测器的价值全在**精确**上 —— 一次误报就要人去人工排除，
    报得多了就没人看了。标题行数量少、语义强，放宽它是安全的。
    """
    out: list[str] = []
    #: 当前生效的各级标题，下标 = 层级 - 1
    stack: list[str] = []
    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            del stack[level - 1 :]
            while len(stack) < level - 1:
                stack.append("")
            stack.append(m.group(2))
            out.append(f"{line} {' '.join(stack)}")
        else:
            out.append(line)
    return out


#: 这些数字在文档里作为版本号、年份、行号等出现，与数量断言无关。
_COMMON_NOISE = frozenset({1142, 1143, 2023, 2024, 2025, 2026})


# ── 产物核验 ────────────────────────────────────────────────
def _prod_dir_entries(game: dict, _mods: dict, _cross: dict, target: str) -> object:
    return game.get("common", {}).get(target, {}).get("顶层条目数")


def _prod_common_dirs(game: dict, _mods: dict, _cross: dict, _target: str) -> object:
    return game.get("概览", {}).get("common 目录数")


def _prod_dlc(game: dict, _mods: dict, _cross: dict, _target: str) -> object:
    return game.get("概览", {}).get("DLC")


def _prod_md(game: dict, _mods: dict, _cross: dict, _target: str) -> object:
    return game.get("概览", {}).get("官方md")


def _prod_md_sizes(game: dict, _mods: dict, _cross: dict, _target: str) -> dict:
    """产物里的逐篇官方 ``.md`` 字节表。"""
    return game.get("官方文档") or {}


def _prod_md_total_bytes(game: dict, _mods: dict, _cross: dict, target: str) -> object:
    sizes = _prod_md_sizes(game, _mods, _cross, target)
    return sum(sizes.values()) if sizes else None


def _prod_md_max_bytes(game: dict, _mods: dict, _cross: dict, target: str) -> object:
    sizes = _prod_md_sizes(game, _mods, _cross, target)
    return max(sizes.values()) if sizes else None


def _prod_vanilla_prefix(game: dict, _mods: dict, _cross: dict, _target: str) -> object:
    return game.get("概览", {}).get("原版前缀使用")


def _prod_mods_total(_game: dict, mods: dict, _cross: dict, _target: str) -> object:
    return mods.get("概览", {}).get("mod 数")


def _prod_mods_files(_game: dict, mods: dict, _cross: dict, _target: str) -> object:
    return mods.get("概览", {}).get("文件总计")


#: 断言类型 → 从**已落盘的产物**里取值。
#:
#: 为什么要有这一层：``CLAIMS`` 检查的是「游戏里到底有多少」，
#: 这里检查的是「分析产物有没有把它写对」。两者是不同的问题，
#: 但**必须共用同一份期望值**。
#:
#: 历史上 ``tools/check_outputs.py`` 自己维护了一套写死的期望值，
#: 结果它的 ``on_actions = 263`` 与 ``CLAIMS`` 里的 264 长期冲突，
#: 而且因为它跑在 pytest 管辖之外，谁也没发现。
#: 现在两个检查都从 ``CLAIMS`` 取数，冲突在结构上不可能再出现。
#:
#: 用具名函数而不是 lambda：一来 linter 不会抱怨「未使用的形参」，
#: 二来这四个形参的统一签名本身就是「产物取值器」这个协议的一部分。
_PRODUCT_GETTERS: dict[str, Callable[[dict, dict, dict, str], object]] = {
    "dir_entries": _prod_dir_entries,
    "common_dir_count": _prod_common_dirs,
    "dlc_count": _prod_dlc,
    "md_files": _prod_md,
    "md_total_bytes": _prod_md_total_bytes,
    "md_max_bytes": _prod_md_max_bytes,
    "prefix_in_vanilla": _prod_vanilla_prefix,
    "mods_total": _prod_mods_total,
    "mods_files": _prod_mods_files,
}


def product_kinds() -> frozenset[str]:
    """能被产物核验覆盖的断言类型。"""
    return frozenset(_PRODUCT_GETTERS)


# ── 无游戏环境下的核验：用**入库的精简快照**当真值 ──────────
#: 断言类型 → 从快照的某个域里取值。
#:
#: 为什么需要这一层：`run_claims` 全部要读游戏本体，而 **CI 上没有游戏**，
#: 于是那 63 条断言在 CI 上一条都不跑（`test_verify.py` 被自动跳过）。
#: 而入库的精简快照（`tools/out/snapshots/*.compact.json`，约 4.9 MiB）
#: 里带着 common 各目录的条目名、defines 命名空间、DLC 清单 —— 足够核验其中一批。
#:
#: ⚠️ **它证明什么、不证明什么**（写清楚，否则又是自我安慰）：
#:
#: * 证明：断言注册表**仍然与当时记录的真值一致**。有人改了 `CLAIMS`
#:   却没同步快照，这里立刻会响 —— 这正是 CI 该管的事。
#: * **不**证明：游戏里「现在」还是这个数。那要读游戏本体，是 `run_claims`
#:   的职责，只有装了游戏的机器才能做。
#:
#: 两者合起来才完整：本地跑 `v3 verify`（真值来自游戏），
#: CI 跑 `v3 verify --from-snapshot`（真值来自入库快照）。


def _snap_dir_entries(snap: Snapshot, target: str) -> object:
    """``common/<target>`` 的顶层条目数 = 该目录在快照里的条目名个数。"""
    entries = snap.sections.get("common_entries", {}).get(target)
    return len(entries) if entries is not None else None


def _snap_common_dirs(snap: Snapshot, _target: str) -> object:
    """``common/`` 的子目录数 = 快照里出现的目录数。"""
    section = snap.sections.get("common_entries")
    return len(section) if section is not None else None


def _snap_dlc(snap: Snapshot, _target: str) -> object:
    section = snap.sections.get("dlc")
    return len(section) if section is not None else None


def _snap_game_defines(snap: Snapshot) -> dict[str, list[str]]:
    """只取 **game 层**的 defines 命名空间。

    快照的 ``defines`` 域刻意把 game 与 jomini 两层都收进来（键形如
    ``game/NAI``、``jomini/NAI``），而 ``def.*`` 系列断言的口径是
    ``game/common/defines`` 一个目录 —— 不过滤就会把 jomini 的
    13 个命名空间、79 个参数算进去（实测 63 vs 50、3567 vs 3488）。
    """
    section = snap.sections.get("defines") or {}
    return {k: v for k, v in section.items() if k.startswith("game/")}


def _snap_defines_param_total(snap: Snapshot, _target: str) -> object:
    """defines 参数总数。快照按「层/命名空间」合并，但合并不改变参数总数。"""
    section = _snap_game_defines(snap)
    return sum(len(v) for v in section.values()) if section else None


def _snap_defines_param_names(snap: Snapshot, _target: str) -> object:
    """去重后的参数名数 —— 跨命名空间的并集。"""
    section = _snap_game_defines(snap)
    if not section:
        return None
    names: set[str] = set()
    for params in section.values():
        names.update(params)
    return len(names)


def _snap_defines_namespaces(snap: Snapshot, _target: str) -> object:
    """去重命名空间数 —— 键形如 ``game/NAI``，去掉层前缀再取并集。"""
    section = _snap_game_defines(snap)
    if not section:
        return None
    return len({k.partition("/")[2] for k in section})


_SNAPSHOT_GETTERS: dict[str, Callable[[Snapshot, str], object]] = {
    "dir_entries": _snap_dir_entries,
    "dir_subdirs": _snap_common_dirs,
    "common_dir_count": _snap_common_dirs,
    "dlc_count": _snap_dlc,
    "defines_param_total": _snap_defines_param_total,
    "defines_param_names": _snap_defines_param_names,
    "defines_namespaces": _snap_defines_namespaces,
}


def snapshot_kinds() -> frozenset[str]:
    """能被入库快照核验覆盖的断言类型。"""
    return frozenset(_SNAPSHOT_GETTERS)


def latest_compact_snapshot() -> Snapshot | None:
    """仓库里最新的一份**精简快照**；一份都没有时返回 ``None``。

    只认 ``*.compact.json`` —— 完整快照不入库，而且体积大一个数量级。
    """
    if not SNAPSHOT_DIR.is_dir():
        return None
    paths = sorted(SNAPSHOT_DIR.glob("*.compact.json"))
    if not paths:
        return None
    try:
        return Snapshot.load(paths[-1])
    except (OSError, ValueError):
        return None


def verify_from_snapshot(
    snap: Snapshot | None = None, claims: list[Claim] | None = None
) -> list[CheckResult]:
    """用入库的精简快照核验能被它覆盖的那部分断言。

    覆盖不到的断言类型**不出现在结果里**（用 :func:`snapshot_kinds` 查范围），
    而不是报成失败 —— 这条路的定位就是「无游戏时能查多少查多少」。
    """
    snap = snap or latest_compact_snapshot()
    if snap is None:
        return []
    out: list[CheckResult] = []
    for claim in claims if claims is not None else CLAIMS:
        getter = _SNAPSHOT_GETTERS.get(claim.kind)
        if getter is None:
            continue
        try:
            actual = getter(snap, claim.target)
        except (KeyError, TypeError, AttributeError) as exc:
            out.append(CheckResult(claim, None, False, f"{type(exc).__name__}: {exc}"))
            continue
        if actual is None:
            out.append(CheckResult(claim, None, False, "快照里没有对应域或条目"))
            continue
        out.append(CheckResult(claim, actual, actual == claim.expected))
    return out


def verify_products(
    game: dict, mods: dict, cross: dict, claims: list[Claim] | None = None
) -> list[CheckResult]:
    """核验已落盘的分析产物是否与断言注册表一致。

    只检查 ``_PRODUCT_GETTERS`` 里有映射的类型；其余类型会以 ``error``
    标注为「产物中没有对应字段」，而**不是假装通过** ——
    静默跳过是让检查表腐烂的最快方式。
    """
    out: list[CheckResult] = []
    for claim in claims if claims is not None else CLAIMS:
        getter = _PRODUCT_GETTERS.get(claim.kind)
        if getter is None:
            out.append(CheckResult(claim, None, False, f"产物中没有对应字段（{claim.kind}）"))
            continue
        try:
            actual = getter(game, mods, cross, claim.target)
        except (KeyError, TypeError, AttributeError) as exc:
            out.append(CheckResult(claim, None, False, f"{type(exc).__name__}: {exc}"))
            continue
        if actual is None:
            out.append(CheckResult(claim, None, False, "产物中该字段缺失"))
            continue
        out.append(CheckResult(claim, actual, actual == claim.expected))
    return out


# ── 覆盖率扫描 ──────────────────────────────────────────────
_NUM_RE = re.compile(r"\*\*([\d,]{3,})\*\*|(?<![\d,])([\d]{4,})(?![\d,])")


def find_unregistered_claims(
    docs_dir: Path | None = None, known_values: set[int] | None = None
) -> dict[str, list[tuple[int, str]]]:
    """扫描文档，找出**已在断言表中登记过数字之外**的数量断言。

    用于防止文档新增了断言却忘记登记。返回 ``文档名 -> [(行号, 原文)]``。
    这个扫描刻意宽松（宁可多报也不要漏报），人工复核后再决定是否登记。
    """
    docs_dir = docs_dir or config.DOCS
    known = known_values
    if known is None:
        known = {int(c.expected) for c in CLAIMS if isinstance(c.expected, int)}

    out: dict[str, list[tuple[int, str]]] = {}
    if not docs_dir.is_dir():
        return out

    for doc in sorted(docs_dir.glob("*.md")):
        hits: list[tuple[int, str]] = []
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
            for m in _NUM_RE.finditer(line):
                raw = (m.group(1) or m.group(2)).replace(",", "")
                try:
                    val = int(raw)
                except ValueError:
                    continue
                if val in known:
                    continue
                hits.append((n, line.strip()[:120]))
                break
        if hits:
            out[doc.name] = hits
    return out
