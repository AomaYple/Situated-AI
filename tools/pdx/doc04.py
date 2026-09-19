"""doc 04（脚本系统）的机械表。

本篇剩下 15 张「有统计量列」的表，散布在 `scripted_*` / `events` /
`journal_entries` / `effect_localization` 四块里。它们共用三种口径：

* **字段出现次数** —— 每个条目块里的字段出现了多少次（`usage.field_occurrences`）；
* **取值分布** —— 某字段的取值各出现多少次（JE 的 `group`、事件的 `type`）；
* **文本级形态分类** —— 键名后缀、`$PARAM$` 出现次数、`placement` 写法
  （不是 `key = value` 形状，各自一个小分类器）。

三处口径值得写下来（都容易写错）
------------------------------
1. **`placement` 的形态是「互斥级联」**：``root`` 与 ``scope:…`` 与 ``c:XXX.capital``
   必须按顺序判、命中即停 —— 每行的次数是**该类**的总和，不是「有多少种写法」。
   实测六类相加 1460 + 586 + 1 + 3 + 2 + 9 = 2,061 = `placement` 字段总数，可分完。
2. **`root` / `ROOT` 是同一行的两种写法**（文档里写成合并的一行）：不能按
   「合并行」机制生成 —— 那套机制会把两个键的值**各算一遍**拼成 ``1460 / 1460``，
   而这一行要的是**合计**。所以键照抄文档原文、值由分类器一次给出。
3. **`$PARAM$` 先剥行内注释再数**：注释里出现的 ``$X$`` 不是一次使用
   （实测 `00_chris_scripted_effects.txt` 有一处只在注释里）。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .doc_tables import KeyedTableSpec
from .model import Block
from .scan import subdir_stats
from .usage import field_occurrences, field_value_counts, file_definition_counts

if TYPE_CHECKING:
    from collections.abc import Callable

    from .scan import DirStats


# ────────────────────── 口径一：字段出现次数（doc 04 各目录）──────────────────────


def _rows_plain(counter: Counter[str], col: int) -> list[tuple[str, dict[int, str]]]:
    """``(键, {列: 计数})`` —— **不带千位分隔符**。

    doc 04 全篇的统计表都不用分隔符（``4840`` / ``2255`` / ``1460``），
    而 doc 06/15/17 用逗号。生成器跟着**各自的文档风格**走：这样 `v3 tables`
    的 diff 里只剩真实变化，不会先被二十来行纯格式差异淹一遍。
    """
    return [
        (key, {col: str(n)}) for key, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


#: ``(表头, occurrence, 次数列, 目录)``。
_DOC04_FIELD_TABLES: tuple[tuple[str, int, int, str], ...] = (
    ("| 字段 | 出现次数 | 首例 |", 0, 1, "common/scripted_buttons"),
    ("| 字段 | 出现次数 | 首例 |", 1, 1, "common/scripted_progress_bars"),
    ("| 字段 | 使用次数 | 首例 | 备注 |", 0, 1, "common/journal_entries"),
    ("| 规则键 | 出现次数 |", 0, 1, "common/effect_localization"),
    (
        "| 字段 | 出现次数 | 首例 | 说明（由用法/上下文推断，非官方文档） |",
        0,
        1,
        "events",
    ),
)

#: `scripted_guis` 表里那行「文档有、原版零使用」的**合并行**。
#:
#: 六个字段名写在**同一个单元格**里（``| `a` / `b` / … | **0** |``），值是合计。
#: 不能交给「合并行」机制：那套机制会把每个键的值各算一遍，拼出 ``0 / 0 / 0 …``。
#: 所以键**照抄文档原文**（含反引号与间隔），值由这里一次给出 ——
#: 这样那一行才有人认领（不被认领的行既不警告也不更新）。
_SCRIPTED_GUIS_ZERO_KEY = "`notification_key` / `confirm_title` / `confirm_text` / `ai_is_valid` / `ai_chance` / `ai_frequency`"
_SCRIPTED_GUIS_ZERO_FIELDS = (
    "notification_key",
    "confirm_title",
    "confirm_text",
    "ai_is_valid",
    "ai_chance",
    "ai_frequency",
)


def scripted_guis_rows() -> list[tuple[str, dict[int, str]]]:
    """`scripted_guis` 字段表：计数器给的行 + 那行合并的「零使用」字段。"""
    counter = field_occurrences("common/scripted_guis")
    out = _rows_plain(counter, 1)
    if not any(counter.get(k) for k in _SCRIPTED_GUIS_ZERO_FIELDS):
        out.append((_SCRIPTED_GUIS_ZERO_KEY, {1: "0"}))
    return out


def _field_rows(dir_rel: str, col: int) -> Callable[[], list[tuple[str, dict[int, str]]]]:
    def rows() -> list[tuple[str, dict[int, str]]]:
        return _rows_plain(field_occurrences(dir_rel), col)

    return rows


def _doc04_field_specs() -> list[KeyedTableSpec]:
    return [
        KeyedTableSpec(
            name="doc04 字段表1 scripted_guis",
            header="| 字段 | 原版使用次数 | 首例 |",
            cells=scripted_guis_rows,
            append_new=False,
        ),
        *[
            KeyedTableSpec(
                name=f"doc04 字段表{n + 1} {d}",
                header=header,
                cells=_field_rows(d, col),
                occurrence=occ,
                append_new=False,
            )
            for n, (header, occ, col, d) in enumerate(_DOC04_FIELD_TABLES, start=1)
        ],
    ]


# ────────────────────── 口径二：取值分布 ──────────────────────

#: JE 分组表（两栏并排）里**作者选定**的行键 —— 版面是作者的，生成器只填数字。
#: 左栏 12 个、右栏 14 个（与文档的 14 行版式一致）。
_JE_GROUP_LEFT: tuple[str, ...] = (
    "`je_group_historical_content`",
    "`je_group_objectives`",
    "`je_group_internal_affairs`",
    "`je_group_tutorial`",
    "`je_group_technology`",
    "`je_group_foreign_affairs`",
    "`je_group_crises`",
    "`je_group_british_india`",
    "`je_group_russia_expansion`",
    "`je_group_brazil`",
    "`je_group_global_international_situations`",
    "`je_group_tanzimat`",
)
_JE_GROUP_RIGHT: tuple[str, ...] = (
    "`je_group_usa_manifest_destiny`",
    "`je_group_spa_economic_regeneration`",
    "`je_group_usa_american_civil_war`",
    "`je_group_meiji_restoration`",
    "`je_group_qing`",
    "`je_group_france_expansion`",
    "`je_group_expeditions`",
    "`je_group_german_unification`",
    "`je_group_russia_great_reformer`",
    "`je_group_brazil_pedro`",
    "`je_group_poland`",
    "`je_group_france_divided_monarchists`",
    "`je_group_global_test`",
    "`je_group_iberia`",
)


def je_group_counts() -> Counter[str]:
    """JE 的 ``group`` 取值分布 —— 键带反引号，与文档单元格一致。"""
    return Counter(
        {f"`{k}`": v for k, v in field_value_counts("common/journal_entries", "group").items()}
    )


def _je_group_rows(keys: tuple[str, ...], col: int) -> list[tuple[str, dict[int, str]]]:
    counter = je_group_counts()
    return [(k, {col: f"{counter.get(k, 0)}"}) for k in keys]


def _event_type_rows() -> list[tuple[str, dict[int, str]]]:
    counter = field_value_counts("events", "type")
    return [
        (f"`{k}`", {1: f"{n}"}) for k, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# ────────────────────── 口径三：文本级形态分类 ──────────────────────


def _top_level_keys(dir_rel: str) -> list[str]:
    keys: list[str] = []
    base = config.GAME / dir_rel
    if not base.is_dir():
        return keys
    for path in sorted(base.rglob("*.txt")):
        pf = parse_cached(path)
        keys += [a.key for a in pf.top_assignments if not a.is_variable]
    return keys


#: 命名形态：``(文档行键, 判据)``，**顺序即级联顺序**（命中即停）。
#: 键照抄文档单元格（含反引号），否则那一行没人认领。
_EFFECT_SHAPES: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("以 `_effect` / `_effects` 结尾", lambda k: k.endswith(("_effect", "_effects"))),
    ("以 `scripted_effect` 开头", lambda k: k.startswith("scripted_effect")),
)
_TRIGGER_SHAPES: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("以 `_trigger` / `_triggers` 结尾", lambda k: k.endswith(("_trigger", "_triggers"))),
    ("以 `is_` 开头", lambda k: k.startswith("is_")),
    ("以 `has_` 开头", lambda k: k.startswith("has_")),
    ("以 `can_` 开头", lambda k: k.startswith("can_")),
)


def shape_rows(
    dir_rel: str, shapes: tuple[tuple[str, Callable[[str], bool]], ...], other_label: str
) -> list[tuple[str, dict[int, str]]]:
    """``形态 | 数量 | 占比`` 三列 —— 占比 = 数量 / 该目录顶层键总数。"""
    keys = _top_level_keys(dir_rel)
    total = len(keys) or 1
    rest = list(keys)
    out: list[tuple[str, dict[int, str]]] = []
    for label, match in shapes:
        hit = [k for k in rest if match(k)]
        rest = [k for k in rest if not match(k)]
        out.append((label, {1: f"{len(hit)}", 2: f"{len(hit) / total * 100:.1f}%"}))
    out.append((other_label, {1: f"{len(rest)}", 2: f"{len(rest) / total * 100:.1f}%"}))
    return out


#: ``$参数$``（先剥行内注释）。
_PARAM_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$")


def param_counts(dir_rel: str) -> dict[str, int]:
    """每个文件里 ``$参数$`` 的出现次数（只列用到的文件）。"""
    out: dict[str, int] = {}
    base = config.GAME / dir_rel
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*.txt")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        code = "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())
        n = len(_PARAM_RE.findall(code))
        if n:
            out[path.name] = n
    return out


def param_rows(dir_rel: str) -> list[tuple[str, dict[int, str]]]:
    return [(name, {1: f"{n}"}) for name, n in sorted(param_counts(dir_rel).items())]


#: 事件的 ``placement`` 写法分类：``(文档行键, 判据)``，**顺序即级联顺序**。
#: 第一行的键把两种写法写在一起（``root`` / ``ROOT``），值是**合计** ——
#: 所以它必须整体作为一个键给出，不能交给「合并行」机制（那会把值各算一遍）。
_PLACEMENT_FORMS: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("`root` / `ROOT`", lambda v: v.lower() == "root"),
    ("`scope:<名字>`", lambda v: v.startswith("scope:")),
    ("`capital`（无前缀）", lambda v: v == "capital"),
    ("`c:XXX.capital`", lambda v: re.fullmatch(r"c:[A-Z0-9]+\.capital", v) is not None),
    ("`p:XXX.state`", lambda v: re.fullmatch(r"p:[A-Za-z0-9]+\.state", v) is not None),
    (
        "`s:STATE_X.region_state:YYY`",
        lambda v: re.fullmatch(r"s:[A-Za-z0-9_]+\.region_state:[A-Z0-9]+", v) is not None,
    ),
)


def placement_rows() -> list[tuple[str, dict[int, str]]]:
    counted = field_value_counts("events", "placement")
    rest: dict[str, int] = dict(counted)
    out: list[tuple[str, dict[int, str]]] = []
    for label, match in _PLACEMENT_FORMS:
        hit = [v for v in rest if match(v)]
        for v in hit:
            del rest[v]
        out.append((label, {1: f"{sum(counted[v] for v in hit)}"}))
    if rest:  # 出现新写法时打出来，别让它悄悄漏出统计
        print(f"[doc04] placement 有未分类写法：{sorted(rest)[:5]}")
    return out


# ────────────────────── 其余两张表 ──────────────────────


def scripted_overview_rows() -> list[tuple[str, dict[int, str]]]:
    """``scripted_effects`` / ``scripted_triggers`` 的文件数与顶层键数。"""
    out: list[tuple[str, dict[int, str]]] = []
    for system in ("scripted_effects", "scripted_triggers"):
        base = config.GAME / "common" / system
        files = sum(1 for _ in base.rglob("*.txt")) if base.is_dir() else 0
        keys = sum(file_definition_counts(f"common/{system}").values())
        out.append((system, {2: f"{files}", 3: f"{keys}"}))
    return out


def event_subdir_rows() -> list[tuple[str, dict[int, str]]]:
    base = config.GAME / "events"
    if not base.is_dir():
        return []
    stats: list[DirStats] = subdir_stats(base)
    return [(s.name, {1: f"{s.files}"}) for s in stats]


# ────────────────────── §0.2 目录规模表（两列都由工具给）──────────────────────

#: §0.2 的每一行：目录名 → `.txt` 列的写法。
#:
#: ``md1`` = ``N（+1 `.md`）``、``plain`` = ``N``、``md_only`` = ``**0**（仅 `.md`）``。
_OVERVIEW_TXT_KIND: dict[str, str] = {
    "on_actions": "md1",
    "script_values": "md1",
    "scripted_effects": "plain",
    "scripted_triggers": "plain",
    "scripted_guis": "md1",
    "scripted_buttons": "md1",
    "scripted_lists": "plain",
    "scripted_rules": "plain",
    "scripted_modifiers": "md_only",
    "scripted_progress_bars": "md1",
    "journal_entries": "md1",
    "decisions": "plain",
    "trigger_localization": "md1",
    "effect_localization": "plain",
}

#: §0.2 备注列的模板。``{keys}`` = 顶层**块**数；``{parts}`` = 逐文件块数用 ``+`` 连起来。
#: 两列都是公式化的（``40`` / ``共 **721** 个顶层键``），整表生成不夺走作者信息；
#: 逐行声明是因为「哪一行写什么」本来就不同。
_OVERVIEW_NOTE: tuple[tuple[str, str], ...] = (
    ("on_actions", "共 **{keys}** 个顶层 on_action 键"),
    ("script_values", "共 **{keys}** 个顶层键"),
    ("scripted_effects", "共 **{keys}** 个顶层键"),
    ("scripted_triggers", "共 **{keys}** 个顶层键"),
    ("scripted_guis", "共 **{keys}** 个 SGUI"),
    ("scripted_buttons", "共 **{keys}** 个按钮"),
    ("scripted_lists", "共 **{keys}** 个列表"),
    ("scripted_rules", "共 **{keys}** 个规则"),
    ("scripted_modifiers", "原版未定义任何 scripted modifier"),
    ("scripted_progress_bars", "共 **{keys}** 个进度条"),
    ("journal_entries", "共 **{keys}** 个 JE"),
    ("decisions", "共 **{keys}** 个 decision"),
    ("trigger_localization", "共 {parts} = **{keys}** 条"),
    ("effect_localization", "共 **{keys}** 条"),
)

#: 事件定义：顶层块且键形如 ``<namespace>.<整数>``。
_EVENT_KEY_RE = re.compile(r"^[^.]+\.\d+$")


def event_definition_count() -> int:
    """`events/` 里事件定义的个数（**顶层块** + 键形如 ``name.123``）。

    文档原文用的是「精确行匹配 ``^<namespace>.<id> = {``」，那条口径对
    **注释里的花括号**敏感（§9.3 记过一次 6 个的差异）。本仓库的解析器
    先剥注释再按花括号深度走，所以这里给的是可复现的块数。
    """
    base = config.GAME / "events"
    if not base.is_dir():
        return 0
    n = 0
    for path in sorted(base.rglob("*.txt")):
        pf = parse_cached(path)
        for a in pf.top_assignments:
            if not a.is_variable and isinstance(a.value, Block) and _EVENT_KEY_RE.match(a.key):
                n += 1
    return n


def _txt_kind_text(kind: str, dir_rel: str) -> str:
    base = config.GAME / dir_rel
    n = sum(1 for _ in base.rglob("*.txt")) if base.is_dir() else 0
    if kind == "md1":
        return f"{n}（+1 `.md`）"
    if kind == "md_only":
        return f"**{n}**（仅 `.md`）"
    return f"{n}"


def overview_rows() -> list[tuple[str, dict[int, str]]]:
    """§0.2「目录与文件规模」整表：``文件数`` 与 ``备注`` 两列都由工具给。"""
    out: list[tuple[str, dict[int, str]]] = []
    for dir_name, note in _OVERVIEW_NOTE:
        dir_rel = f"common/{dir_name}"
        per_file = file_definition_counts(dir_rel, blocks_only=True)
        out.append(
            (
                f"`{dir_rel}/`",
                {
                    1: _txt_kind_text(_OVERVIEW_TXT_KIND[dir_name], dir_rel),
                    2: note.format(
                        keys=sum(per_file.values()),
                        parts="+".join(str(v) for _k, v in sorted(per_file.items())),
                    ),
                },
            )
        )
    # events/ 的写法是复合的（根目录 + 子目录），单独一行
    ev = config.GAME / "events"
    subs = list(subdir_stats(ev))
    out.append(
        (
            "`events/`",
            {
                1: (
                    f"{sum(1 for _ in ev.glob('*.txt'))}（根）+ "
                    f"{len(subs)} 个子目录（{sum(s.files for s in subs)} 个）"
                ),
                2: f"共 **{event_definition_count()}** 个事件定义",
            },
        )
    )
    return out


def param_summary_rows(dir_rel: str) -> list[tuple[str, dict[int, str]]]:
    """``| 目录 | 使用该语法的文件数 | 出现次数 |`` 的单行汇总。

    第一列写的是 ``7 / 40``（用到的文件数 / 该目录 ``.txt`` 总数）——
    生成器只换**分子**，分母留给文档（``_merge_cell`` 的「N / M」规则）。
    """
    base = config.GAME / dir_rel
    per = param_counts(dir_rel)
    total_files = sum(1 for _ in base.rglob("*.txt")) if base.is_dir() else 0
    return [(f"`{dir_rel}/`", {1: f"{len(per)} / {total_files}", 2: f"{sum(per.values())}"})]


def localization_count_rows() -> list[tuple[str, dict[int, str]]]:
    """§11 那张「两种 localization 对照表」里**只有一行是数字**：条目数。

    整张表是作者写的差异对照（官方 `.md` / 规则键 / 否定后缀 / 条目名），
    只有最后一行是两个可数的量 —— 那就只更新那一行，别碰其余。
    """
    trigger = sum(file_definition_counts("common/trigger_localization").values())
    effect = sum(file_definition_counts("common/effect_localization").values())
    return [("条目数", {1: str(trigger), 2: str(effect)})]


def doc_table_specs() -> list[KeyedTableSpec]:
    """doc 04 的 19 张表（21 条 spec）。"""
    return [
        KeyedTableSpec(
            name="doc04 §0.2 目录规模",
            header="| 目录 | `.txt` 文件数 | 备注 |",
            cells=overview_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 scripted 总览",
            header="| 系统 | 位置 | 文件数 | 顶层键数 |",
            cells=scripted_overview_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 scripted_effects 参数汇总",
            header="| 目录 | 使用该语法的文件数 | 出现次数 |",
            cells=lambda: param_summary_rows("common/scripted_effects"),
            occurrence=0,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 scripted_triggers 参数汇总",
            header="| 目录 | 使用该语法的文件数 | 出现次数 |",
            cells=lambda: param_summary_rows("common/scripted_triggers"),
            occurrence=1,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 scripted_effects 参数分布",
            header="| 文件 | 出现次数 |",
            cells=lambda: param_rows("common/scripted_effects"),
            occurrence=0,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 scripted_triggers 参数分布",
            header="| 文件 | 出现次数 |",
            cells=lambda: param_rows("common/scripted_triggers"),
            occurrence=1,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 scripted_effects 命名形态",
            header="| 形态 | 数量 | 占比 |",
            cells=lambda: shape_rows(
                "common/scripted_effects", _EFFECT_SHAPES, "其它（无固定后缀）"
            ),
            occurrence=0,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 scripted_triggers 命名形态",
            header="| 形态 | 数量 | 占比 |",
            cells=lambda: shape_rows("common/scripted_triggers", _TRIGGER_SHAPES, "其它"),
            occurrence=1,
            append_new=False,
        ),
        *_doc04_field_specs(),
        KeyedTableSpec(
            name="doc04 JE 分组左栏",
            header="| 分组 | 使用次数 | | 分组 | 使用次数 |",
            cells=lambda: _je_group_rows(_JE_GROUP_LEFT, 1),
            key_column=0,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 JE 分组右栏",
            header="| 分组 | 使用次数 | | 分组 | 使用次数 |",
            cells=lambda: _je_group_rows(_JE_GROUP_RIGHT, 4),
            key_column=3,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 events 子目录",
            header="| 子目录 | 文件数 | 其中的 namespace |",
            cells=event_subdir_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 events type 取值",
            header="| 取值 | 出现次数（量级参考） |",
            cells=_event_type_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 events placement 形态",
            header="| 形式 | 出现次数 | 例 |",
            cells=placement_rows,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc04 两种 localization 条目数",
            header="| 项 | trigger_localization | effect_localization |",
            cells=localization_count_rows,
            append_new=False,
        ),
    ]


__all__ = [
    "doc_table_specs",
    "event_definition_count",
    "je_group_counts",
    "param_counts",
    "placement_rows",
    "shape_rows",
]
