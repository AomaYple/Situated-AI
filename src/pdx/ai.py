"""AI 相关的两张/三张机械表（doc 03 与 doc 10 各占一部分）。

* **doc 03 §3.1**：`NAI` 命名空间里 1,017 个参数名的**前缀分布** Top 25
  （`DIPLO` 210 / `PRODUCTION` 89 / …）。前缀 = 参数名第一个 `_` 之前的部分，
  领域列是作者写的，不动。
* **doc 10 §0 / §1**：`common\\ai_strategies\\00_default_strategy.txt` 那 **60 个字段**的
  两种分类 —— 值的**形态**（56 块 + 3 枚举 + 1 字符串）与官方注释里的**叠加语义**。

叠加语义的口径（这一条花了点功夫才对上）
--------------------------------------
作者的四类判据是**措辞**，不是关键词：

* 相加 = 注释含 ``additively``（36 个）
* 覆盖 = 注释含**整句** ``Using a different value in a strategy will override this value``（10 个）
* 相乘 = ``will function multiplicatively`` 或 ``will result in several multiplications``（2 个）
* 未标注 = 其余（12 个）

第一版按「注释里出现 `override` 这个词」数，得到 12/10 —— 与文档的 10/12 差 2。
差的正是 `war_subsidies` 这类**在别的语境里用了 override** 的字段
（``Specifying values here will override subsidy priorities``）：它们讲的是另一个对象，
作者只认那句标准措辞。四类相加 = 60，与字段总数吻合。

注释的归属规则：字段**上方最近的连续 ``#`` 块**（跳过空行即停）。
实测该文件里每条注释都紧贴着自己的字段，没有歧义。
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from . import config, defines
from .cache import parse_cached
from .doc_tables import KeyedTableSpec
from .model import Block, Scalar
from .usage import ai_script_values_key_stats, ai_script_values_referenced

if TYPE_CHECKING:
    from collections.abc import Callable

#: doc 03 §3.1 那张 Top 25 的 25 个前缀（**作者的选取**，不是重新排序的结果）。
#: 生成器只填数字：Top-N 榜单在并列处的取舍是作者的版面决定，
#: 机械按 (次数, 名字) 排会把并列项换掉。
_NAI_PREFIXES: tuple[str, ...] = (
    "DIPLO",
    "PRODUCTION",
    "MONEY",
    "AI",
    "GOAL",
    "FLEET",
    "AUTONOMOUS",
    "UNIFICATION",
    "CHANGE",
    "MOBILIZATION",
    "GOVERNMENT",
    "POWER",
    "NAVAL",
    "OWNER",
    "COMPANY",
    "DIPLOMATIC",
    "FRONT",
    "MIN",
    "CONSTRUCTION",
    "RAID",
    "SHIP",
    "TREATIES",
    "DEFEND",
    "PROTECT",
    "BLOCKADE",
)

#: 字段字段（60 个）所在的包装块。
_AI_STRATEGY_FILE = "common/ai_strategies/00_default_strategy.txt"

#: 叠加语义的四类判据 —— ``(短键, 文档行键, 判据)``。顺序即优先级（一个字段只进一类）。
#: **短键**（``additive`` / ``override`` / …）是给 `v3 verify` 的 target 用的；
#: 文档行键才是往表格里写的文字。两者分开是踩出来的：早先把行键当短键用，
#: `semantic_counts()["multiplicative"]` 永远是 0，而断言表还以为自己在核对。
_SEMANTICS: tuple[tuple[str, str, Callable[[str], bool]], ...] = (
    ("additive", "**相加 additive**", lambda c: "additively" in c),
    (
        "override",
        "**覆盖 override**",
        lambda c: "Using a different value in a strategy will override this value" in c,
    ),
    (
        "multiplicative",
        "**相乘 multiplicative**",
        lambda c: "will function multiplicatively" in c or "several multiplications" in c,
    ),
)


def nai_prefix_counts() -> Counter[str]:
    """`NAI` 命名空间的参数名前缀 → 个数。"""
    report = defines.extract_defines()
    counter: Counter[str] = Counter()
    for ns in report.namespaces:
        if ns.name != "NAI":
            continue
        for param in ns.params:
            counter[param.name.split("_", 1)[0]] += 1
    return counter


def nai_prefix_rows() -> list[tuple[str, dict[int, str]]]:
    counts = nai_prefix_counts()
    return [(f"`{p}`", {1: str(counts[p])}) for p in _NAI_PREFIXES]


def _strategy_fields() -> list[tuple[str, str, object]]:
    """``(字段名, 上方注释文本, 值)`` —— 60 个字段，按文件顺序。"""
    path = config.GAME / _AI_STRATEGY_FILE
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    pf = parse_cached(path)
    out: list[tuple[str, str, object]] = []
    for top in pf.top_assignments:
        if top.is_variable or not isinstance(top.value, Block):
            continue
        for a in top.value.assignments():
            i = a.line - 2  # a.line 是 1 基；上一行的下标
            comments: list[str] = []
            while i >= 0 and lines[i].strip().startswith("#"):
                comments.append(lines[i].strip())
                i -= 1
            out.append((a.key, " ".join(reversed(comments)), a.value))
    return out


#: 形态分类的 target → 文档里那一行的键。
_SHAPE_LABEL: dict[str, str] = {
    "block": "script value 块",
    "scalar": "枚举标量",
    "string": "字符串",
}


def strategy_field_count() -> int:
    """`00_default_strategy.txt` 里的字段总数（实测 60）。"""
    return len(_strategy_fields())


def shape_counts() -> dict[str, int]:
    """值形态 → 个数（``block`` / ``scalar`` / ``string``）。

    ``nonblock`` = ``scalar + string``：文档 §0 那句「另有 4 个标量字段」
    数的是**非块**字段（含 `icon` 那个字符串），不是「枚举标量」那一类 ——
    两者差 1，正是「口径差 1」最容易被误当成漂移的地方。
    """
    counts = {"block": 0, "scalar": 0, "string": 0}
    for _key, _c, value in _strategy_fields():
        if isinstance(value, Block):
            counts["block"] += 1
        elif isinstance(value, Scalar) and value.quoted:
            counts["string"] += 1
        else:
            counts["scalar"] += 1
    counts["nonblock"] = counts["scalar"] + counts["string"]
    return counts


def semantic_counts() -> dict[str, int]:
    """官方注释里的叠加语义 → 个数（含 ``unmarked``）。"""
    counted: Counter[str] = Counter()
    for _key, comment, _value in _strategy_fields():
        for short, _label, match in _SEMANTICS:
            if match(comment):
                counted[short] += 1
                break
        else:
            counted["unmarked"] += 1
    return dict(counted)


def semantic_rows() -> list[tuple[str, dict[int, str]]]:
    """doc 10 §0：四类叠加语义各多少个字段。"""
    counted = semantic_counts()
    return [
        *((label, {1: str(counted[short])}) for short, label, _m in _SEMANTICS),
        ("未标注", {1: str(counted["unmarked"])}),
    ]


def shape_rows() -> list[tuple[str, dict[int, str]]]:
    """doc 10 §1：60 个字段的**值形态**（块 / 枚举标量 / 字符串）。"""
    counts = shape_counts()
    return [(label, {1: str(counts[kind])}) for kind, label in _SHAPE_LABEL.items()]


def nai_param_count() -> int:
    """``common/defines/00_ai.txt`` 里 ``NAI`` 命名空间块的参数数（实测 **1,017**）。

    与 ``v3 verify`` 的 ``defines_params``（target ``00_ai.txt:NAI``）同一个量 ——
    文档里 doc 03 §3.3 与 doc 09 §4 都引用它，所以口径写在 ``pdx.defines`` 那一层，
    这里只是薄包装（不重复实现计数规则）。
    """
    report = defines.extract_defines(config.GAME / "common" / "defines")
    return sum(ns.count for ns in report.get("NAI"))


#: doc 09 §4 那张「领域 → 对应字段」的表头。
FIELD_MAP_TABLE = "| 领域 | 对应字段 | 所在位置 |"


def doc09_field_rows() -> list[tuple[str, dict[int, str]]]:
    """doc 09 §4 里**机械可算的两行**（其余行是作者写的字段清单，不动）。

    * ``PM 评分 / 外交阈值 / 各类机制`` → ``00_ai.txt`` 的 ``NAI`` 参数数；
    * ``AI 中间值`` → 脚本值顶层键数 + 其中被默认策略文件引用的个数。

    这两行原先手写、且各配了一条断言 —— 但断言只能报「不一致」，改还是要人改；
    接进生成器之后 ``v3 tables --write`` 直接算对。
    """
    stats = ai_script_values_key_stats()
    return [
        ("PM 评分 / 外交阈值 / 各类机制", {1: f"{nai_param_count():,} 个 `NAI` 参数"}),
        (
            "AI 中间值",
            {
                1: f"{stats['top_keys']} 个脚本值"
                f"（其中 {ai_script_values_referenced()} 个被 `00_default_strategy.txt` 引用）"
            },
        ),
    ]


def doc_table_specs() -> list[KeyedTableSpec]:
    """doc 03 一张 + doc 09 一张 + doc 10 两张（名字前缀区分归属，由 docgen 分发）。"""
    return [
        KeyedTableSpec(
            name="doc03 NAI 参数前缀 Top25",
            header="| 前缀 | 数量 | 领域 |",
            cells=nai_prefix_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc09 领域对应字段",
            header=FIELD_MAP_TABLE,
            cells=doc09_field_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc10 叠加语义",
            header="| 语义 | 数量 | 含义 |",
            cells=semantic_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc10 字段形态",
            header="| 形态 | 数量 | 写法 |",
            cells=shape_rows,
            append_new=False,
        ),
    ]


__all__ = [
    "doc_table_specs",
    "nai_prefix_counts",
    "nai_prefix_rows",
    "semantic_counts",
    "semantic_rows",
    "shape_counts",
    "shape_rows",
    "strategy_field_count",
]
