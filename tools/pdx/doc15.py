"""doc 15（政治人口与社会）的机械表。

为什么单独一个模块
-----------------
doc 15 的 §0 是一张 **25 个目录 × 2 列**的总览表（`.txt` 数与顶层定义数），
其余六张表散布在 `laws` / `interest_group_traits` / `ideologies` /
`discrimination_traits` 四节里。它们共用两种口径：

* **顶层定义数** = 目录内所有 `.txt` 的顶层块数（``@变量`` 不计）——
  §0 的定义数列与 `ideologies` 的逐文件表都是这个；
* **取值普查** = 给定取值集合、数它们作为 ``=`` 赋值出现了多少次 ——
  五档态度（``approve`` …）与好感度门槛（``loyal`` …）都是这个形状，
  而且**与键名无关**（态度值的键有 26 种 `lawgroup_*`，取值只有 5 种）。

两处口径值得单独写下来
--------------------
* **§0 的「顶层定义键」列不是数字**（写的是 ``law_*`` 这类键名前缀），
  所以只填 `.txt` 与定义数两列，那一列是作者按命名规律归纳的，生成器不碰；
* **`laws` 的文件名前缀表**：`00_` / `01_` / `02_` 是**类别序号**，
  实测 9 + 8 + 8 = 25 恰好等于该目录的 `.txt` 数 —— 文档原写 `01_` 9 个，
  与同一节的「25 个 `.txt`」自相矛盾；这是本模块改出来的第一处订正。
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .doc_tables import KeyedTableSpec
from .usage import (
    _rows,
    definition_rows,
    field_occurrences,
    field_value_counts,
    file_definition_counts,
    value_census,
)

if TYPE_CHECKING:
    from collections.abc import Callable

#: §0 的一页总览：25 个目录。顺序 = 文档行序（作者按主题排的，别按文件名排）。
#: 表头提出来做成常量：测试要按同一个字符串去文档里找表，两处各抄一遍迟早抄错。
_OVERVIEW_HEADER = "| # | 目录 | .txt | 官方 `.md` | 顶层定义键 | 定义数 | 一句话用途 |"

_OVERVIEW_DIRS: tuple[str, ...] = (
    "laws",
    "law_groups",
    "interest_groups",
    "interest_group_traits",
    "ideologies",
    "parties",
    "political_movements",
    "political_movement_categories",
    "political_movement_pop_support",
    "political_lobbies",
    "political_lobby_appeasement",
    "institutions",
    "government_types",
    "legitimacy_levels",
    "pop_types",
    "social_classes",
    "social_hierarchies",
    "cultures",
    "religions",
    "discrimination_traits",
    "discrimination_trait_groups",
    "ethnicities",
    "amendments",
    "cohesion_levels",
    "liberty_desire_levels",
)


def _txt_count(dir_rel: str) -> int:
    base = config.GAME / dir_rel
    return sum(1 for p in base.rglob("*.txt") if p.is_file()) if base.is_dir() else 0


def _overview_rows() -> list[tuple[str, dict[int, str]]]:
    """``| # | 目录 | .txt | … | 定义数 | … |`` 的两列数字（第 2、5 列）。

    目录行的键写**目录名**（第 1 列是行号 ``#``，不是键）。
    """
    return [
        (
            d,
            {
                2: f"{_txt_count(f'common/{d}'):,}",
                5: f"{sum(file_definition_counts(f'common/{d}').values()):,}",
            },
        )
        for d in _OVERVIEW_DIRS
    ]


#: `laws` 的文件名前缀 → 文件数。前缀是**类别序号**（见 §1.2），不是任意分组：
#: `00_` 权力结构、`01_` 经济、`02_` 人权。
def _laws_prefix_rows() -> list[tuple[str, dict[int, str]]]:
    base = config.GAME / "common/laws"
    counter: Counter[str] = Counter()
    if base.is_dir():
        for path in sorted(base.glob("*.txt")):
            head = path.name.split("_", 1)[0]
            if head.isdigit():
                counter[f"{head}_"] += 1
    return [(prefix, {2: f"{n:,}"}) for prefix, n in sorted(counter.items())]


def _approval_rows() -> list[tuple[str, dict[int, str]]]:
    """`interest_group_traits` 的 `min_approval` / `max_approval` **取值**分布。

    键取**第 1 列**（取值 ``loyal`` / ``happy`` / ``unhappy``）而不是第 0 列 ——
    第 0 列是字段名，``min_approval`` 与 ``max_approval`` 各占一行，
    按第 0 列做键会两行撞在一起。取值本身互不重叠（哪个门槛用哪个枚举是固定的），
    所以两个字段的取值可以并进同一个计数器。
    """
    dir_rel = "common/interest_group_traits"
    counter = field_value_counts(dir_rel, "min_approval") + field_value_counts(
        dir_rel, "max_approval"
    )
    return [(v, {2: f"{n:,}"}) for v, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]


#: `ideologies` 的五档态度 —— `law_stance` 的全部合法取值。
_STANCES: tuple[str, ...] = (
    "neutral",
    "disapprove",
    "strongly_disapprove",
    "approve",
    "strongly_approve",
)


def _stance_rows() -> list[tuple[str, dict[int, str]]]:
    counter = value_census("common/ideologies", _STANCES)
    return [(v, {1: f"{counter.get(v, 0):,}"}) for v in _STANCES]


#: `discrimination_traits` 的四类：``(文档里的行键, 键前缀, 算哪些文件)``。
#:
#: 前两行是**总数与其中的子集**（不是互斥分组）：文档第一行的 118 是
#: ``heritage_*`` 的**合计**（``00_cultural_heritages.txt`` 110 + ``03_religious_heritages.txt`` 8），
#: 第二行的 8 是把宗教那一份单独列出来。实测 196(语言) + 118(传承合计) + 10(传统) = 324 = 该目录定义总数，
#: 与 §15.4 的「四类特质实测分布」自洽；把前两行当互斥分组会让合计变成 332，与事实不符。
_DISCRIMINATION_ROWS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "`heritage_*`（文化传承）",
        "heritage_",
        ("00_cultural_heritages.txt", "03_religious_heritages.txt"),
    ),
    ("`heritage_*`（宗教传承）", "heritage_", ("03_religious_heritages.txt",)),
    ("`language_*`", "language_", ("01_languages.txt",)),
    ("`tradition_*`", "tradition_", ("02_traditions.txt",)),
)


def _key_prefix_counts(dir_rel: str) -> dict[str, Counter[str]]:
    """``文件名 → {键前缀: 个数}``（只数顶层定义，``@变量`` 不算）。"""
    out: dict[str, Counter[str]] = {}
    base = config.GAME / dir_rel
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*.txt")):
        pf = parse_cached(path)
        c: Counter[str] = Counter()
        for a in pf.top_assignments:
            if a.is_variable:
                continue
            for prefix in ("heritage_", "language_", "tradition_"):
                if a.key.startswith(prefix):
                    c[prefix] += 1
        out[path.name] = c
    return out


def _discrimination_rows() -> list[tuple[str, dict[int, str]]]:
    per_file = _key_prefix_counts("common/discrimination_traits")
    return [
        (
            label,
            {
                1: f"{sum(per_file.get(name, Counter())[prefix] for name in names):,}",
            },
        )
        for label, prefix, names in _DISCRIMINATION_ROWS
    ]


def _law_rows() -> Callable[[], list[tuple[str, dict[int, str]]]]:
    """`laws` 的字段出现次数（表是**节选**：文档列了 26 个字段，只更新已列出的行）。"""
    return lambda: _rows(field_occurrences("common/laws"), 1)


def doc_table_specs() -> list[KeyedTableSpec]:
    """doc 15 的七张表（登记进 :func:`pdx.docgen.targets`）。"""
    return [
        KeyedTableSpec(
            name="doc15 §0 一页总览",
            header=_OVERVIEW_HEADER,
            cells=_overview_rows,
            # 键在第 1 列：第 0 列是行号 `#`。
            key_column=1,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc15 laws 文件名前缀",
            header="| 前缀 | 含义 | 文件数 |",
            cells=_laws_prefix_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc15 laws 字段出现次数",
            header="| 字段 | 出现次数 | 类型 | 含义 | 来源 |",
            cells=_law_rows(),
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc15 interest_group_traits 门槛取值",
            header="| 字段 | 取值 | 次数 |",
            cells=_approval_rows,
            key_column=1,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc15 ideologies 逐文件定义数",
            header="| 文件 | 定义数 | 用途 |",
            cells=definition_rows("common/ideologies", 1),
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc15 ideologies 五档态度",
            header="| 态度值 | 次数 |",
            cells=_stance_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc15 discrimination_traits 分类",
            header="| 特质类别 | 定义数 | 被谁引用（**【实测】**） |",
            cells=_discrimination_rows,
            append_new=False,
        ),
    ]


__all__ = ["doc_table_specs"]
