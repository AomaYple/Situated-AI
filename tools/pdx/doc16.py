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

下半部分不是「表」，而是那批**只读口径的提取函数**
------------------------------------------------
它们服务于 §0 与 §4 里那几组「文档说了个数、而数法本身才是结论」的数字
（33 个目录 / 205 个文件、`pact` 块 36 vs 28、`kind` 33 vs 28、`traits` 517 vs 514）。
每一组都有**两种都说得通**的数法，差在口径上，不在算术上：

* **官方 `.md` 是散文，不是 PDX 脚本。** `pact` 块里的 `key = value` 只是示意行：
  同一行还挂着 `#` 注释，块里还有大段自然语言，值常写成 `bool` / `<a|b|c>`。
  喂给解析器会**凭空多出** ``source_country`` / ``target_country`` / ``mutual``
  （它们只是 `a|b|c` 里的词），又**丢掉** ``second_country_gets_income_transfer``
  （那一行整行被当成散文）；走 :mod:`pdx.lexer` 的 token 深度则得 29 个键。
  所以下面这两个 md 读取函数**只用行级正则**，不经词法器。
* **「出现次数」不等于「有多少处写它」。** `map_data\\state_regions\\*.txt` 里
  `traits` 出现 **517** 次，但只有 **514** 个州块写了它 —— `STATE_ZANZIBAR` /
  `STATE_TOMSK` / `STATE_TUVA` 各写了**两个** `traits` 块。两个数都对，
  写进文档的必须是**口径说清楚的那一个**。
* **子串计数会把将来出现的词吞掉。** `traits` / `state_traits` 现在一个是 517、
  一个是 0，所以 :func:`pdx.usage.word_stats` 的 ``text.count`` 恰好给出同一个数；
  等哪天原版写下 `state_traits = {`，子串计数就会把它算进 `traits` ——
  而文档那句「键名是 `traits`，不是 `state_traits`」正是靠这两个数**分开**才成立。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .doc_tables import KeyedTableSpec, TableSpec, norm_key
from .model import Block
from .usage import (
    all_field_occurrences,
    field_occurrences,
    field_value_counts,
    file_definition_counts,
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

# ────────────────────── §0：那 33 个目录，与它们的四类计数 ──────────────────────

#: doc 16 §0 覆盖的 **33 个 `common\` 一级目录**，按文档自己的分组存放。
#:
#: **必须硬编码**：这 33 个是作者按「mod 作者会碰的外交 / 军事 / 地图数据」选定的，
#: 没有任何自然谓词能从 `common\` 的 136 个子目录里把它挑出来 —— 写一条
#: 「名字里带 diplomacy 的目录」之类的规则只会得到另一组目录，而且游戏升级时
#: 会**静默变化**：文档里的 33 跟着漂，没人知道为什么。
#: 顺序 = §0 表格的行序（外交 9 → 军事 17 → 地图 7），**不是**字母序。
DOC16_GROUPS: dict[str, tuple[str, ...]] = {
    "外交": (
        "diplomatic_actions",
        "diplomatic_plays",
        "diplomatic_catalysts",
        "diplomatic_catalyst_categories",
        "treaty_articles",
        "subject_types",
        "opinion_modifiers",
        "proposal_types",
        "acceptance_statuses",
    ),
    "军事": (
        "war_goal_types",
        "combat_unit_types",
        "combat_unit_groups",
        "combat_unit_experience_levels",
        "ship_types",
        "ship_groups",
        "ship_modifications",
        "ship_modification_slots",
        "ship_veterancy_levels",
        "commander_orders",
        "commander_ranks",
        "mobilization_options",
        "mobilization_option_groups",
        "battle_conditions",
        "naval_battle_conditions",
        "naval_mission_types",
        "military_formation_flags",
    ),
    "地图": (
        "strategic_regions",
        "state_traits",
        "terrain",
        "terrain_manipulators",
        "strait_definitions",
        "geographic_regions",
        "travel_network",
    ),
}

#: 33 个目录的**扁平**形式（§0 的行序）。由 :data:`DOC16_GROUPS` 拼出 ——
#: 分成两份常量写会漂，而漂了之后「33」这个数字照样对得上（少一个多一个都还是 33）。
DOC16_DIRS: tuple[str, ...] = tuple(d for dirs in DOC16_GROUPS.values() for d in dirs)

#: :func:`group_file_counts` 接受的四种口径。
_GROUP_COUNT_KINDS: tuple[str, ...] = ("dirs", "files", "txt", "md")


def dir_file_counts(dir_rel: str) -> dict[str, int]:
    """一个目录（路径相对 `game\\`）的**递归**计数：``txt`` / ``md`` / ``files``。

    只做 ``rglob`` + ``is_file()``，**不解析内容**，所以能用在任意目录上。
    实测 ``common/diplomatic_actions`` = ``{"txt": 48, "md": 1, "files": 49}``。

    目录不存在时**抛异常**而不是返回 0：这个函数是 §0 那 33 行数字的来源，
    静默返回 0 会让整行数字在文档里留在原处、只在总数上少几个。
    """
    base = config.GAME / dir_rel
    if not base.is_dir():
        raise FileNotFoundError(f"目录不存在：{base}")
    files = [p for p in base.rglob("*") if p.is_file()]
    return {
        "txt": sum(1 for p in files if p.suffix == ".txt"),
        "md": sum(1 for p in files if p.suffix == ".md"),
        "files": len(files),
    }


def group_file_counts(kind: str) -> int:
    """§0 那 33 个目录的合计计数，``kind ∈ {"dirs", "files", "txt", "md"}``。

    实测 **33 / 205 / 182 / 23**（= `dirs` / `files` / `txt` / `md`）。

    ⚠️ ``dirs`` 是**顶层**目录数（:data:`DOC16_DIRS` 的条目数），不是递归的：
    按「子目录也数」会得到 **34** —— 多出来的那个是
    ``terrain_manipulators\\provinces\\``（374,983 B 的 `allowed_provinces.txt`
    所在的子目录，见 §0 的注 1）。文档那句「33 个子目录」说的是前者；
    两种数法都能自圆其说，所以口径写死在这里。
    """
    if kind not in _GROUP_COUNT_KINDS:
        raise ValueError(f"kind 只能是 {_GROUP_COUNT_KINDS} 之一，收到 {kind!r}")
    if kind == "dirs":
        return len(DOC16_DIRS)
    return sum(dir_file_counts(f"common/{d}")[kind] for d in DOC16_DIRS)


def group_dirs_without_md() -> list[str]:
    """§0 那 33 个目录里**一个官方 `.md` 都没有**的目录名（实测 10 个）。

    口径：目录**递归**里没有任何 ``.md`` 文件（不是「顶层没有」——
    这两个口径在本范围里恰好一致，但 `terrain_manipulators\\provinces\\` 说明
    子目录是存在的）。这 10 个目录的字段表**全部**来自 `.txt` 机械提取，
    没有官方文档可对照 —— §0 的「有官方文档」列写 ❌ 的就是它们。

    顺序 = :data:`DOC16_DIRS` 的顺序（§0 行序）。不用字母序：字母序会把
    「军事 5 个」与「地图 3 个」混在一起，而文档是按组叙述的。
    """
    out: list[str] = []
    for name in DOC16_DIRS:
        base = config.GAME / "common" / name
        if not any(p.is_file() for p in base.rglob("*.md")):
            out.append(name)
    return out


#: `common/diplomatic_actions/` 是 §2 那张「scope 记号」表的样本范围（48 个 `.txt`）。
_DIPLOMATIC_DIR = "common/diplomatic_actions"
_DIPLOMATIC_MD = "diplomatic_action.md"
#: 同一个 `.md` 的 **game 相对路径** —— :func:`md_block_keys` 要的是这一种。
_DIPLOMATIC_MD_REL = f"{_DIPLOMATIC_DIR}/{_DIPLOMATIC_MD}"

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


# ──────────────── 官方 `.md` 的行级提取（散文，不是 PDX 脚本）────────────────

#: 官方文档里那两个「文档有 / 数据有」差集用到的路径与标题。
_WAR_GOAL_DIR = "common/war_goal_types"
_WAR_GOAL_MD_REL = f"{_WAR_GOAL_DIR}/war_goal_types.md"
_WAR_GOAL_KIND_SECTION = "List of Kinds"

#: §4.2.1 那句「键名是 `traits`，不是 `state_traits`」的两个词。
_STATE_REGION_DIR = "map_data/state_regions"
_STATE_REGION_WORDS: tuple[str, ...] = ("traits", "state_traits")

#: §7.3 那张表里的战略区（**不是** `map_data\\state_regions\\`，两者只差一个词）。
_STRATEGIC_REGION_DIR = "common/strategic_regions"


def _md_lines(md_rel: str) -> list[str]:
    """官方 `.md` 的正文行。``md_rel`` 相对 `game\\`，且**要带 `.md` 后缀**。

    ``utf-8-sig``：官方 `.md` 里就有带 BOM 的（``war_goal_types.md`` 是），
    不剥掉的话 ``^#`` 判标题在第一行当场失配 —— 而失配的表现是「这个文件里
    一个标题都没有」，不是报错。
    """
    path = config.GAME / md_rel
    if not path.is_file():
        raise FileNotFoundError(f"官方 .md 不存在：{path}（md_rel 要相对 game\\，且带后缀）")
    return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()


def md_block_keys(md_rel: str, block: str) -> list[str]:
    """官方 `.md` 里 ``block = { … }`` 块**下一层**的键名（按出现顺序）。

    ⚠️ **官方 `.md` 是散文，不是 PDX 脚本**，所以这里既不用
    :func:`pdx.parser.parse_text`（实测会凭空多出 ``source_country`` /
    ``target_country`` / ``mutual`` —— 它们只是 ``<a|b|c>`` 里的词 ——
    又丢掉 ``second_country_gets_income_transfer``，因为那一行整行像自然语言），
    也不用 :mod:`pdx.lexer` 走 token 深度（实测得 29 个键）。规则只有三条：

    1. ``^\\s*<block>\\s*=\\s*\\{`` 定位块的**开头那一行**；
    2. 逐行**先截断到第一个 ``#``**（官方 `.md` 把说明写在 ``#`` 后面，
       而块内注释行本身就是 ``# `` 开头的），再按行累计花括号深度；
    3. 深度 == 1 时用 ``^\\s*([A-Za-z_]\\w*)\\s*=`` 收键名，深度回到 0 即停。

    实测 ``("common/diplomatic_actions/diplomatic_action.md", "pact")``
    → **28** 个键。块或文件找不到时**抛异常**：返回空表会让「上一层的表少了一半」
    以「0 行」的形式静默通过。
    """
    lines = _md_lines(md_rel)
    opener = re.compile(rf"^\s*{re.escape(block)}\s*=\s*\{{")
    start = next((i for i, line in enumerate(lines) if opener.match(line)), None)
    if start is None:
        raise ValueError(f"{md_rel} 里找不到 {block} = {{ 开头的那一行")
    keys: list[str] = []
    depth = 0
    for line in lines[start:]:
        code = line.split("#", 1)[0]
        if depth == 1:
            m = re.match(r"^\s*([A-Za-z_]\w*)\s*=", code)
            if m:
                keys.append(m.group(1))
        depth += code.count("{") - code.count("}")
        if depth <= 0:
            break
    return keys


def md_bullet_values(md_rel: str, section: str) -> list[str]:
    """官方 `.md` 某个标题下形如 ``- 值`` 的条目（按出现顺序）。

    标题用 ``^#+\\s*<section>\\s*$`` 匹配（级别不写死：这里要的
    ``### List of Kinds`` 是三级，同一份 md 里别的清单是二级），条目用
    ``^\\s*-\\s*([A-Za-z_]\\w*)\\s*$`` —— **整行只有 `-` 加一个词**。
    项下面那句说明是**制表符缩进的自然语言**（``Converted to law commitment…``），
    天然不是这一形状，所以不会混进来。

    ⚠️ **遇到下一个 ``^#`` 标题即停**：``war_goal_types.md`` 里另有两张
    ``- 项`` 清单（settings / contestion types），不停会把它们一起抓走
    （实测 28 → 90）。实测
    ``("common/war_goal_types/war_goal_types.md", "List of Kinds")`` → **28** 个
    （含末尾那个 ``custom``）。
    """
    lines = _md_lines(md_rel)
    head = re.compile(rf"^#+\s*{re.escape(section)}\s*$")
    start = next((i for i, line in enumerate(lines) if head.match(line)), None)
    if start is None:
        raise ValueError(f"{md_rel} 里找不到标题 {section!r}")
    out: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        m = re.match(r"^\s*-\s*([A-Za-z_]\w*)\s*$", line)
        if m:
            out.append(m.group(1))
    return out


def pact_undocumented_keys() -> list[str]:
    """官方 `.md` 的 ``pact`` 块**没写**、而原版数据里有的字段（实测 21 个）。

    两侧口径**故意不同**，差集才是要抓的东西：

    * 数据侧 = ``field_occurrences("common/diplomatic_actions", within="pact")``
      → **36** 个字段（``pact = { … }`` 块内的字段名，跨文件累加）；
    * 文档侧 = :func:`md_block_keys` 的 ``pact`` 块 → **28** 个键。

    交集 15、文档独有 13、数据独有 **21**（本函数的返回值，字母序）——
    也就是说官方那份 `.md` 只写了实际字段的四成左右。数据独有的 21 个是：
    ``exempt_from_service`` / ``first_modifier`` / ``has_junior_participant`` /
    ``infamy_affects_maintenance`` / ``is_colonization_rights`` / ``is_embargo`` /
    ``is_foreign_investment_rights`` / ``is_hostile`` / ``is_humiliation`` /
    ``is_rivalry`` / ``is_two_sided_pact`` / ``maintenance_paid_by`` /
    ``market_owner`` / ``relations_improvement_max`` / ``relations_improvement_min`` /
    ``relations_progress_per_day`` / ``second_foreign_anti_country_lobby_member_modifier`` /
    ``second_foreign_pro_country_lobby_member_modifier`` / ``second_modifier`` /
    ``show_in_outliner`` / ``subject_type``。
    """
    data = set(field_occurrences(_DIPLOMATIC_DIR, within="pact"))
    doc = set(md_block_keys(_DIPLOMATIC_MD_REL, "pact"))
    return sorted(data - doc)


def war_goal_kind_diff() -> list[str]:
    """``kind`` 在数据里有、官方 `.md` 的 `List of Kinds` 里没有的取值（实测 6 个）。

    33（``field_value_counts("common/war_goal_types", "kind")``）
    减去 28（:func:`md_bullet_values`）⇒ **6** 个 txt-only：
    ``break_enforced_treaties`` / ``demand_no_strait_closure`` / ``demand_no_tolls`` /
    ``demand_strait_access`` / ``demand_toll_exemption`` / ``release_as_subject``。
    这 6 个原版**都在用**，只是官方清单没跟着更新 —— 与 :func:`pact_undocumented_keys`
    是同一个形状的两个样本（一个 21/36、一个 6/33，说明「文档写了多少」并不稳定）。
    """
    data = set(field_value_counts(_WAR_GOAL_DIR, "kind"))
    doc = set(md_bullet_values(_WAR_GOAL_MD_REL, _WAR_GOAL_KIND_SECTION))
    return sorted(data - doc)


def strategic_region_field_counts() -> Counter[str]:
    """``common/strategic_regions/`` 的字段 → **出现次数**。

    实测 ``states 142 / capital_province 34 / map_color 36 / graphical_culture 23``
    —— §7.3 那句「142 个区域里只有 34 个有 ``capital_province``、36 个有
    ``map_color``」用的就是这四个数。

    ⚠️ 来源是 ``common\\strategic_regions\\``（**战略区**，7 个文件）
    **不是** ``map_data\\state_regions\\``（州区域，17 个文件）：两个目录名只差
    一个词，写错照样能数出「4 个字段」，只是四个数字全不一样（``states`` 会变成
    781 个州块）。§0 的表里这两个目录也各占一行。
    """
    return field_occurrences(_STRATEGIC_REGION_DIR)


def state_region_word_counts() -> Counter[str]:
    """``map_data/state_regions/*.txt`` 里 :data:`_STATE_REGION_WORDS` 的**带词界**出现次数。

    实测 ``traits 517`` / ``state_traits 0`` —— §4.2.1 那句「键名是 ``traits``，
    不是 ``state_traits``」的两个数就是它们。

    ⚠️ 不能用 :func:`pdx.usage.word_stats`：那是 ``text.count`` 的**子串**计数，
    现在两个数恰好相等只是因为 ``state_traits`` 一个都没有；等哪天原版
    （或我们自己的 fixture）写下 ``state_traits = { … }``，子串计数会把它并进
    ``traits`` —— 而这两个数**分开**正是那条结论成立的证据。

    ⚠️ 517 是「**出现次数**」，不是「有多少个州有特性」：实测只有 **514** 个顶层州块
    写了 ``traits``（见 :func:`state_regions_with_traits`），多出来的 3 处是
    ``STATE_ZANZIBAR`` / ``STATE_TOMSK`` / ``STATE_TUVA`` 各写了**两个** ``traits`` 块。
    """
    base = config.GAME / _STATE_REGION_DIR
    if not base.is_dir():
        raise FileNotFoundError(f"目录不存在：{base}")
    patterns = {w: re.compile(rf"\b{w}\b") for w in _STATE_REGION_WORDS}
    counter: Counter[str] = Counter()
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for word, pattern in patterns.items():
            counter[word] += len(pattern.findall(text))
    return counter


def state_regions_with_traits() -> int:
    """``map_data/state_regions/`` 里**写了 `traits` 块的州区域个数**（实测 514）。

    与 :func:`state_region_word_counts` 的 517 是同一份数据的两种口径，
    差在「一个州写了两个 ``traits`` 块」这件事上（实测 3 个州如此）。
    这个函数数的是**州块**，所以它才是「有多少个州有州特性」。
    """
    base = config.GAME / _STATE_REGION_DIR
    if not base.is_dir():
        raise FileNotFoundError(f"目录不存在：{base}")
    total = 0
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        pf = parse_cached(path)
        for a in pf.top_assignments:
            if a.is_variable or not isinstance(a.value, Block):
                continue
            if any(sub.key == "traits" for sub in a.value.assignments()):
                total += 1
    return total


#: §4.2.1 那张「17 个 state_regions 文件的 traits 使用量」的表头。
#:
#: 它是**两栏并排**的排版（左右各一组「文件 / traits= / state region 数」），
#: 所以只能走整表生成（``TableSpec``），不能按键更新某一列。
#: 这张表此前是手写的：内容 30 个数全靠人工，实测已经错了 1 个
#: （``99_seas.txt`` 的州数写着 104，实为 106）—— 手写的机械表就该变成生成的。
STATE_REGION_TABLE = "| 文件 | traits= | state region 数 | | 文件 | traits= | state region 数 |"


def _state_region_per_file() -> list[tuple[str, int, int]]:
    """``[(文件名, traits 出现次数, 顶层州块数), …]``，按文件内顺序（自然序）。"""
    base = config.GAME / _STATE_REGION_DIR
    if not base.is_dir():
        raise FileNotFoundError(f"目录不存在：{base}")
    pattern = re.compile(r"\btraits\b")
    out: list[tuple[str, int, int]] = []
    for path in sorted(b for b in base.glob("*.txt") if b.is_file()):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        blocks = sum(
            1
            for a in parse_cached(path).top_assignments
            if not a.is_variable and isinstance(a.value, Block)
        )
        out.append((path.name, len(pattern.findall(text)), blocks))
    return out


def state_region_rows() -> list[str]:
    """§4.2.1 那张表的全部数据行（两栏并排，左栏多一行时空出右栏）。"""
    per_file = _state_region_per_file()
    half = (len(per_file) + 1) // 2
    left, right = per_file[:half], per_file[half:]
    rows: list[str] = []
    for i, (name, traits, regions) in enumerate(left):
        cells = [f"`{name}`", str(traits), str(regions)]
        if i < len(right):
            rname, rtraits, rregions = right[i]
            cells += ["", f"`{rname}`", str(rtraits), str(rregions)]
        else:
            cells += ["", "", "", ""]
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def action_file_definition_counts() -> dict[str, int]:
    """``common/diplomatic_actions/`` 的**逐文件顶层定义数**（``@变量`` 不计）。

    直接转发 :func:`pdx.usage.file_definition_counts`，口径与理由都在那里。
    实测 48 个键、``43_subjects_handle_states.txt`` = **3**；该目录递归
    ``.txt`` 数也是 **48**（另有 1 个官方 `.md`，见 :func:`dir_file_counts`）。

    ⚠️ 字典键是**文件名**（不是相对路径）—— ``len(...)`` 等于「递归 `.txt` 数」
    **只有在目录里没有重名文件时才成立**。本目录实测两者都是 48，但别把这条
    当成惯例：要那个数请用 ``dir_file_counts("common/diplomatic_actions")["txt"]``。
    """
    return file_definition_counts(_DIPLOMATIC_DIR)


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


def doc_table_specs() -> list[TableSpec | KeyedTableSpec]:
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
        TableSpec(
            name="doc16 state_regions 逐文件",
            header=STATE_REGION_TABLE,
            rows=state_region_rows,
        ),
    ]


__all__ = [
    "DOC16_DIRS",
    "DOC16_GROUPS",
    "NOT_GENERATED",
    "action_file_definition_counts",
    "dir_file_counts",
    "doc_table_specs",
    "group_dirs_without_md",
    "group_file_counts",
    "marker_rows",
    "md_block_keys",
    "md_bullet_values",
    "pact_undocumented_keys",
    "state_region_word_counts",
    "state_regions_with_traits",
    "strategic_region_field_counts",
    "subject_field_rows",
    "travel_network_rows",
    "treaty_flag_rows",
    "war_goal_kind_diff",
    "war_goal_setting_rows",
]
