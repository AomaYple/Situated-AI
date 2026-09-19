"""doc 17（角色、科技与内容呈现系统）的机械表。

为什么单独一个模块
-----------------
:mod:`pdx.usage` 的模块注释里写着「等某份文档的表多到值得拆分时再拆」。
doc 17 就是那个时点：**25 张**表里有 24 张可以脚本化，而它们要用到四种互不相同的
计数口径 —— 全塞进 ``usage.py`` 会让「口径」这件事更难看清。这里把 doc 17
自己的口径集中写下来。

四种口径（**逐表选定，不能互换**）
--------------------------------
1. **字段出现次数** —— 某目录的条目块里，各字段出现了多少次（``field_occurrences``）；
2. **逐文件顶层定义数** —— 每个文件有多少个定义（``@变量`` 不计）；
3. **取值分布** —— 某个字段的取值各出现多少次（消息的 ``type``、警报的 ``script_context``）；
4. **文本级机械统计** —— 颜色语法、本地化键后缀、修正符键名前缀（不是 `key = value` 形状）。

口径混在一张表里是 doc 17 的常态，也是本篇最大的坑
------------------------------------------------
实测撞到三处，每一处都**不报错、只是数字错**：

* `flag_definitions` 表里 10 行是 ``flag_definition`` **块内**字段，
  而 ``includes``（表里就写着「列表级」）在 **TAG 顶层块**里 —— 只按块内数会得 0；
* `modifier_types` 表把 ``game_data``（顶层字段）与 ``game_data.tags``
  （**子字段**）写在同一列里 —— 两种层级共用一个点号键名；
* 「取值分布」那四张两栏并排的表，**布局是作者的**：哪些值放左栏、哪些放右栏
  没有规则可推（消息的 `type` 是 9/13 分栏，自定义 loc 的 `type` 是 8/8）。
  所以生成器**只按行内位置更新数字，绝不重排** —— 为此给
  :class:`~pdx.doc_tables.KeyedTableSpec` 用上了 ``key_column``：
  左栏键在第 0 列、右栏键在第 2 列，一条 spec 管一半。

还有一处「文档与实况不符」是本模块**改出来的**而不是查出来的：
自定义 loc 的 `type` 取值表用「全部 ``type =`` 赋值」口径（384 处）与
字段表的「顶层条目」口径（376 处）**记了同一个字段**，两个数并不相等 ——
这也是为什么同一张表里的数字必须逐表声明口径。

除了表，本篇还有一批**散落在正文里的单个数字**（§0 的 29 目录合计、`genes`
的块名数、`technology` 的逐文件定义数…）。它们的失效方式和表不一样：
表会被 `v3 tables` 重算，正文不会 —— 只能靠人眼。所以这里另有一节
**点状查询**（口径 5），把每个数字的口径写在函数里，让正文与它可对照。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .doc_tables import KeyedTableSpec, norm_key
from .extract import extract_dir
from .model import Block
from .usage import (
    _iter_keyed_blocks,
    _rows,
    definition_rows,
    field_occurrences,
    field_value_counts,
    file_definition_counts,
    nested_field_occurrences,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


# ────────────────────────── 口径 1：字段出现次数 ──────────────────────────


def _field_rows(
    dir_rel: str, col: int, *, within: str | None = None, zero_keys: tuple[str, ...] = ()
) -> Callable[[], list[tuple[str, dict[int, str]]]]:
    """``(目录, 次数列, 块名, 允许为 0 的字段)`` → 取值函数。

    ``col`` 必须逐表指定：doc 17 的表里次数列的**位置不统一** ——
    有 ``| 字段 | 实测次数 |``（第 1 列），也有 ``| 字段 | 官方 .md | .txt 实测次数 |``
    （第 2 列）。写错列不会报错，只会把次数写进「有没有文档」那一列。

    ``zero_keys`` 是**「文档有、原版未使用」的行**（值 0）。它们不在计数器里 ——
    计数器只统计出现过的字段 —— 所以不显式声明的话，那些行永远没人认领：
    数字停在原处，将来真被用上了也不会更新（`test_doc17` 的「每一行都有人认领」抓的就是它）。
    """

    def rows() -> list[tuple[str, dict[int, str]]]:
        counter = field_occurrences(dir_rel, within=within)
        out = _rows(counter, col)
        for key in zero_keys:
            if key not in counter:
                out.append((key, {col: "0"}))
        return out

    return rows


#: doc 17 的「字段 → 出现次数」表。
#: ``(表头, occurrence, 次数列, 目录, 块名, 允许为 0 的字段)``。
#:
#: ``occurrence`` 是**同表头的第几张表**（``_find_header`` 按 ``startswith`` 取第 N 张），
#: 逐条用模拟 ``_find_header`` 反解并断言落在预期行 —— 人眼数序号在 20 多张表里必然出错，
#: 而数错只会「把 A 目录的次数写进 B 目录的表」，不报错。
_DOC17_FIELD_TABLES: tuple[tuple[str, int, int, str, str | None, tuple[str, ...]], ...] = (
    ("| 字段 | 官方 `.md` | `.txt` 实测次数 | 说明 |", 0, 2, "common/dna_data", None, ("dna",)),
    # `flag_definition` 块内字段；表里另有 `includes` 一行在**顶层**，见 doc_table_specs()。
    (
        "| 字段 | 文档 | 实测次数 | 说明 |",
        0,
        2,
        "common/flag_definitions",
        "flag_definition",
        ("revolutionary_canton",),
    ),
    (
        "| 字段 | `.md` | 实测次数 | 说明（`.md` 逐字） |",
        0,
        2,
        "common/dynamic_country_names",
        "dynamic_country_name",
        (),
    ),
    ("| 字段 | 实测次数 | 说明 |", 0, 1, "common/game_concepts", None, ()),
    ("| 字段 | 头注释 | 实测次数 | 说明 |", 0, 2, "common/messages", None, ()),
    ("| 字段 | 头注释 | 实测次数 | 说明 |", 1, 2, "common/alert_types", None, ("open_popup",)),
    ("| 字段 | 实测次数 | 说明 |", 1, 1, "common/map_interaction_types", None, ()),
    ("| 字段 | 头注释 | 实测次数 | 说明 |", 2, 2, "common/map_notification_types", None, ()),
    ("| 字段 | 实测次数 | 说明 |", 2, 1, "common/labels", None, ()),
    # 同一个目录两张表：条目层字段 与 `text` 块内部字段（自定义 loc 的核心）。
    ("| 字段 | 实测次数 | 说明 |", 3, 1, "common/customizable_localization", None, ()),
    ("| 字段 | 实测次数 | 说明 |", 4, 1, "common/customizable_localization", "text", ()),
    ("| 字段 | 实测次数 | 说明 |", 5, 1, "common/effect_localization", None, ()),
    ("| 字段 | 实测次数 | `.md` 是否记载 | 说明 |", 0, 1, "common/trigger_localization", None, ()),
    (
        "| 字段 | `.md` | 实测次数 | `.md` 原文注释 |",
        0,
        2,
        "common/modifier_type_definitions",
        None,
        (),
    ),
)


def _doc17_field_specs() -> list[KeyedTableSpec]:
    return [
        KeyedTableSpec(
            name=f"doc17 字段表{n} {d}",
            header=header,
            cells=_field_rows(d, col, within=within, zero_keys=zero),
            occurrence=occ,
            append_new=False,
        )
        for n, (header, occ, col, d, within, zero) in enumerate(_DOC17_FIELD_TABLES, start=1)
    ]


# ────────────────────────── 口径 2：逐文件定义数 ──────────────────────────


def _subdir_rows(
    root_rel: str, files_col: int, defs_col: int
) -> Callable[[], list[tuple[str, dict[int, str]]]]:
    """``common/coat_of_arms`` 一级子项的「文件数 + 顶层定义数」。

    键里带**反斜杠路径**（``coat_of_arms\\template_lists\\``），与文档写法一致；
    子目录内部**递归**统计（``coat_of_arms\\coat_of_arms\\`` 下有 17 个文件）。

    **只含一个 ``.txt`` 的子目录写文件名而不是目录名**（``coat_of_arms\\options\\atlases.txt``）：
    这是作者在文档里的写法，实测不照做的话那一行没人认领 ——
    而 ``append_new=False`` 的表对未认领的行既不警告也不更新。
    """
    base = config.GAME / root_rel
    root_name = root_rel.rsplit("/", 1)[-1]

    def rows() -> list[tuple[str, dict[int, str]]]:
        out: list[tuple[str, dict[int, str]]] = []
        for entry in sorted(base.iterdir()):
            if entry.is_dir():
                counts = file_definition_counts(f"{root_rel}/{entry.name}")
                if len(counts) == 1:
                    only = next(iter(counts))
                    key = f"{root_name}\\{entry.name}\\{only}"
                else:
                    key = f"{root_name}\\{entry.name}\\"
            elif entry.suffix == ".txt":
                whole = file_definition_counts(root_rel)
                counts = {entry.name: whole.get(entry.name, 0)}
                key = f"{root_name}\\{entry.name}"
            else:
                continue
            out.append(
                (key, {files_col: f"{len(counts):,}", defs_col: f"{sum(counts.values()):,}"})
            )
        return out

    return rows


def _game_data_rows() -> list[tuple[str, dict[int, str]]]:
    """``game_data`` 块的子字段 + **文档有、原版未使用**的 ``type_set``（值 0）。"""
    counter = nested_field_occurrences("common/modifier_type_definitions", "game_data")
    counter.setdefault("game_data.type_set", 0)
    return _rows(counter, 2)


def _includes_rows() -> list[tuple[str, dict[int, str]]]:
    """`flag_definitions` 表里的 ``includes`` 一行（在 **TAG 顶层块**里，不在块内）。

    键写成文档里的 ``| `includes`（列表级） |`` —— 键列里带作者的注
    （提醒读者它不是块内字段）。查计数器时只用裸名 ``includes``：
    键是**行身份**，必须与文档逐字对得上，否则那一行没人认领。
    """
    n = field_occurrences("common/flag_definitions")["includes"]
    return [("`includes`（列表级）", {2: f"{n:,}"})]


# ────────────────────────── 口径 3：取值分布 ──────────────────────────

#: 取值分布的实现已经通用化到 :func:`pdx.usage.field_value_counts`
#: （doc 15 的「态度值」与「好感度取值」用的是同一套），这里只保留 doc 17 的名字。
value_counter = field_value_counts


def _value_rows(
    dir_rel: str, field: str, keys: tuple[str, ...], col: int, *, deep: bool
) -> Callable[[], list[tuple[str, dict[int, str]]]]:
    """按 ``keys`` 的**声明顺序**给值 —— 布局是作者的，生成器只填数字。

    两个后果要写清楚：
    * 新出现的取值**不会**自动加行（两栏并排的版面没法机械重排），
      故另有 ``tools/tests/test_doc17.py`` 断言「实测取值集合 ⊆ 声明集合」；
    * 某个取值消失后它的行会留着旧数字 —— 同一张测试会把它抓出来。
    """

    def rows() -> list[tuple[str, dict[int, str]]]:
        counter = value_counter(dir_rel, field, deep=deep)
        return [(k, {col: f"{counter.get(norm_key(k), 0):,}"}) for k in keys]

    return rows


#: 两栏并排的「取值分布」表。``(表头, occurrence, 字段, 目录, 深度, 左栏键, 右栏键)``。
#:
#: 键的写法**照抄文档单元格**（含反引号）：:func:`pdx.doc_tables.norm_key` 只剥首尾的
#: `` ` `` 与 ``*``，写成别的形式就一行都匹配不上，而这类表 ``append_new=False``，
#: 不匹配**连警告都不会打** —— 于是数字静默过期。查计数器时同样要过一遍
#: ``norm_key``（计数器给的键不带反引号）—— 第一版忘了这一步，整列写成 0。
DIST_TABLES: tuple[tuple[str, int, str, str, bool, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "| `type` 值 | 次数 | | `type` 值 | 次数 |",
        0,
        "type",
        "common/messages",
        False,
        (
            "`country`",
            "`diplomatic_play`",
            "`power_bloc`",
            "`diplomatic_action`",
            "`military_formation`",
            "`character`",
            "`interest_group`",
            "`state`",
            "`treaty`",
        ),
        (
            "`building`",
            "`interest_marker`",
            "`company`",
            "`journal_entry`",
            "`political_movement`",
            "`law`",
            "`institution`",
            "`state_region`",
            "`civil_war`",
            "`diplomatic_pact`",
            "`diplomatic_demand`",
            "`market`",
            "`culture`",
        ),
    ),
    (
        "| 实测值 | 次数 | | 实测值 | 次数 |",
        0,
        "script_context",
        "common/alert_types",
        False,
        (
            "`player_country`",
            "`player_military_formation`",
            "`player_state`",
            "`player_market_goods`",
            "`player_invasion`",
            "`player_decision`",
            "`player_diplomatic_relations`",
            "`player_company`",
            "`player_treaty`",
        ),
        (
            "`player_country_formation`",
            "`player_diplomatic_play`",
            "`player_article`",
            "`player_subject`",
            "`player_war`",
            "`player_front`",
            "`player_market`",
            "`player_state_local_goods`",
            "`player_diplomatic_pact`",
        ),
    ),
    (
        "| `type` 值 | 次数 | | `type` 值 | 次数 |",
        1,
        "type",
        "common/customizable_localization",
        True,
        (
            "`country`",
            "`character`",
            "`state`",
            "`interest_group`",
            "`religion`",
            "`state_region`",
            "`goods`",
            "`culture`",
        ),
        (
            "`building`",
            "`political_lobby`",
            "`journal_entry`",
            "`puppet`",
            "`protectorate`",
            "`dominion`",
            "`market`",
            "`personal_union`",
        ),
    ),
)


def _doc17_dist_specs() -> list[KeyedTableSpec]:
    """左右两栏各一条 spec。

    **右栏的键在第 3 列、值在第 4 列** —— 表头是
    ``| `type` 值 | 次数 | | `type` 值 | 次数 |``，中间那个空单元格也是一列。
    第一版照「两栏 = 第 0/1 列 + 第 2/3 列」写成 ``key_column=2``，
    结果右栏**一行都没匹配上**（``row[2]`` 是空格）—— 而 ``append_new=False``
    的表对未匹配的行既不警告也不更新，于是右栏的数字看着「对」，
    其实只是没人动过它。是 ``test_doc17`` 的「每一行都有人认领」把它抓出来的。
    """
    out: list[KeyedTableSpec] = []
    for n, (header, occ, field, d, deep, left, right) in enumerate(DIST_TABLES, start=1):
        for side, (keys, key_col, col) in (("左", (left, 0, 1)), ("右", (right, 3, 4))):
            out.append(
                KeyedTableSpec(
                    name=f"doc17 分布表{n}{side} {field}",
                    header=header,
                    cells=_value_rows(d, field, keys, col, deep=deep),
                    key_column=key_col,
                    occurrence=occ,
                    append_new=False,
                )
            )
    return out


# ────────────────────────── 口径 4：文本级统计 ──────────────────────────


def color_rows() -> list[tuple[str, dict[int, str]]]:
    """`named_colors` 的颜色语法分布（按**行**数，注释先剥掉）。

    判据顺序与文档行序一致：``hsv360`` → ``hsv`` → ``rgb`` → 裸 ``{ r g b }``。
    顺序不能反：``hsv360`` 里含 ``hsv``、``rgb`` 行的值也可能是三个数。
    """
    base = config.GAME / "common/named_colors"
    counter: Counter[str] = Counter()
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            code = line.split("#", 1)[0]
            if "hsv360" in code:
                counter["hsv360 { h s v }"] += 1
            elif "hsv" in code:
                counter["hsv { h s v }"] += 1
            elif re.search(r"\brgb\b", code):
                counter["rgb { r g b }"] += 1
            elif re.search(r"=\s*\{", code) and re.search(r"[\d.]+\s+[\d.]+\s+[\d.]+", code):
                counter["裸 `{ r g b }"] += 1
    return [(key, {1: f"{counter[key]:,}"}) for key in counter]


def loc_suffix_keys(text: str) -> list[str]:
    """从 ``concepts_l_english.yml`` 里取出全部 ``concept_*`` 键（含重复）。"""
    return re.findall(r"^\s*(concept_[A-Za-z0-9_.]+):", text, re.MULTILINE)


def loc_suffix_rows() -> list[tuple[str, dict[int, str]]]:
    """`concepts_l_english.yml` 里 ``concept_*`` 键的后缀分布。

    分类互斥且完备（实测 614 + 239 + 49 + 252 + 1,037 = 2,191 = 文件里的键总数）。
    「复数」的判据是**去掉词尾 s 后仍是本文件的键**（``concept_subject_types`` ←
    ``concept_subject_type``）—— 只按「以 s 结尾」分类会把 126 个单数基名
    （如 ``concept_goods``）算成复数。
    """
    path = config.GAME / "localization/english/concepts_l_english.yml"
    keys: list[str] = loc_suffix_keys(path.read_text(encoding="utf-8")) if path.is_file() else []
    pool = set(keys)
    counter: Counter[str] = Counter()
    for k in keys:
        if k.endswith("_desc"):
            counter["`concept_x_desc`"] += 1
        elif k.endswith("_short"):
            counter["`concept_x_short`"] += 1
        elif k.endswith("_possessive"):
            counter["`concept_x_possessive`"] += 1
        elif k.endswith("s") and k[:-1] in pool:
            counter["`concept_x` + `s`（复数，如 `concept_countries`）"] += 1
        else:
            counter["`concept_x`"] += 1
    return [
        ("`concept_x`", {1: f"{counter['`concept_x`']:,}"}),
        ("`concept_x_desc`", {1: f"{counter['`concept_x_desc`']:,}"}),
        ("`concept_x_short`", {1: f"{counter['`concept_x_short`']:,}"}),
        ("`concept_x_possessive`", {1: f"{counter['`concept_x_possessive`']:,}"}),
        (
            "`concept_x` + `s`（复数，如 `concept_countries`）",
            {1: f"{counter['`concept_x` + `s`（复数，如 `concept_countries`）']:,}"},
        ),
    ]


#: `character_templates` 的文件名模式。``(行内写法, 判据)`` —— 顺序即文档行序，
#: 最后一行是「其余」：**不匹配上面任何一条**的文件数（说明列里手写的那 6 个文件名）。
#: 实测 1 + 193 + 2 + 4 + 1 + 1 + 1 + 1 + 6 = 210 = 该目录的 `.txt` 总数 —— 完备。
_TEMPLATE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("`00_default_template.txt`", r"^00_default_template\.txt$"),
    ("`country_<tag>.txt`", r"^country_[a-z0-9]+\.txt$"),
    ("`historical_leaders_*.txt`", r"^historical_leaders_.*\.txt$"),
    ("`historical_commanders_*.txt`", r"^historical_commanders_.*\.txt$"),
    ("`historical_agitators.txt`", r"^historical_agitators\.txt$"),
    ("`colonial_governor_templates.txt`", r"^colonial_governor_templates\.txt$"),
    ("`ruler_selector_templates.txt`", r"^ruler_selector_templates\.txt$"),
    ("`indian_princely_states.txt`", r"^indian_princely_states\.txt$"),
)


def template_rows() -> list[tuple[str, dict[int, str]]]:
    names = sorted(p.name for p in (config.GAME / "common/character_templates").glob("*.txt"))
    used: set[str] = set()
    out: list[tuple[str, dict[int, str]]] = []
    for label, pattern in _TEMPLATE_PATTERNS:
        hits = [n for n in names if re.match(pattern, n)]
        used |= set(hits)
        out.append((label, {1: f"{len(hits):,}"}))
    out.append(("其他单例", {1: f"{len([n for n in names if n not in used]):,}"}))
    return out


#: `modifier_types` 的键名前缀分布（决定修正符「流向」）。左右两栏，末行是「其余」。
_MODIFIER_PREFIX_LEFT: tuple[str, ...] = ("country_", "state_", "building_", "goods_", "ship_")
_MODIFIER_PREFIX_RIGHT: tuple[str, ...] = ("unit_", "character_", "power_", "interest_")


def _prefix_counter() -> Counter[str]:
    """键名前缀 → 键数，另存一个 ``_total`` 供「其余」用。"""
    counter: Counter[str] = Counter()
    base = config.GAME / "common/modifier_type_definitions"
    for path in sorted(base.rglob("*.txt")):
        pf = parse_cached(path)
        for a in pf.top_assignments:
            if a.is_variable:
                continue
            counter[a.key.split("_", 1)[0] + "_"] += 1
            counter["_total"] += 1
    return counter


def _modifier_prefix_rows(keys: tuple[str, ...], col: int) -> list[tuple[str, dict[int, str]]]:
    counter = _prefix_counter()
    total = counter["_total"]
    named = sum(counter[k] for k in (*_MODIFIER_PREFIX_LEFT, *_MODIFIER_PREFIX_RIGHT))
    out: list[tuple[str, dict[int, str]]] = []
    for k in keys:
        if k == "其余":
            out.append(("其余", {col: f"{total - named:,}"}))
        else:
            out.append((k, {col: f"{counter[k]:,}"}))
    return out


# ────────────────────────── 口径 5：§0 总览与点状查询 ──────────────────────────
#
# 这一节回答的是**散在正文里的单个数字**（不是整张表）。它们的共同坑是
# 「口径写在正文、代码里没有」—— 数字过期时没人能复算，只能靠人眼重数，
# 而人眼重数正是本篇出过最多错的地方（91 vs 433、1,681 vs 1,037、178 vs 179）。

#: doc 17 §0「一页总览」的 29 个目录，**顺序 = 文档行序**（作者按主题排的，别按名字排）。
#:
#: 这是 §0 那两个合计（**955 个 `.txt` / 11,705 个顶层定义键**）唯一的目录清单 ——
#: 再抄一份必然分叉，而分叉的现象就是「表里 29 行相加 ≠ 头条」：
#: `tools/tests/test_doc_overview.py` 正是拿头条与逐行各算一遍来抓它。
#: §0 那张表**没有生成器**（「官方 `.md`」与「一句话用途」两列是作者的判断），
#: 所以这里只提供计数，不去动表里的单元格。
OVERVIEW_DIRS: tuple[str, ...] = (
    "character_templates",
    "character_traits",
    "character_roles",
    "character_interactions",
    "dna_data",
    "genes",
    "ethnicities",
    "coat_of_arms",
    "flag_definitions",
    "dynamic_country_names",
    "dynamic_treaty_names",
    "dynamic_country_map_colors",
    "named_colors",
    "power_bloc_coa_pieces",
    "power_bloc_map_textures",
    "culture_graphics",
    "technology",
    "game_concepts",
    "messages",
    "alert_types",
    "alert_groups",
    "map_interaction_types",
    "map_notification_types",
    "labels",
    "console_command_macros",
    "customizable_localization",
    "effect_localization",
    "trigger_localization",
    "modifier_type_definitions",
)


def _overview_paths(dir_name: str) -> list[Path]:
    """§0 里一个目录的 `.txt`（**递归**：`technology` 一行写的是 ``3 + `eras/`1``）。"""
    base = config.GAME / "common" / dir_name
    return sorted(p for p in base.rglob("*.txt") if p.is_file()) if base.is_dir() else []


def _overview_counts() -> tuple[int, int]:
    """``(§0 的 .txt 数, 顶层定义键数)`` —— 一次遍历同时给出两个数。

    两个函数共用它，是为了让「文件数」与「键数」永远出自**同一份目录清单**
    （`:data:`OVERVIEW_DIRS``）与**同一次递归**。
    """
    files = 0
    keys = 0
    for dir_name in OVERVIEW_DIRS:
        paths = _overview_paths(dir_name)
        files += len(paths)
        for path in paths:
            keys += sum(
                1
                for a in parse_cached(path).top_assignments
                if not a.is_variable and isinstance(a.value, Block)
            )
    return files, keys


def overview_txt_count() -> int:
    """doc 17 §0 与头条的 **955**：29 个目录的 `.txt` 数（**递归**）。

    递归是必须的：`technology` 那 4 个文件里有 1 个在 `eras\\` 子目录下，
    只数直接子项会少 1 —— 而「954」正是 1.14.2 的旧值，容易与这个坑混淆。

    `.md` **不算**。篇首勘误表里那句「1,010 = 早期把 `.md` 也计入了」不成立：
    这 29 个目录下的官方 `.md` 只有 9 个，含 `.md` 是 **964**，1,010 任何口径都复现不出。
    """
    return _overview_counts()[0]


def overview_key_count() -> int:
    """doc 17 §0 与头条的 **11,705**：29 个目录的**顶层定义键出现次数**。

    口径与 §0 表、`test_doc_overview` 一致，三条缺一不可：

    * ``@变量`` 不计（它们是文件级宏，不是定义）；
    * **只数 ``键 = { … }`` 形状的顶层块**，标量赋值不算；
    * **按出现次数计，不去重** —— `genes` 因此是 9（去重块名只有 5 个，
      见 :func:`gene_block_names`），§0 表里那一行才写成「5 个块名（9 处定义）」。

    实测在这 29 个目录上顶格**标量赋值为 0 个**，所以「只数块」与
    「全部非 `@` 赋值」两种口径同值 —— 换个目录就未必了。
    """
    return _overview_counts()[1]


def loc_suffix_count(key: str) -> int:
    """`concepts_l_english.yml` 里某一类 ``concept_*`` 键的数量。

    口径就是 :func:`loc_suffix_rows`（五类互斥且完备，合计 2,191），
    这里只按**行身份**取一行的数值列。键要过一遍 ``strip("`")``：
    表里的键带反引号（``\\`concept_x\\```）。

    ⚠️ 复数那一行的键是
    ``\\`concept_x\\` + \\`s\\`（复数，如 \\`concept_countries\\`）``，
    整串 strip 之后**不等于** ``concept_x`` —— 所以 ``concept_x`` 拿到的是
    **1,037**，而不是「含复数的 1,289」。

    找不存在的键**抛 KeyError**（不返回 0）：这张表没有「文档有、原版未使用」
    那种合法零值，静默返回 0 只会让写错的键名看起来「数出来了」。
    """
    want = key.strip("`")
    rows = loc_suffix_rows()
    for row_key, cells in rows:
        if row_key.strip("`") == want:
            return int(cells[1].replace(",", ""))
    known = "、".join(f"`{row_key.strip('`')}`" for row_key, _cells in rows)
    raise KeyError(f"{key!r} 不是 concept 键后缀分类里的一行；可用的是：{known}")


def gene_block_names() -> list[str]:
    """`common/genes` 的**顶层块名**（去重、升序）—— 1.14.3 是 **5 个**。

    5 个名字、**9 处定义**（`accessory_genes` ×3、`special_genes` ×3）。
    两者不可互换：§0 表那一行写「5 个块名（9 处定义）」、合计按 9 计入；
    勘误表原先写的 6 是 1.14.2 的旧账。

    ⚠️ `gene_face_dacals` **不在这里** —— 它是 ``01_genes_morph.txt`` 里
    `morph_genes` 的**子块**（深度 1）。§6.2 那张「顶层块」表曾多列了它一行，
    多出来的那一行正好把块名数从 5 顶成 6。
    """
    return sorted(extract_dir(config.GAME / "common/genes").entries)


def flag_comment_brace_lines() -> int:
    """`00_flag_definitions.txt` 里**注释段含花括号**的行数 —— **21**。

    它是「必须先剥离注释再数花括号深度」那件事的**证据**：不剥注释会让该目录的
    顶层键从 433 掉到 91（本篇第一个被推翻的数字）。口径 = 「行内第一个 ``#``
    之后的部分含 ``{`` 或 ``}``」——只数 ``{`` 会得 13，因为有些被注释掉的块
    只留下收尾的 ``}``（实测踩过）。
    """
    path = config.GAME / "common" / "flag_definitions" / "00_flag_definitions.txt"
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return sum(
        1
        for line in text.splitlines()
        if "#" in line and ("{" in line.split("#", 1)[1] or "}" in line.split("#", 1)[1])
    )


def fallback_yes_count() -> int:
    """`customizable_localization` 里 ``fallback = yes`` 的处数 —— 全目录 **16**。

    纯文本口径：这些赋值写在 ``text`` 块**内部**，比字段口径更深，所以
    :func:`pdx.usage.field_value_counts` 数不到（返回空）。
    文档原先把 16 挂在两个文件名后面，读起来像「这两个文件里共 16 处」——
    实测那两个文件各只有 1 处，16 是**全目录**的数。
    """
    base = config.GAME / "common" / "customizable_localization"
    if not base.is_dir():
        return 0
    return sum(
        p.read_text(encoding="utf-8-sig", errors="replace").count("fallback = yes")
        for p in sorted(base.rglob("*.txt"))
        if p.is_file()
    )


def block_prefix_count(path_rel: str, block: str, prefix: str) -> int:
    """一个文件里、某个块内**以 ``prefix`` 开头的去重键名**个数。

    块定位复用 :func:`pdx.usage._iter_keyed_blocks`（**任意深度**），
    所以同名的块若出现多次，它们的键**合并去重**后再数。

    去重与否会差 1：`00_ethnicities_templates.txt` 的 `ethnicity_template`
    里 `gene_forehead_roundness` 写了两遍 —— 出现 94 次、**去重 93 个**，
    而正文那句「93 个 `gene_*`」用的是去重口径。

    ``prefix`` 是 ``str.startswith`` 判据（不是正则）；`@变量` 也是赋值、
    一样参与匹配（它们以 ``@`` 开头，用 ``gene_`` 这类前缀取不到）。
    文件不存在返回 **0**，与 :func:`pdx.usage.field_occurrences` 对空目录的行为一致。
    """
    path = config.GAME / path_rel
    if not path.is_file():
        return 0
    seen: set[str] = set()
    for key, blk in _iter_keyed_blocks(parse_cached(path)):
        if key == block:
            seen.update(a.key for a in blk.assignments() if a.key.startswith(prefix))
    return len(seen)


def block_item_count(path_rel: str, block: str) -> tuple[int, int]:
    """``(块的出现次数, 块内赋值条数)`` —— **返回值就是这个顺序**。

    用于 `common/cultures/00_cultures.txt` 的 `ethnicities`：``(317, 343)``。
    正文「317 个 `ethnicities = { … }` 块 / 343 条 `权重 = 族群` 条目」就是这两个数。

    ⚠️ 第一项是**块的出现次数**，不是「子块数」：那 317 个块里的 343 条赋值
    **全是标量**（``1 = caucasian`` 形状），子块 0 个 ——
    写成「317 个子块」会让人以为块里还嵌着块。权重取值实测只有 ``{1, 2, 3, 5, 10}``
    （其中 1 有 329 条）。

    正文原先那句「共 1,346 个 token」**没有任何自然口径能复现**
    （唯一凑得出 1,346 的分解是 1,029 + 317，像是手写 tokenizer 少算一格），
    已改成上面两个可复算的数。
    """
    path = config.GAME / path_rel
    if not path.is_file():
        return (0, 0)
    blocks = 0
    items = 0
    for key, blk in _iter_keyed_blocks(parse_cached(path)):
        if key == block:
            blocks += 1
            items += sum(1 for _ in blk.assignments())
    return (blocks, items)


def field_occurrence(dir_rel: str, field: str) -> int:
    """某目录里某字段的**出现次数** —— :func:`pdx.usage.field_occurrences` 的薄包装。

    口径写在 :mod:`pdx.usage`：只数**顶层条目块内部**的字段、跨文件累加、
    不按文件去重。`common/flag_definitions` 的 ``flag_definition`` 因此是
    **1,407**（TAG 顶层块里的条目数）、``includes`` 是 **2**。

    ⚠️ 同一个词可以在两种层级上：`flag_definition` 既是 TAG 块里的**字段**
    （1,407），又是那张表的**块名**（块内字段要传 ``within="flag_definition"``）——
    指错就得 0，而且不报错。

    字段不存在返回 **0**（``Counter`` 语义），这不是错误：doc 17 那几张字段表里
    本来就有「文档有、原版未使用」的行（值 0），见 ``_DOC17_FIELD_TABLES`` 的 ``zero_keys``。
    """
    return field_occurrences(dir_rel)[field]


def files_without_defs(dir_rel: str) -> int:
    """目录里**顶层定义数为 0** 的文件个数 —— `common/dna_data` 是 **1**。

    `dna_data` 的 584 个 `.txt` 里 583 个各有 1 个顶层定义，唯一例外是
    `00_dna.txt`：7,966 B **整块被注释**，首行逐字是 ``#test_oscar_wilde = {``。
    所以正文那句「每个文件只有 1 个顶层定义，共 583 个定义」里
    **「只有 1 个」不成立、583 成立**。
    """
    return sum(1 for n in file_definition_counts(dir_rel).values() if n == 0)


def tech_counts() -> dict[str, int]:
    """doc 17 §13 的科技计数（1.14.3）。每个键都是**可复算**的一项：

    * ``technologies`` —— `technology\\technologies\\` 的顶层定义（`dir_blocks` 口径）：**179**
    * ``eras`` —— `technology\\eras\\` 的顶层定义：**5**
    * ``definitions`` —— `technology\\`（含两个子目录）的**去重条目名**数：**184**
      （= 179 + 5；`v3 verify` 的 `chr.tech` 断言用的就是这个口径）
    * ``<文件名>`` —— 逐文件顶层定义：`10_production.txt` **57** / `20_military.txt` **58** /
      `30_society.txt` **64**
    * ``category.<值>`` —— `category` 字段取值分布：**57 / 58 / 64**（与逐文件数逐项相等）
    * ``era.<值>`` —— `era` 字段取值分布：**39 / 38 / 41 / 38 / 23**

    1.14.3 里这三套数**完全一致（都是 179）**。正文曾写「顶层定义 178、
    分布 179，差 1 未确认」—— 那是把 **1.14.2 的定义数**与 **1.14.3 的分布**
    并排比较：1.14.3 新增 1 项科技后三处同步变成 179，**「差 1 之谜」不存在**。
    """
    out: dict[str, int] = {}
    files = file_definition_counts("common/technology/technologies", blocks_only=True)
    out["technologies"] = sum(files.values())
    out["eras"] = sum(file_definition_counts("common/technology/eras", blocks_only=True).values())
    out["definitions"] = extract_dir(config.GAME / "common/technology").unique_entries
    out.update(sorted(files.items()))
    for field in ("category", "era"):
        values = field_value_counts("common/technology/technologies", field)
        for value, n in sorted(values.items()):
            out[f"{field}.{value}"] = n
    return out


# ────────────────────────── 登记 ──────────────────────────


def doc_table_specs() -> list[KeyedTableSpec]:
    """doc 17 的全部生成表（24 张，30 条 spec）。

    条数比表数多，是因为有三类表要**两条 spec 才覆盖得住**：
    * 两栏并排的分布表（左栏键在第 0 列、右栏键在**第 3** 列）；
    * `flag_definitions`（块内字段 + 顶层 ``includes``）；
    * `modifier_types`（顶层字段 + ``game_data`` 子字段）。
    每条只碰自己那几行 —— 其余行原样保留。
    """
    return [
        *_doc17_field_specs(),
        # `flag_definitions` 表的最后一行：`includes` 在 **TAG 顶层块**里（表里写着「列表级」），
        # 按块内字段数会得 0 —— 于是这一行永远显示「未使用」，而它其实有 2 处。
        KeyedTableSpec(
            name="doc17 flag_definitions includes",
            header="| 字段 | 文档 | 实测次数 | 说明 |",
            cells=_includes_rows,
            append_new=False,
        ),
        # `modifier_types` 的 4 行子字段：键写成 `game_data.子字段`，与文档的写法一致。
        KeyedTableSpec(
            name="doc17 modifier_types game_data 子字段",
            header="| 字段 | `.md` | 实测次数 | `.md` 原文注释 |",
            cells=_game_data_rows,
            append_new=False,
        ),
        # 逐文件定义数（口径 2）
        KeyedTableSpec(
            name="doc17 coat_of_arms 子目录",
            header="| 路径 | 文件数 | 顶层定义 | 内容 |",
            cells=_subdir_rows("common/coat_of_arms", 1, 2),
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc17 coat_of_arms 逐文件",
            header="| 文件 | 定义数 | 作用 |",
            cells=definition_rows("common/coat_of_arms/coat_of_arms", 1),
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc17 messages 逐文件",
            header="| 文件 | 定义数 | 内容 |",
            cells=definition_rows("common/messages", 1),
            append_new=False,
        ),
        # 取值分布（口径 3）
        *_doc17_dist_specs(),
        # 文本级统计（口径 4）
        KeyedTableSpec(
            name="doc17 named_colors 颜色语法",
            header="| 语法 | 次数 | 例（逐字） |",
            cells=color_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc17 concepts 本地化键后缀",
            header="| 键名模式 | 实测数量 | 用途 |",
            cells=loc_suffix_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc17 character_templates 文件名模式",
            header="| 文件名模式 | 文件数 | 作用 |",
            cells=template_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc17 modifier 前缀分布左",
            header="| 前缀 | 数量 | 前缀 | 数量 |",
            cells=lambda: _modifier_prefix_rows(_MODIFIER_PREFIX_LEFT, 1),
            key_column=0,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc17 modifier 前缀分布右",
            header="| 前缀 | 数量 | 前缀 | 数量 |",
            cells=lambda: _modifier_prefix_rows((*_MODIFIER_PREFIX_RIGHT, "其余"), 3),
            key_column=2,
            append_new=False,
        ),
    ]


__all__ = [
    "DIST_TABLES",
    "OVERVIEW_DIRS",
    "block_item_count",
    "block_prefix_count",
    "color_rows",
    "doc_table_specs",
    "field_occurrence",
    "files_without_defs",
    "gene_block_names",
    "loc_suffix_count",
    "loc_suffix_keys",
    "loc_suffix_rows",
    "overview_key_count",
    "overview_txt_count",
    "tech_counts",
    "template_rows",
    "value_counter",
]
