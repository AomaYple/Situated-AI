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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config
from .extract import extract_dir
from .mods import aggregate_prefixes, analyse_all, vanilla_prefix_count
from .cache import parse_cached
from .parser import PREFIXES
from .scan import count_files


# ── 数据结构 ────────────────────────────────────────────────
@dataclass(slots=True)
class Claim:
    """一条待核对的断言。"""

    id: str                     # 唯一标识
    doc: str                    # 出处文档（文件名）
    text: str                   # 断言内容的人类可读描述
    kind: str                   # 检查类型
    target: str                 # 目标（目录名 / 文件 / 命名空间等）
    expected: object            # 期望值
    note: str = ""              # 补充说明（口径等）


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
        if a.key == ns and a.is_block:
            return len(list(a.value.assignments()))
    return -1


def _defines_blocks(target: str) -> int:
    """defines 目录下的命名空间块总数。

    只数**命名空间块**（大写开头、非 ``@变量``、是块）。
    ``00_defines.txt`` 顶部有 22 个 ``@变量`` 定义，若一并计入
    会得到 97 而非正确的 75。
    """
    total = 0
    for f in (config.GAME / "common" / "defines").rglob("*.txt"):
        total += len(parse_cached(f).namespace_blocks())
    return total


def _defines_namespaces(target: str) -> int:
    """defines 目录下去重的命名空间名数量。"""
    names: set[str] = set()
    for f in (config.GAME / "common" / "defines").rglob("*.txt"):
        names.update(a.key for a in parse_cached(f).namespace_blocks())
    return len(names)


def _prefix_in_mods(target: str) -> int:
    """某个功能前缀在全部 mod 中的使用次数。"""
    return aggregate_prefixes(analyse_all()).get(target, 0)


def _prefix_in_vanilla(target: str) -> int:
    """某个功能前缀在原版中的使用次数（实测应为 0）。"""
    return vanilla_prefix_count().get(target, 0)


def _mods_total(target: str) -> int:
    return len(analyse_all())


def _history_wrappers(target: str) -> int:
    """history 目录下出现过的顶层包装块种类数。"""
    base = config.GAME / "common" / "history"
    names: set[str] = set()
    for f in base.rglob("*.txt"):
        names.update(parse_cached(f).top_keys)
    return len(names)


def _md_files(target: str) -> int:
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


def _file_top_keys(target: str) -> int:
    """单个文件（相对 game/）的顶层键数。"""
    pf = parse_cached(config.GAME / target)
    return len(pf.top_keys)


def _dlc_count(target: str) -> int:
    """``game/dlc/`` 下的 DLC 目录数。

    实测 **17**（编号 001–018，其中缺 ``dlc005``）。
    这个数字曾在 doc 01 与 doc 19 里被误写成 18，故单列断言钉住。
    """
    base = config.GAME / "dlc"
    return sum(1 for p in base.iterdir() if p.is_dir()) if base.is_dir() else 0


def _common_dir_count(target: str) -> int:
    """``common/`` 下的子目录数。

    实测 **136**。注意不能靠「有哪些目录含有 .txt」来数 ——
    ``scripted_modifiers`` 目录下只有 ``.md`` 没有 ``.txt``，
    按后者口径会得到 135。
    """
    base = config.GAME / "common"
    return sum(1 for p in base.iterdir() if p.is_dir()) if base.is_dir() else 0


_CHECKS: dict[str, Callable[[str], object]] = {
    "dir_entries": _dir_entries,
    "dir_txt_files": _dir_txt_files,
    "dir_all_files": _dir_all_files,
    "dir_subdirs": _dir_subdirs,
    "defines_params": _defines_params,
    "defines_blocks": _defines_blocks,
    "defines_namespaces": _defines_namespaces,
    "prefix_in_mods": _prefix_in_mods,
    "prefix_in_vanilla": _prefix_in_vanilla,
    "mods_total": _mods_total,
    "history_wrappers": _history_wrappers,
    "md_files": _md_files,
    "file_top_keys": _file_top_keys,
    "dlc_count": _dlc_count,
    "common_dir_count": _common_dir_count,
}


# ── 断言注册表 ──────────────────────────────────────────────
#: 依赖外部数据的检查（需扫描全部 mod / 整个 game 树）较慢，
#: 由 ``slow`` 标记区分，便于快速模式下跳过。
SLOW_KINDS = frozenset({"prefix_in_mods", "prefix_in_vanilla", "mods_total", "md_files"})


CLAIMS: list[Claim] = [
    # ── 环境 ────────────────────────────────────────────
    Claim("env.common_dirs", "08-目录全量清单.md", "common 有 136 个子目录",
          "dir_subdirs", "", 136),
    Claim("env.dlc", "01-环境与版本.md", "game/dlc 下有 17 个 DLC",
          "dlc_count", "", 17,
          "编号 001–018，缺 dlc005。doc 01 与 doc 19 早期误写为 18"),
    Claim("env.common_txt", "08-目录全量清单.md", "common 有 3026 个 .txt",
          "dir_txt_files", "", 3026,
          "1.14.2 时为 3024，1.14.3 新增 2 个。注意 3101 是含 .md 的全部文件数"),
    Claim("env.common_all", "08-目录全量清单.md", "common 共 3101 个文件",
          "dir_all_files", "", 3101, "1.14.2 时为 3099"),
    Claim("env.md_total", "07-官方文档索引.md", "游戏自带 92 篇官方 .md",
          "md_files", "", 92),

    # ── 经济与生产（doc 14）────────────────────────────
    Claim("eco.buildings", "14-经济与生产系统.md", "buildings 有 115 个",
          "dir_entries", "buildings", 115),
    Claim("eco.pm", "14-经济与生产系统.md", "production_methods 有 436 个",
          "dir_entries", "production_methods", 436,
          "早期缩进法误得 433，漏掉 3 个含连字符的键"),
    Claim("eco.pmg", "14-经济与生产系统.md", "production_method_groups 有 197 个",
          "dir_entries", "production_method_groups", 197),
    Claim("eco.bg", "14-经济与生产系统.md", "building_groups 有 69 个",
          "dir_entries", "building_groups", 69),
    Claim("eco.goods", "14-经济与生产系统.md", "goods 有 53 个",
          "dir_entries", "goods", 53),
    Claim("eco.companies", "14-经济与生产系统.md", "company_types 有 221 个",
          "dir_entries", "company_types", 221),

    # ── 政治人口（doc 15）──────────────────────────────
    Claim("pol.laws", "15-政治人口与社会.md", "laws 有 138 个",
          "dir_entries", "laws", 138),
    Claim("pol.ig", "15-政治人口与社会.md", "interest_groups 有 8 个",
          "dir_entries", "interest_groups", 8),
    Claim("pol.ig_traits", "15-政治人口与社会.md", "interest_group_traits 有 99 个",
          "dir_entries", "interest_group_traits", 99),
    Claim("pol.ideologies", "15-政治人口与社会.md", "ideologies 有 172 个",
          "dir_entries", "ideologies", 172),
    Claim("pol.gov", "15-政治人口与社会.md", "government_types 有 444 个",
          "dir_entries", "government_types", 444),
    Claim("pol.cultures", "15-政治人口与社会.md", "cultures 有 317 个",
          "dir_entries", "cultures", 317),
    Claim("pol.disc", "15-政治人口与社会.md", "discrimination_traits 有 324 个",
          "dir_entries", "discrimination_traits", 324),
    Claim("pol.amend", "15-政治人口与社会.md", "amendments 有 67 个",
          "dir_entries", "amendments", 67),

    # ── 角色科技（doc 17）──────────────────────────────
    Claim("chr.templates", "17-角色科技与呈现.md", "character_templates 有 2011 个",
          "dir_entries", "character_templates", 2011,
          "早期缩进法误得 1983，漏掉 27 个含连字符的键"),
    Claim("chr.traits", "17-角色科技与呈现.md", "character_traits 有 121 个",
          "dir_entries", "character_traits", 121),
    Claim("chr.tech", "17-角色科技与呈现.md", "technology 有 184 个",
          "dir_entries", "technology", 184),
    Claim("chr.concepts", "17-角色科技与呈现.md", "game_concepts 有 612 个",
          "dir_entries", "game_concepts", 612),

    # ── 外交军事（doc 16）──────────────────────────────
    Claim("dip.actions", "16-外交军事与地图.md", "diplomatic_actions 有 55 个",
          "dir_entries", "diplomatic_actions", 55),
    Claim("dip.treaty", "16-外交军事与地图.md", "treaty_articles 有 34 个",
          "dir_entries", "treaty_articles", 34),
    Claim("dip.wargoal", "16-外交军事与地图.md", "war_goal_types 有 39 个",
          "dir_entries", "war_goal_types", 39),
    Claim("dip.state_traits", "16-外交军事与地图.md", "state_traits 有 239 个",
          "dir_entries", "state_traits", 239),
    Claim("dip.strategic", "16-外交军事与地图.md", "strategic_regions 有 142 个",
          "dir_entries", "strategic_regions", 142),
    Claim("dip.ships", "16-外交军事与地图.md", "ship_modifications 有 259 个",
          "dir_entries", "ship_modifications", 259),

    # ── defines / 修饰符（doc 05）──────────────────────
    Claim("def.nai_count", "05-defines与修饰符.md",
          "NAI 有 1017 个参数", "defines_params", "00_ai.txt:NAI", 1017,
          "1.14.2 时为 1013，1.14.3 增至 1017（+4）；文件 1307 行 → 1311 行"),
    Claim("def.blocks", "05-defines与修饰符.md", "defines 共 75 个顶层命名空间块",
          "defines_blocks", "", 75),
    Claim("def.namespaces", "05-defines与修饰符.md", "defines 共 50 个去重命名空间",
          "defines_namespaces", "", 50),
    Claim("def.modtypes", "05-defines与修饰符.md", "modifier_type_definitions 有 2364 个",
          "dir_entries", "modifier_type_definitions", 2364),
    Claim("def.static", "05-defines与修饰符.md", "static_modifiers 有 6128 个",
          "dir_entries", "static_modifiers", 6128,
          "早期缩进法误得 6121；实测 68/68 文件带 BOM 且存在缩进的顶层键"),

    # ── 脚本系统（doc 04）──────────────────────────────
    Claim("scr.on_actions", "04-脚本系统.md", "on_actions 有 264 个键",
          "dir_entries", "on_actions", 264,
          "doc 04 早期记 263（其中 00_code_on_actions.txt 记 218，实为 219）。"
          "漏掉的是 on_diplo_play_overlord_protects_subject，位于该文件第 4321 行、缩进 0"),

    # ── history（doc 18）───────────────────────────────
    Claim("hist.wrappers", "18-history初始状态系统.md",
          "history 有 22 种顶层包装块", "history_wrappers", "", 22),

    # ── mod 分析（doc 12）──────────────────────────────
    Claim("mod.total", "12-真实mod解剖与改造面地图.md", "订阅了 23 个 Workshop mod",
          "mods_total", "", 23),
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
        for n, line in enumerate(
            doc.read_text(encoding="utf-8").splitlines(), start=1
        ):
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
