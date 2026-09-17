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
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .extract import extract_dir
from .model import Block
from .mods import aggregate_prefixes, analyse_all, vanilla_prefix_count
from .scan import count_files

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


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
    return sum(vanilla_prefix_count().values())


def _prefix_in_vanilla(target: str) -> int:
    """某个功能前缀在原版中的使用次数（实测应为 0）。"""
    return vanilla_prefix_count().get(target, 0)


def _mods_total(_target: str) -> int:
    return len(analyse_all())


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
    "mods_prefix_total": _mods_prefix_total,
    "vanilla_prefix_total": _vanilla_prefix_total,
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
SLOW_KINDS = frozenset(
    {
        "prefix_in_mods",
        "prefix_in_vanilla",
        "mods_prefix_total",
        "vanilla_prefix_total",
        "mods_total",
        "md_files",
    }
)


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

    # ── 引擎级功能前缀（doc 02 / doc 14，本项目最核心的结论之一）──
    #: 这条长期缺席：函数写好了、注册了，却没有 claim 引用它，
    #: 导致 run_verify 报「全绿」而该结论实际上无人看守。
    Claim("pfx.vanilla_zero", "02-Mod结构与加载.md",
          "原版脚本零使用功能前缀（INJECT/REPLACE 等专供 mod）",
          "vanilla_prefix_total", "", 0,
          "范围限定为 config.is_scriptable 认可的文件，与全量分析其余部分一致"),
    Claim("pfx.mods_total", "02-Mod结构与加载.md",
          "全部 mod 共使用 2737 次功能前缀", "mods_prefix_total", "", 2737,
          "六个前缀之和：REPLACE_OR_CREATE 1116 / INJECT 740 / TRY_INJECT 440 / "
          "REPLACE 221 / TRY_REPLACE 174 / INJECT_OR_CREATE 46"),
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


#: 独立的数字。两侧不能紧邻字母/下划线 —— 否则 ``dlc018_ep2`` 里的
#: ``018``、``1.14.2`` 里的 ``14`` 都会被当成数量断言（实测这是最大的误报源）。
_STANDALONE_NUM_RE = re.compile(r"(?<![A-Za-z0-9_])(\d[\d,]*)(?![A-Za-z0-9_])")


def find_doc_drift(docs_dir: Path | None = None) -> list[DocDrift]:
    """扫描文档，找出「锚点词 + 数字」与断言表对不上的地方。

    这是把「文档里的数字会不会过期」变成可自动检查的关键一步。

    判定规则（三条都是被误报逼出来的）：

    1. 以断言描述里的**英文标识符**为锚点（``on_actions`` / ``NAI`` / ``laws``），
       只看含锚点的行 —— 否则 264 这种数字在两千行文档里到处都可能出现，
       写错了也照样"通过"。
    2. 数字必须**独立成词**。``dlc018_*`` 里的 018、版本号 1.14.2 里的 14
       都不是数量。
    3. 只取锚点之后**第一个**独立数字。表格行里往往并列好几个指标
       （条目数 / 文件数 / 行数），语义槽位是「紧接着锚点的那个」。

    仍会有少量误报 —— 同一行里既有"条目数"又有"文件数"时，
    静态文本无法判断哪个是断言要的那个。因此这个函数是**给人看的线索**，
    不是自动改文档的依据。
    """
    docs_dir = docs_dir or config.DOCS
    out: list[DocDrift] = []
    if not docs_dir.is_dir():
        return out

    cache: dict[str, list[str]] = {}
    for claim in CLAIMS:
        if not isinstance(claim.expected, int) or not claim.expected:
            continue
        if claim.doc not in cache:
            path = docs_dir / claim.doc
            cache[claim.doc] = (
                path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            )
        lines = cache[claim.doc]
        if not lines:
            continue

        anchors = anchors_of(claim)
        if not anchors:
            continue
        tolerance = max(2, claim.expected // 100)
        expected_str = f"{claim.expected:,}"

        for n, line in enumerate(lines, start=1):
            if not any(a in line for a in anchors):
                continue
            # 期望值已经出现在这一行 —— 说明文档是对的
            if expected_str in line or str(claim.expected) in line:
                continue
            # 找出这一行里量级接近期望值的独立数字；有就说明多半是漂移。
            #
            # 不能只看锚点后的**第一个**数字：表格行 `| NAI | 1 | 1013 |`
            # 里第一个数字是文件数 1，真正的参数数在后面（实测漏报过 9 处）。
            for hit in _STANDALONE_NUM_RE.finditer(line):
                value = int(hit.group(1).replace(",", ""))
                if value in _COMMON_NOISE:
                    continue
                if 0 < abs(value - claim.expected) <= tolerance:
                    out.append(DocDrift(claim, claim.doc, n, line, value))
                    break
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


def _prod_vanilla_prefix(game: dict, _mods: dict, _cross: dict, _target: str) -> object:
    return game.get("概览", {}).get("原版前缀使用")


def _prod_mods_total(_game: dict, mods: dict, _cross: dict, _target: str) -> object:
    return mods.get("概览", {}).get("mod 数")


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
    "prefix_in_vanilla": _prod_vanilla_prefix,
    "mods_total": _prod_mods_total,
}


def product_kinds() -> frozenset[str]:
    """能被产物核验覆盖的断言类型。"""
    return frozenset(_PRODUCT_GETTERS)


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
            out.append(
                CheckResult(claim, None, False, f"产物中没有对应字段（{claim.kind}）")
            )
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
