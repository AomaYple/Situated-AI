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

除表格外，本模块还放三个**只读提取函数**（:func:`ideology_field_split` /
:func:`lobby_appeasement_usable` / :func:`religion_heritage_values`）——
它们对应的数字写在散文里、不在任何表里，因此一直没人看守：
`ideologies` 的 26 个法律组、`political_lobby_appeasement` 的 15 个可用条目、
`religions` 的 7 个 heritage 取值。三者的口径各不相同，逐个写在函数里。
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


# ── 三段散在散文里的数字 ────────────────────────────────────
# 这三处的数字都**不在表里**（写在 §11 / §14.6 的正文中），所以一直没人看守。
# 口径各自不同，且都踩过一次「看着像 A、其实是 B」，故逐个写下来。
def ideology_field_split() -> tuple[int, int, int]:
    """`common/ideologies` 顶层条目字段的三段拆分：``(总数, lawgroup_*, 其余)``。

    实测 **(35, 26, 9)**：35 个字段名，其中 26 个是 `lawgroup_*`（也就是
    26 个法律组的态度行），剩下 9 个是框架字段。

    ⚠️ **第三个数字 9 不是「值形态是标量」的个数**。那 9 个里只有 **4 个**是标量
    （`icon` / `priority` / `show_in_list` / `character_ideology`），另外 **5 个是块**
    （`country_trigger`、`interest_group_leader_trigger` / `_weight`、
    `non_interest_group_leader_trigger` / `_weight`）。按「值形态是标量」实现会得 4，
    而 4 与 9 都很像「合理的字段数」—— 错的那版**不会报错**，只会让文档里那句话
    和 `laws` 的 26 个法律组对不上账。9 = 35 − 26，是**前缀的补集**。
    """
    counter = field_occurrences("common/ideologies")
    lawgroups = sum(1 for key in counter if key.startswith("lawgroup_"))
    return len(counter), lawgroups, len(counter) - lawgroups


def lobby_appeasement_usable() -> int:
    """`common/political_lobby_appeasement` 里 ``is_always_usable = yes`` 的条目数。

    实测 **15**（该目录只有 1 个文件、**49 个顶层块**，其中 49 个都写了
    ``duration_to_show``、15 个写了 ``is_always_usable``，取值全是 ``yes``）。

    ⚠️ 别用 :func:`pdx.verify._dir_field_count` 那类「字段**种类**」口径：这里
    只有 2 种字段（`duration_to_show` / `is_always_usable`），得到的是 2 而不是 15。
    49 与 15 是**条目数**，字段种类数跟它们不是一个量。
    """
    return field_value_counts("common/political_lobby_appeasement", "is_always_usable").get(
        "yes", 0
    )


def religion_heritage_values() -> list[str]:
    """`common/religions` 里 ``heritage`` 用到的**去重取值**（实测 7 个，已排序）。

    返回的是文件里的**原样取值**，带 `heritage_` 前缀：
    `heritage_christian` / `_dharmic` / `_indigenous` / `_islamic` / `_jewish` /
    `_materialist` / `_taoic`。文档正文把它写成不带前缀的
    ``christian / islamic / jewish / dharmic / taoic / indigenous / materialist``
    —— 那是同一批值的简写，不是另一种口径。

    口径：:func:`pdx.usage.field_value_counts`（顶层条目块的字段），
    顶层宗教块 **17 个**（`dir_entries` 口径）。**注意第 8 个传承已存在**：
    `discrimination_traits/03_religious_heritages.txt` 定义了 8 个 `heritage_*` 特质，
    第 8 个 `heritage_humanist` **没有任何原版宗教引用**，所以这里只有 7 个取值 ——
    「8」是**特质定义数**、「7」是**被用到的取值数**，两个数都对，混着说才自相矛盾。
    """
    return sorted(field_value_counts("common/religions", "heritage"))


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


__all__ = [
    "doc_table_specs",
    "ideology_field_split",
    "lobby_appeasement_usable",
    "religion_heritage_values",
]
