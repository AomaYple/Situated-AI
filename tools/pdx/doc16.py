"""doc 16（外交军事与地图）剩下的八张游戏侧机械表。

doc 16 的绝大多数表在上一批已经接进 :mod:`pdx.usage`；这一批是**剩下的八张**，
它们的共同点是「统计单位不是字段」：

* **文本级**：`scope:` 记号、`flags` / `settings` / `ai.*` 那几张数的是
  「有多少个文件里出现过这个词」——纯文本计数，与「它作为某个字段的取值出现了几次」
  在**一个文件里出现两次**时才分岔（实测 `can_be_renegotiated` 出现 27 次、只在 26 个文件里）；
* **任意深度**：`travel_network\\naval_network.txt` 是程序导出的
  ``nodes = { { province = … } … }``，`nodes` 在顶层、`province` 在**匿名块**里，
  两种「只看某一层」的口径都数不出那张表（见 `usage.all_field_occurrences`）。

两张**刻意不生成**的表（写在 :data:`NOT_GENERATED` 里）与这里无关：
它们统计的是**本机装的 mod**（`workshop\\content\\529340\\`），
换台机器、或作者退订一个 mod，数字就变 —— 那不是「文档里的数字过期」，
而是「这份快照描述的是另一台机器」。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .doc_tables import KeyedTableSpec, norm_key
from .model import Block
from .usage import (
    all_field_occurrences,
    word_file_counts,
    word_stats,
)

if TYPE_CHECKING:
    from collections.abc import Callable

#: 刻意不生成的两张表 —— 理由是「依赖本机 workshop 内容」，不是「口径不清」。
#: `tools/tests/test_inventory.py` 的 `NOT_GENERATED` 里也有同样的两条（那边管余额）。
NOT_GENERATED: dict[str, str] = {
    "| 前缀 | 出现次数 | 语义（由 mod 用法推断） |": (
        "§1.1 六种前缀：统计对象是 `workshop\\content\\529340\\**\\*.txt`"
        "（本机订阅的 mod），换机器/退订就会变"
    ),
    "| SteamId | mod 名 | 本范围内文件数 | 覆盖（原版相对路径） | 新增（自有文件名） |": (
        "§5 改造面总表：同上，统计的是本机 23 个 mod 的覆盖/新增清单"
    ),
}

#: `common/diplomatic_actions/` 是 §2 那张「scope 记号」表的样本范围（48 个 `.txt`）。
_DIPLOMATIC_DIR = "common/diplomatic_actions"
_DIPLOMATIC_MD = "diplomatic_action.md"

#: ``(文档行键, 记号, 是否只看 .md)``。键照抄文档单元格。
_MARKERS: tuple[tuple[str, str, bool], ...] = (
    ("`scope:target_country`", "scope:target_country", False),
    ("`scope:actor`", "scope:actor", False),
    ("`scope:target`（裸，`scope:target(?!_)`）", "scope:target", False),
    ("`scope:target`（仅在 `.md` 里）", "scope:target", True),
)


def marker_rows() -> list[tuple[str, dict[int, str]]]:
    """§2 的 scope 记号表：``出现次数 | 出现文件数``。

    第 3 行是**裸** ``scope:target``（正则 ``scope:target(?!_)``，即不跟下划线），
    第 4 行是官方 `.md` 里的那两处 —— 两者数的是不同来源，所以分开。
    """
    out: list[tuple[str, dict[int, str]]] = []
    base = config.GAME / _DIPLOMATIC_DIR
    for label, marker, md_only in _MARKERS:
        if md_only:
            path = base / _DIPLOMATIC_MD
            text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            occ = len(re.findall(r"scope:target(?!_)", text))
            out.append((label, {1: str(occ), 2: "1" if occ else "0"}))
        elif marker == "scope:target":
            occ = files = 0
            for path in sorted(base.rglob("*.txt")):
                n = len(re.findall(r"scope:target(?!_)", path.read_text(encoding="utf-8-sig")))
                occ += n
                files += 1 if n else 0
            out.append((label, {1: str(occ), 2: str(files)}))
        else:
            occ, files = word_stats(_DIPLOMATIC_DIR, marker)
            out.append((label, {1: str(occ), 2: str(files)}))
    return out


#: `ai.*` 那 6 行：文档行键带 `ai.` 前缀，实际数的是**字段本名**。
_TREATY_AI_KEYS: tuple[tuple[str, str], ...] = (
    ("`ai.inherent_accept_score`", "inherent_accept_score"),
    ("`ai.contextual_accept_score`", "contextual_accept_score"),
    ("`ai.evaluation_chance`", "evaluation_chance"),
    ("`ai.proposal_weight`", "proposal_weight"),
    ("`ai.wargoal_score_multiplier`", "wargoal_score_multiplier"),
    ("`ai.quantity_input_value`", "quantity_input_value"),
)

#: 文档完全没写、vanilla 在用的两个键。
_TREATY_MISSING_KEYS: tuple[str, ...] = ("usage_limit", "ship_valid_trigger")


def treaty_ai_rows() -> list[tuple[str, dict[int, str]]]:
    counts = word_file_counts("common/treaty_articles", [k for _l, k in _TREATY_AI_KEYS])
    return [(label, {1: str(counts[key])}) for label, key in _TREATY_AI_KEYS]


def treaty_missing_rows() -> list[tuple[str, dict[int, str]]]:
    counts = word_file_counts("common/treaty_articles", _TREATY_MISSING_KEYS)
    return [(f"**`{key}`**", {1: str(counts[key])}) for key in _TREATY_MISSING_KEYS]


#: `treaty_articles` 的 `flags` 表（两栏并排）里作者选定的 33 行。
_TREATY_FLAGS_LEFT: tuple[str, ...] = (
    "`can_be_renegotiated`",
    "`can_be_enforced`",
    "`giftable`",
    "`ai_consider_threaten_naval_hostilities`",
    "`friendly`",
    "`hostile`",
    "`is_military_access`",
    "`causes_state_transfer`",
    "`exclude_from_make_this_work`",
    "`is_abandon_piracy`",
    "`is_alliance`",
    "`is_defensive_pact`",
    "`is_goods_transfer`",
    "`is_guarantee_independence`",
    "`is_investment_rights`",
    "`is_law_commitment`",
    "`is_money_transfer`",
    "`is_monopoly_for_company`",
)
_TREATY_FLAGS_RIGHT: tuple[str, ...] = (
    "`is_no_strait_closure`",
    "`is_no_subventions`",
    "`is_no_tariffs`",
    "`is_no_tolls`",
    "`is_non_colonization_agreement`",
    "`is_non_piracy_agreement`",
    "`is_prohibit_goods_trade_with_world_market`",
    "`is_ship_transfer`",
    "`is_strait_access`",
    "`is_support_independence`",
    "`is_toll_exemption`",
    "`is_trade_privilege`",
    "`is_transit_rights`",
    "`is_treaty_port`",
    "`target_subjects_as_input`",
)

#: `war_goal_types` 的 `settings` 表里作者选定的 42 行。
_SETTINGS_LEFT: tuple[str, ...] = (
    "`require_target_be_part_of_war`",
    "`validate_conflicts_war_goals_all`",
    "`skip_build_list`",
    "`can_add_for_other_country`",
    "`conflicts_with_make_subject`",
    "`requires_interest`",
    "`validate_conflicts_make_subject`",
    "`validate_subject_relation`",
    "`assent_required`",
    "`turns_into_subject`",
    "`conflicts_with_annex_state`",
    "`conflicts_with_country_creation`",
    "`validate_conflicts_conquer_state`",
    "`annexes_entire_state`",
    "`conflicts_with_annex_country`",
    "`conflicts_with_existing_subject`",
    "`country_creation`",
    "`has_other_stakeholder`",
    "`overlord_is_stakeholder`",
    "`targets_enemy_subject`",
    "`validate_conflicts_existing_subject`",
)
_SETTINGS_RIGHT: tuple[str, ...] = (
    "`validate_conflicts_annex_country`",
    "`validate_conflicts_war_goals_holder`",
    "`validate_contain_threat`",
    "`validate_force_nationalization`",
    "`validate_foreign_investment_rights`",
    "`validate_formation_candidate_self`",
    "`validate_formation_candidate_target`",
    "`validate_increase_autonomy`",
    "`validate_independence`",
    "`validate_join_power_bloc`",
    "`validate_regime_change`",
    "`validate_sole_formation_candidate`",
    "`validate_take_treaty_port`",
    "`preserve_on_switching_sides`",
    "`targets_enemy_claims`",
    "`can_target_decentralized`",
    "`debug`",
    "`annexes_entire_country`",
    "`validate_colonization_rights`",
    "`validate_revoke_claims`",
    "`validate_target_not_treaty_port`",
)


def _value_file_rows(
    dir_rel: str, keys: tuple[str, ...], col: int
) -> list[tuple[str, dict[int, str]]]:
    """两栏并排的「值 → 文件数」表：键去反引号后按**文本出现**数文件。"""
    words = [norm_key(k) for k in keys]
    counts = word_file_counts(dir_rel, words)
    return [(k, {col: str(counts[norm_key(k)])}) for k in keys]


def treaty_flag_rows(keys: tuple[str, ...], col: int) -> list[tuple[str, dict[int, str]]]:
    return _value_file_rows("common/treaty_articles", keys, col)


def war_goal_setting_rows(keys: tuple[str, ...], col: int) -> list[tuple[str, dict[int, str]]]:
    return _value_file_rows("common/war_goal_types", keys, col)


def contestion_rows() -> list[tuple[str, dict[int, str]]]:
    """`war_goal_types` 的 `contestion_type` 取值 → 文件数（9 个值）。"""
    base = config.GAME / "common" / "war_goal_types"
    counter: Counter[str] = Counter()
    for path in sorted(base.rglob("*.txt")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for m in re.finditer(r"contestion_type\s*=\s*([a-z_]+)", text):
            counter[f"`{m.group(1)}`"] += 1
    return [(k, {1: str(v)}) for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]


def subject_field_rows() -> list[tuple[str, dict[int, str]]]:
    """`subject_types` 的 28 个字段 → **出现次数**。

    这一列在文档里写作「使用文件数」，但该目录只有 **1 个文件**、里面有 9 个
    subject type 条目 —— 作者写下的 9 只可能是**条目级出现次数**。
    表头已随之改成「出现次数」（口径说不清比数字错更难查）。
    """
    counter: Counter[str] = Counter()
    base = config.GAME / "common" / "subject_types"
    for path in sorted(base.rglob("*.txt")):
        pf = parse_cached(path)
        for a in pf.top_assignments:
            if a.is_variable or not isinstance(a.value, Block):
                continue
            for sub in a.value.assignments():
                counter[sub.key] += 1
    return [(k, {1: str(v)}) for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]


def travel_network_rows() -> list[tuple[str, dict[int, str]]]:
    """`travel_network\\naval_network.txt` 的 8 个键（顶层 + 匿名块内的）。

    **只有这张表用千位逗号**：它是 doc 16 里唯一出现过万级数字的表
    （``6,641`` / ``7,191``），作者在这里写了逗号，而本篇其余表的数字都在三位数以内、
    一律不写分隔符。跟着文档自己的写法走，diff 里才不会混进纯格式差异。
    """
    counter = all_field_occurrences("common/travel_network")
    order = ("nodes", "connections", "province", "type", "x", "y", "from", "to")
    return [(k, {1: f"{counter[k]:,}"}) for k in order if k in counter]


def _spec(
    name: str,
    header: str,
    cells: Callable[[], list[tuple[str, dict[int, str]]]],
    *,
    key_column: int = 0,
    occurrence: int = 0,
) -> KeyedTableSpec:
    return KeyedTableSpec(
        name=name,
        header=header,
        cells=cells,
        append_new=False,
        key_column=key_column,
        occurrence=occurrence,
    )


def doc_table_specs() -> list[KeyedTableSpec]:
    """doc 16 剩下的八张表（10 条 spec：两张两栏并排的左右各一条）。"""
    return [
        _spec("doc16 scope 记号", "| 记号 | 出现次数 | 出现文件数 |", marker_rows),
        _spec("doc16 treaty_articles AI 键", "| 键 | 使用文件数 | 备注 |", treaty_ai_rows),
        _spec("doc16 treaty_articles 未记载键", "| 键 | 文件数 | 实测值 |", treaty_missing_rows),
        _spec(
            "doc16 treaty flags 左栏",
            "| flag | 文件数 | 文档 | | flag | 文件数 | 文档 |",
            lambda: treaty_flag_rows(_TREATY_FLAGS_LEFT, 1),
        ),
        _spec(
            "doc16 treaty flags 右栏",
            "| flag | 文件数 | 文档 | | flag | 文件数 | 文档 |",
            lambda: treaty_flag_rows(_TREATY_FLAGS_RIGHT, 4),
            key_column=3,
        ),
        _spec(
            "doc16 subject_types 字段",
            "| 键 | 出现次数 | 类型 | 备注 |",
            subject_field_rows,
        ),
        _spec(
            "doc16 war_goal settings 左栏",
            "| setting | 文件数 | 文档 | | setting | 文件数 | 文档 |",
            lambda: war_goal_setting_rows(_SETTINGS_LEFT, 1),
        ),
        _spec(
            "doc16 war_goal settings 右栏",
            "| setting | 文件数 | 文档 | | setting | 文件数 | 文档 |",
            lambda: war_goal_setting_rows(_SETTINGS_RIGHT, 4),
            key_column=3,
        ),
        _spec("doc16 war_goal contestion_type", "| 值 | 文件数 |", contestion_rows),
        _spec(
            "doc16 travel_network 字段",
            "| 键 | 出现次数 | 说明 |",
            travel_network_rows,
            # ⚠️ 这个表头在 doc 16 里出现 **4 次**（同表头的表在别的节里也有），
            # 本节那张是**第 4 张**（0 基下标 3）。写成 0 会把规格指到别处的表上：
            # `v3 tables` 照样报「一致」（那几张表的键一个都匹配不上 → 原样保留），
            # 只有「每一行都有人认领」会把它抓出来 —— 实测就是这么发现的。
            occurrence=3,
        ),
    ]


__all__ = [
    "NOT_GENERATED",
    "doc_table_specs",
    "marker_rows",
    "subject_field_rows",
    "travel_network_rows",
    "treaty_flag_rows",
    "war_goal_setting_rows",
]
