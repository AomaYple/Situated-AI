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

import ast
import re
from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import TYPE_CHECKING

from . import config, docs_mirror
from .ai import semantic_counts, shape_counts, strategy_field_count
from .cache import parse_cached
from .defines import kind_counts, layer_diff
from .doc04 import event_definition_count
from .doc14 import (
    buy_package_entry_count,
    buy_package_goods_categories,
    hyphen_key_dir_counts,
    wealth_1_goods_categories,
)
from .doc15 import (
    ideology_field_split,
    lobby_appeasement_usable,
    religion_heritage_values,
    stance_total,
)
from .doc16 import (
    group_dirs_without_md,
    group_file_counts,
    pact_undocumented_keys,
    state_region_word_counts,
    strategic_region_field_counts,
    war_goal_kind_diff,
)
from .doc17 import (
    block_item_count,
    block_prefix_count,
    dna_observation,
    fallback_yes_count,
    field_occurrence,
    files_without_defs,
    flag_comment_brace_lines,
    gene_block_names,
    loc_suffix_count,
    overview_key_count,
    overview_txt_count,
)
from .doc18 import country_effect_file_count
from .extract import extract_dir
from .game_root import checksum_targets_grouped, paths_settings
from .localization import (
    getcustom_stats,
    gui_sprite_lines,
    texticon_counts,
    yml_unique_name_count,
)
from .markers import MarkerFix, all_markers, apply_fixes, marker_ids_by_doc
from .model import Block
from .modifiers import digit_leading_entries, indented_top_entries, modifier_type_suffixes
from .mods import aggregate_prefixes, analyse_all, vanilla_prefix_count
from .scan import count_files
from .snapshot import SNAPSHOT_DIR, Snapshot
from .usage import (
    ai_script_values_key_stats,
    ai_script_values_referenced,
    count_key_assignments,
    field_missing,
    field_occurrences,
    field_value_counts,
    file_definition_counts,
    file_line_count,
)
from .verify_claims_1152 import CLAIMS, Claim
from .version_contracts import CURRENT_CONTRACT, require_current

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["CLAIMS", "Claim"]


# ── 数据结构 ────────────────────────────────────────────────
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
def _dir_blocks(target: str) -> int:
    """`common/<target>` 下各文件的**顶层块**总数（``@变量`` 不计）。

    用途：文档里那批「共 N 个 JE / 按钮 / 进度条 / SGUI」的**散文数字** ——
    它们与 :func:`pdx.usage.file_definition_counts` 是同一个口径
    （``blocks_only=True``：只数 ``键 = {``，跳过标量赋值）。
    实测 `script_values` 两种口径差 209 个，所以这里必须与生成表一致。
    """
    return sum(file_definition_counts(f"common/{target}", blocks_only=True).values())


def _modifier_suffix(target: str) -> int:
    """`modifier_type_definitions\\` 里以 ``_<target>`` 结尾的键数。

    文档 §3.x 的「后缀分布」那段散文（``_add`` 1635 / ``_mult`` 626 / …）
    就是这四个数 —— 它们一直没人看守，而键数会随版本变。
    """
    base = config.GAME / "common" / "modifier_type_definitions"
    suffix = f"_{target}"
    total = 0
    for path in sorted(base.rglob("*.txt")):
        pf = parse_cached(path)
        total += sum(1 for a in pf.top_assignments if not a.is_variable and a.key.endswith(suffix))
    return total


def _modifier_suffix_other(target: str) -> int:
    """尾段**不在**``target``（逗号分隔）里的修饰符键数 —— doc 05 那句「另有 9 个」。

    「其它」是个否定口径，所以判据写在 target 里而不是函数名里：
    将来若版本新增 ``_foo`` 一族，「已知尾段」清单要跟着改，
    改的地方应当和数字在同一行（断言表），而不是散在实现里。
    """
    known = {s.strip() for s in target.split(",") if s.strip()}
    return sum(n for suffix, n in modifier_type_suffixes().items() if suffix not in known)


def _static_digit_entries(_target: str) -> int:
    """``static_modifiers`` 里以**数字开头**的顶层键数（doc 05 的 3 个 ``1848_*``）。"""
    return len(digit_leading_entries())


def _static_indented_entries(_target: str) -> int:
    """``static_modifiers`` 里**行首带缩进**的顶层键数（doc 05 的 7 个）。

    缩进在 PDX 里没有语义 —— 所以「顶层」由解析器的花括号深度判定，
    缩进必须回原文看那一行（两个口径缺一不可，见
    :func:`pdx.modifiers.indented_top_entries`）。
    """
    return len(indented_top_entries())


def _field_missing(target: str) -> int:
    """``<目录>:<字段>`` —— 目录里**没写**该字段的顶层条目数。

    doc 05 的「原版有 31 个键完全没写 ``decimals``、1479 个没写 ``percent``」。
    """
    dir_rel, _, field = target.partition(":")
    return field_missing(f"common/{dir_rel}", field)


def _file_nested_key_count(target: str) -> int:
    """``<相对 game 的文件>:<键>`` —— 该键在文件里**任意深度**被赋值的次数。

    doc 06 的「``fonts.font`` 里共 53 个 ``languages`` 块」：它们藏在
    ``fontfiles`` 里面，不是顶层键，而缩进没有语义（行正则会多算 1 个 —— 注释里也有这个词）。
    """
    rel, _, key = target.partition(":")
    path = config.GAME / rel
    return count_key_assignments(path, key) if path.is_file() else 0


def _texticon_definitions(_target: str) -> int:
    """``gui/*.gui`` 里 ``^texticon = {`` 的行数（doc 06 的 432）。

    口径见 :data:`pdx.localization.TEXTICON_RE`：文档自己写明了这条判据，
    而同一份数据在「任意缩进」口径下是 436、解析器顶层块口径下是 437。
    """
    return sum(texticon_counts().values())


def _loc_yml_unique_names(_target: str) -> int:
    """``localization`` 下 ``.yml`` 按**文件名去重**后的个数（doc 06 的 1,855）。"""
    return yml_unique_name_count()


def _defines_untaken(_target: str) -> int:
    """Jomini 层里**未被 game 层接管**的 defines 文件数（doc 05 的 15）。

    不能拿 ``extract_all_defines`` 的 ``per_file`` 相减：那个只收
    「含大写命名空间块」的文件，会漏掉整块被注释的
    ``00_audio_persistent_objects.txt``（得 14）。见 :func:`pdx.defines.layer_diff`。
    """
    return len(layer_diff()[1])


def _file_bytes(target: str) -> int:
    """安装树里单个文件的字节数（doc 08 的 ``achievement_groups.txt`` = 4,277 B）。"""
    path = _tree_path(target)
    return path.stat().st_size if path.is_file() else 0


def _file_line_count(target: str) -> int:
    """安装树里某个文件的**行数**（``splitlines`` 口径）。

    doc 05 的「``00_ai.txt`` 共 1311 行」、doc 06 的「``modifiers_l_english.yml``
    全长只有 3 行」、doc 19 的「``paths_checksummed.settings`` 只有 3 行」、
    以及 doc 04 与索引页引用的「``checksum_manifest.txt`` 共 22 行」——
    这类句子原先**一条都没人看守**：散文盘点只认「共 N 个」与纯粗体，
    写成「共 N 行」的从口径里漏掉了（doc 04 §4.6 的 682 就是这么活下来的）。
    """
    path = _tree_path(target)
    return file_line_count(path) if path.is_file() else 0


def _defines_kind_total(target: str) -> int:
    """defines 全部命名空间里某一类参数的合计（``target`` = 标量 / 内联列表 / 嵌套块）。

    doc 05 §1.2 那句「这类内联列表参数全库共 N 条」原先没人看守，
    而 §0.3 的合计行是生成表 —— 正文与表格因此可以各自漂移。
    """
    idx = {"标量": 0, "内联列表": 1, "嵌套块": 2}[target]
    total = 0
    for f in (config.GAME / "common" / "defines").rglob("*.txt"):
        for a in parse_cached(f).namespace_blocks():
            assert isinstance(a.value, Block)
            total += _block_param_kinds(a.value)[idx]
    return total


def _paths_settings_mappings(_target: str) -> int:
    """``paths.settings`` 的映射条目数（doc 19 的 39 条）。

    正文那句「共 39 条映射，分 3 组」里的 39 就是它；三张分表由 ``v3 tables``
    生成，但**合计**原先只在正文里，没有看守（早期工具里写的是 32）。
    """
    return len(paths_settings())


def _file_definitions(target: str) -> int:
    """``<目录>:<文件名>`` —— 该文件的顶层定义数（doc 16 的「48 个 .txt 里那个有 3 个」）。

    「48 个文件里某一个有几个定义」这种句子，靠目录合计是看不出来的 ——
    合计对得上、分布错了照样是错的。
    """
    dir_rel, _, name = target.partition(":")
    return file_definition_counts(dir_rel).get(name, -1)


def _doc16_group_files(target: str) -> int:
    """doc 16 §0 那 33 个目录的分组计数（``target`` = ``dirs`` / ``files`` / ``txt`` / ``md``）。

    目录清单是**作者选定**的一组（外交 9 + 军事 17 + 地图 7），
    ``common\\`` 下 136 个一级目录里没有任何自然谓词能圈出这 33 个 ——
    所以清单写在 :data:`pdx.doc16.DOC16_DIRS`，这里只做计数。
    """
    return group_file_counts(target)


def _doc16_group_no_md(_target: str) -> int:
    """那 33 个目录里**没有官方 ``.md``** 的个数（doc 16 的 10）。"""
    return len(group_dirs_without_md())


def _md_block_undocumented(_target: str) -> int:
    """官方 `.md` 的 ``pact`` 块里**没列**、而游戏数据里在用的字段数（doc 16 的 21）。

    这是**唯一**一处「官方文档 vs 实际数据」的字段差集，所以不假装通用：
    口径见 :func:`pdx.doc16.pact_undocumented_keys`（官方 md 的块必须按行数花括号，
    直接喂解析器会凭空多出 ``source_country`` / ``target_country`` / ``mutual``，
    还会漏掉 ``second_country_gets_income_transfer``）。
    """
    return len(pact_undocumented_keys())


def _md_bullet_diff(_target: str) -> int:
    """官方 ``war_goal_types.md`` 的 kind 列表**漏掉**的数据取值个数（doc 16 的 6）。

    官方 md 的 L79 自己提到 ``kind = release_as_subject``，而它的
    ``List of Kinds`` 里没有这一个 —— 文档自相矛盾，数据以 33 个取值为准。
    """
    return len(war_goal_kind_diff())


def _doc16_strategic_field(target: str) -> int:
    """``common/strategic_regions`` 里某个字段出现的次数（doc 16 的 34 / 36）。

    与 ``dir_field_count``（去重键名数）是两个口径：这里数的是**出现次数**
    （每个区域每键最多一次，所以本例恰好同值 —— 但换目录就会分岔）。
    ⚠️ 目录是 ``common\\strategic_regions``，**不是** ``map_data\\state_regions``：
    后者里没有这个目录（``states`` 142 那句一直被人记错来源）。
    """
    return strategic_region_field_counts().get(target, -1)


def _state_region_words(target: str) -> int:
    """``map_data/state_regions`` 里某个词带**词界**的文本出现次数。

    doc 16 的「``traits =`` 出现在 517 个条目里、``state_traits =`` 出现 0 次」。
    ⚠️ 不能用 ``usage.word_stats``（子串口径）：``state_traits =`` 会被并进 ``traits``
    的次数里，而这句正文的**全部意义**就是这两个词不是一回事。
    """
    _dir, _, word = target.partition(":")
    return state_region_word_counts().get(word, -1)


# ── doc 03 / 14 / 15 / 18 / 19 那一批（2026-09）────────────────────────
def _doc03_ai_script_values(target: str) -> int:
    """`ai_script_values.txt` 的四个口径：``lines`` / ``top_keys`` / ``ast_keys`` / ``line_regex_keys``。

    doc 03 §4 那句「任意缩进的键共 N 个」是**行正则去重键名**口径
    （``line_regex_keys``）——它当初是在 1.14.2 上数的，1.14.3 重测为 64；
    按结构解析（``ast_keys``）是 75，差的那 11 个写在行中间 / 用比较符赋值 / 键名带 ``:``。
    行数（``lines``）与顶层键（``top_keys``）也在同一句里，一起钉住。
    """
    return ai_script_values_key_stats()[target]


def _doc14_hyphen_keys(target: str) -> int:
    """含连字符的顶层键数：``target`` 为空取全 ``common/`` 合计，否则取该目录。

    doc 14 §4.2 说 PM 里有 3 个（``pm_ammonia-soda_process`` …）；
    同一份数据在别的目录更多 —— ``character_templates`` 有 27 个（人名里的连字符），
    合计 4 个目录 32 个。这两个数一起钉，是为了防止下一个人把「PM 里 3 个」
    推广成「只有 PM 有」。
    """
    counts = hyphen_key_dir_counts()
    return sum(counts.values()) if not target else counts.get(target, -1)


def _doc14_buy_packages(target: str) -> int:
    """doc 14 §7.3 的三个口径：``wealth_1``（该包的类别数）/ ``categories``（全部类别去重）/ ``entries``（包数）。"""
    return {
        "wealth_1": wealth_1_goods_categories,
        "categories": buy_package_goods_categories,
        "entries": buy_package_entry_count,
    }[target]()


def _doc15_ideology_fields(target: str) -> int:
    """doc 15 §4.3 的三个数：``all``（深度1 去重 35）/ ``lawgroup``（26）/ ``other``（9）。

    ``other`` 是**不以 lawgroup_ 开头**的字段名个数，文档管它叫「标量字段」——
    其实那 9 个里只有 4 个是标量、5 个是块，所以这里的 target 刻意叫 ``other``。
    """
    total, lawgroup, rest = ideology_field_split()
    return {"all": total, "lawgroup": lawgroup, "other": rest}[target]


def _doc15_lobby_usable(_target: str) -> int:
    """doc 15 §7.5 的「49 个理由里只有 15 个标了 ``is_always_usable = yes``」。"""
    return lobby_appeasement_usable()


def _doc15_heritage_values(_target: str) -> int:
    """``common/religions`` 里 ``heritage`` 的**去重取值**个数（doc 15 §14.6 的 7）。

    ⚠️ 不是「8」：8 是 ``03_religious_heritages.txt`` 里定义的特质数，
    第 8 个 ``heritage_humanist`` 没有任何宗教引用它。
    """
    return len(religion_heritage_values())


def _doc18_country_effects(_target: str) -> int:
    """``common/history/countries`` 里写了 ``add_*`` / ``set_*`` 效果的文件数（doc 18 的 217）。

    ⚠️ 必须**任意深度**：``add_amendment`` 一类写在嵌套块里，只数深度 1 会得 0。
    """
    return country_effect_file_count()


def _doc19_checksum_targets(target: str) -> int:
    """``checksum_manifest.txt`` 里的校验对象数（doc 19 §2 的「5 个目录 + 1 个文件」）。

    ⚠️ 这个文件**不是花括号语法**（裸 ``directory`` / ``file`` 标记行 + ``name =``），
    走 ``parse_cached`` 会静默得 0 —— 必须按行解析，见 :func:`pdx.game_root.checksum_targets_grouped`。
    """
    dirs, files = checksum_targets_grouped()
    return len(dirs) if target == "dirs" else len(files)


# ── doc 17 那一批（2026-09）──────────────────────────────────────────
def _doc17_overview(target: str) -> int:
    """§0 总览的两个合计：``txt``（955 个 ``.txt``）/ ``keys``（11,705 个顶层定义键）。"""
    return overview_txt_count() if target == "txt" else overview_key_count()


def _doc17_loc_suffix(target: str) -> int:
    """``concepts_l_english.yml`` 里某一行的数值列（``concept_x`` 1037 / ``concept_x_desc`` 614）。"""
    return loc_suffix_count(target)


def _doc17_gene_blocks(_target: str) -> int:
    """``common/genes`` 的**不重复顶层块名**数（doc 17 的 5；9 是出现次数）。"""
    return len(gene_block_names())


def _doc17_block_prefix(target: str) -> int:
    """``<文件>|<块>|<前缀>`` —— 块内以该前缀开头的**去重**键名数。

    doc 17 的两个数共用它：``ethnicity_template`` 里 ``gene_`` 93 个、
    ``morph_genes`` 里 ``gene_`` 97 个（模板缺的那 4 个就是 97 − 93）。
    """
    path, _, rest = target.partition("|")
    block, _, prefix = rest.partition("|")
    return block_prefix_count(path, block, prefix)


def _doc17_block_items(target: str) -> int:
    """``<文件>|<块>|<blocks|items>`` —— 块的出现次数 / 块内赋值条数。

    doc 17 的 ``ethnicities`` 块：317 个块、343 条 ``权重 = 族群`` 条目。
    """
    path, _, rest = target.partition("|")
    block, _, which = rest.partition("|")
    blocks, items = block_item_count(path, block)
    return blocks if which == "blocks" else items


def _doc17_field_occurrence(target: str) -> int:
    """``<目录>:<字段>`` —— 该字段的出现次数（``flag_definition`` 1,407 / ``includes`` 2）。"""
    dir_rel, _, field = target.partition(":")
    return field_occurrence(dir_rel, field)


def _doc17_files_without_defs(target: str) -> int:
    """顶层定义数为 0 的文件数（``common/dna_data`` 的 ``00_dna.txt``）。"""
    return files_without_defs(target)


def _doc17_dna_per_file(_target: str) -> int:
    """``dna_data`` 里「有定义的文件各有多少个顶层定义」的**取值个数**。

    doc 17 §x 那句「583 个各有 1 个顶层定义」—— 有定义的文件取值集合是 {1}，
    所以这个数就是 **1**。换成「最常见的定义数」也能得到 1，但取值个数
    顺带证明了「全都有且只有 1 个」这件事（不是平均出来的 1）。
    """
    return len({n for n in file_definition_counts("common/dna_data").values() if n})


def _within_field_count(target: str) -> int:
    """``<目录>:<块>`` —— 该块内出现过的字段名个数（doc 17 的 3；空块名取整个条目）。

    doc 17 §14.4 的两句：``customizable_localization`` 的定义层 6 个字段、
    其中 ``text`` 块内部 3 个（``localization_key`` / ``trigger`` / ``fallback``）。
    """
    dir_rel, _, block = target.partition(":")
    return len(field_occurrences(f"common/{dir_rel}", within=block or None))


def _stance_total(_target: str) -> int:
    """`ideologies` 五档态度的总出现次数（doc 15 的「合计 3,753 处」）。"""
    return stance_total()


def _flag_comment_braces(_target: str) -> int:
    """`00_flag_definitions.txt` 里注释段含花括号的行数（doc 17 的 21）。"""
    return flag_comment_brace_lines()


def _fallback_yes(_target: str) -> int:
    """`customizable_localization` 里 ``fallback = yes`` 的处数（doc 17 的 16）。"""
    return fallback_yes_count()


def _gui_sprite_lines(_target: str) -> int:
    """``gui/`` 下以 ``spriteType =`` 开头的行数（doc 06 的 552）。"""
    return gui_sprite_lines()


def _getcustom_stats(target: str) -> int:
    """原版 `.yml` 里 ``GetCustom('键')`` 的调用统计（``calls`` / ``keys`` / ``files``）。

    doc 17 §18.4 原先写的「全库共 442 处」三种口径都复现不出 —— 见
    :func:`pdx.localization.getcustom_stats`（口径已写成代码：``game`` 下全部 `.yml`）。
    """
    return getcustom_stats()[target]


def _ai_script_values_referenced(_target: str) -> int:
    """`ai_script_values` 的顶层键里被 `00_default_strategy.txt` 引用的个数（doc 09 的 19）。"""
    return ai_script_values_referenced()


def _dir_md_files(target: str) -> int:
    """**游戏内容根**下某个目录的 ``.md`` 数（target 相对 ``game/``，空串表示 game 本身）。

    为什么要单列：`md_files` 数的是**全部官方 `.md`**（game + jomini + clausewitz = 94），
    而 doc 04 那句「GAME 下共有 91 个官方 `.md`」是**只看 game** 的口径 ——
    两个数都对，混用就差 1（这类「口径差 1」最容易被当成漂移去改）。
    """
    return count_files(config.GAME / target, ".md")


def _game_all_files(target: str) -> int:
    """**游戏内容根**下某个目录的全部文件数（递归）。"""
    return count_files(config.GAME / target)


def _game_txt_files(target: str) -> int:
    """**游戏内容根**下某个目录的 ``.txt`` 数（递归）。"""
    return count_files(config.GAME / target, ".txt")


def _file_namespaces(target: str) -> int:
    """一个 defines 文件里**不同命名空间名**的个数（target 相对 ``common/defines/``）。

    与 `file_top_keys` 的区别：那个连 ``@变量`` 与重复块一起数，这个只看
    「大写开头、非 ``@变量``、是块」的名字去重 —— doc 05 那句
    「19 个顶层块，但只有 18 个不同命名空间」正是这两个口径的差。
    """
    path = config.GAME / "common" / "defines" / target
    if not path.is_file():
        return -1
    names = {
        a.key
        for a in parse_cached(path).top_assignments
        if not a.is_variable and a.key[:1].isupper() and isinstance(a.value, Block)
    }
    return len(names)


def _field_distinct_values(target: str) -> int:
    """某目录里某个字段的**不同取值个数**（target 形如 ``events/placement``）。

    doc 04 那句「`placement` 取值共 340 个不同值」是这类数字的代表：
    它既不是字段数也不是出现次数，而是**去重后的取值个数** ——
    没有现成的 kind 能表达，于是长期无人看守（实测已变成 341）。
    """
    dir_rel, _, field = target.partition("/")
    return len(field_value_counts(dir_rel, field))


def _event_definitions(_target: str) -> int:
    """`events/` 里事件定义的个数（顶层块、键形如 ``name.123``）。

    与 :func:`pdx.doc04.event_definition_count` 同源（doc 04 §9.1 的散文数字）。
    """
    return event_definition_count()


def _dir_field_count(target: str) -> int:
    """``common/<target>`` 里**不同字段名**的个数（顶层条目块的字段，去重）。

    文档里那批「只有 N 个字段」的句子用这个 —— 与 `dir_blocks`（块数）
    是两个量：`interest_group_traits` 是 99 个特质、4 个字段。

    ``target`` 含 ``/`` 时按**相对 game** 解析（``events`` 这类目录不在
    ``common/`` 下；实测第一版把 ``events`` 当 ``common/events`` 查，得到 0）。
    """
    if target.startswith("game/"):
        dir_rel = target[len("game/") :]
    else:
        dir_rel = target if "/" in target else f"common/{target}"
    return len(field_occurrences(dir_rel))


def _ai_strategy_count(target: str) -> int:
    """`00_default_strategy.txt` 的字段计数（target 见下）。

    * ``fields`` —— 字段总数；
    * ``block`` / ``scalar`` / ``string`` —— 值形态；
    * ``additive`` / ``override`` / ``multiplicative`` / ``unmarked`` —— 官方注释里的叠加语义。
    """
    if target == "fields":
        return strategy_field_count()
    shapes = shape_counts()
    if target in shapes:
        return shapes[target]
    return semantic_counts().get(target, 0)


def _loc_concept_keys(_target: str) -> int:
    """`concepts_l_english.yml` 里 ``concept_*`` 键的总数（doc 17 §14.4）。

    分类逻辑在 :mod:`pdx.doc17`（那张「键名模式 → 实测数量」表就是它生成的），
    这里只取总数 —— 两处用同一个提取函数，数字不会各算各的。
    导入写在函数里：:mod:`pdx.doc17` 会拉进 doc_tables / usage，放在模块顶部
    会让 `verify` 的导入链变长，而这个 getter 只有一条断言用得到。
    """
    from .doc17 import loc_suffix_keys  # noqa: PLC0415

    path = config.GAME / "localization/english/concepts_l_english.yml"
    return len(loc_suffix_keys(path.read_text(encoding="utf-8"))) if path.is_file() else 0


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

    口径**只有一份实现**：:func:`pdx.defines.kind_counts`（界线是「块里有没有赋值」）。
    这里此前自己写了一套「同一行闭合才算内联列表」的判法，与 doc 05 §0.3 的
    口径补记不一致 —— 两种判法在 1.14.3 差 3 个参数（172 vs 175），
    而合计 3488 相同，所以那个分歧一直没被发现（分项没人钉）。
    """
    return kind_counts(blk)


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

    统计本机安装清单可发现的 Mod；扫描器按 metadata 身份排除本产品自身，避免安装开发
    候选后改变对外部 Mod 的统计。
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

    必须跨三个内容根统计 —— 实测 ``game`` 树 93 篇 + ``jomini`` 树 1 篇
    = **94**。只扫 ``game/`` 会少算一篇
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
    而本体已随 1.14.3 增长 —— 只钉「篇数 94」是看不出这种漂移的。
    """
    return sum(size for _key, size in _official_docs())


def _md_max_bytes(_target: str) -> int:
    """最大的官方 ``.md`` 的字节数（实测为 ``treaty_articles.md``）。

    这条钉住的是**单篇文档的尺寸**。它踩过一次真坑：doc 07 把这个数写成
    镜像里的 25,364（1.14.2），而本体 1.14.3 已是 28,171 —— 该篇新增的
    ``scope:other_country`` / ``requirement_to_maintain`` 等规则镜像里没有，
    照镜像写条约 mod 会漏。内容一致性另由 ``tests/test_docs_mirror.py``
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


def _tree_level1_txt(target: str) -> int:
    """安装树里某个目录**直接**放着的 ``.txt`` 数（不递归）。

    doc 04 §9.1 那句「``events\\`` 根目录 **130** 个 ``.txt``」就是它。
    为什么不能拿 ``tree_files``（递归 328）代替：那两个数答的是不同问题，
    「根目录少了、子目录多了」这种**搬家**会被总数掩盖 —— 而 doc 04 正是
    按「根目录 / 12 个子目录」分层描述的。
    """
    path = _tree_path(target)
    if not path.is_dir():
        return 0
    return sum(1 for p in path.iterdir() if p.is_file() and p.suffix == ".txt")


def _tree_subdir_files(target: str) -> int:
    """安装树里某个目录的**直接子目录**下的递归文件数（不含该目录自己的文件）。

    与 :func:`_tree_level1_txt` 配对：doc 04 §9.1 的
    ``130（根目录 .txt）+ 198（12 个子目录）= 328``（递归总数，另有断言看守）。
    三个口径分别钉住，搬文件才藏不住。
    """
    path = _tree_path(target)
    if not path.is_dir():
        return 0
    return sum(1 for sub in path.iterdir() if sub.is_dir() for p in sub.rglob("*") if p.is_file())


def _dir_level1_files(target: str) -> int:
    """``common/<target>`` 下**直接**放着的文件数（不递归）。

    doc 08 §x 的「``common\\`` 另有 **1 个直接文件**：``achievement_groups.txt``」
    —— ``dir_all_files`` 是递归口径（会把 136 个子目录里的几万个文件都算进来），
    数不出「散在 common 根下的那几个」。
    """
    base = config.GAME / "common" / target
    return sum(1 for p in base.iterdir() if p.is_file()) if base.is_dir() else 0


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


def _game_version_field(target: str) -> object:
    """游戏版本指纹里的某个字段（``caligula_rev`` / ``caligula_branch`` …）。

    doc 01 那张「版本指纹」表里的四个值 —— 它们是**判断游戏精确版本最可靠的依据**
    （``caligula_rev.txt`` 之类的文件在安装根目录下）。

    为什么值得单独钉住：**这是唯一一条「游戏一升级就立刻变红」的断言**。
    其余 230 条都只在自己关心的那个量变化时才响 —— 如果某次更新没碰到任何已断言的
    数字，``v3 verify`` 会全绿，你就不会知道游戏变了。有了这条指纹，
    升级后第一眼就能看到「版本从 A 变成 B」，从而知道该去跑
    ``v3 snapshot diff``（结构漂移）与 ``v3 tables --write``（表格重算）。

    ⚠️ 定义必须放在 ``_CHECKS`` **之前**：那个字典是模块级字面量，引用后面才定义的
    函数会在导入时直接 NameError（实测踩过）。
    """
    return config.game_version().get(target)


_CHECKS: dict[str, Callable[[str], object]] = {
    "dir_entries": _dir_entries,
    "dir_blocks": _dir_blocks,
    "dir_txt_files": _dir_txt_files,
    "dir_all_files": _dir_all_files,
    "dir_subdirs": _dir_subdirs,
    "dir_md_files": _dir_md_files,
    "game_all_files": _game_all_files,
    "game_txt_files": _game_txt_files,
    "file_namespaces": _file_namespaces,
    "loc_concept_keys": _loc_concept_keys,
    "field_distinct_values": _field_distinct_values,
    "event_definitions": _event_definitions,
    "dir_field_count": _dir_field_count,
    "ai_strategy_count": _ai_strategy_count,
    "modifier_suffix": _modifier_suffix,
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
    "tree_level1_txt": _tree_level1_txt,
    "tree_subdir_files": _tree_subdir_files,
    "dir_level1_files": _dir_level1_files,
    "defines_untaken": _defines_untaken,
    "modifier_suffix_other": _modifier_suffix_other,
    "static_digit_entries": _static_digit_entries,
    "static_indented_entries": _static_indented_entries,
    "field_missing": _field_missing,
    "file_nested_key_count": _file_nested_key_count,
    "texticon_definitions": _texticon_definitions,
    "loc_yml_unique_names": _loc_yml_unique_names,
    "file_bytes": _file_bytes,
    "file_definitions": _file_definitions,
    "doc16_group_files": _doc16_group_files,
    "doc16_group_no_md": _doc16_group_no_md,
    "md_block_undocumented": _md_block_undocumented,
    "md_bullet_diff": _md_bullet_diff,
    "dir_field_occurrences": _doc16_strategic_field,
    "state_region_words": _state_region_words,
    "doc03_ai_script_values": _doc03_ai_script_values,
    "doc14_hyphen_keys": _doc14_hyphen_keys,
    "doc14_buy_packages": _doc14_buy_packages,
    "doc15_ideology_fields": _doc15_ideology_fields,
    "doc15_lobby_usable": _doc15_lobby_usable,
    "doc15_heritage_values": _doc15_heritage_values,
    "doc18_country_effects": _doc18_country_effects,
    "doc19_checksum_targets": _doc19_checksum_targets,
    "doc17_overview": _doc17_overview,
    "doc17_loc_suffix": _doc17_loc_suffix,
    "doc17_gene_blocks": _doc17_gene_blocks,
    "doc17_block_prefix": _doc17_block_prefix,
    "doc17_block_items": _doc17_block_items,
    "doc17_field_occurrence": _doc17_field_occurrence,
    "doc17_files_without_defs": _doc17_files_without_defs,
    "doc17_dna_per_file": _doc17_dna_per_file,
    "doc17_dna_observation": dna_observation,
    "within_field_count": _within_field_count,
    "stance_total": _stance_total,
    "flag_comment_braces": _flag_comment_braces,
    "fallback_yes": _fallback_yes,
    "gui_sprite_lines": _gui_sprite_lines,
    "getcustom_stats": _getcustom_stats,
    "ai_script_values_referenced": _ai_script_values_referenced,
    "game_version_field": _game_version_field,
    "file_line_count": _file_line_count,
    "defines_kind_total": _defines_kind_total,
    "paths_settings_mappings": _paths_settings_mappings,
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
        # 要遍历整个 game 内容根的 .yml（实测 ~4 秒）—— 放进「慢」那一组，
        # `v3 verify --fast` 才不会被它拖住。
        "getcustom_stats",
    }
)


def claim_scope(claim: Claim) -> str:
    """Distinguish dated machine observations from current installation assertions."""
    return claim.scope


def claims_for_version(version: str | None = None) -> list[Claim]:
    """Return the documentation registry for the current release."""
    require_current(version)
    return CLAIMS


def current_claims() -> list[Claim]:
    return claims_for_version()


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
    selected = [
        c
        for c in (claims if claims is not None else current_claims())
        if c.scope == "native_installation"
    ]
    if not include_slow:
        selected = [c for c in selected if c.kind not in SLOW_KINDS]
    return [check(c) for c in selected]


# ── 官方更新之后：把实测值写回断言表 ──────────────────────────
#
# 为什么要有它：锁定原版更新后需要跑一次版本演练，而演练的固定成本
# 几乎全在**更新 CLAIMS 里的期望值**上（2026-09-23 的 1.14.4 演练：48 处）。
# `v3 refresh` 只改**文档**（表 + 带标记的正文），它改不了断言表自己 ——
# 于是那句「跑完全绿说明没有任何需要人改的东西」在最要紧的一步上不成立。
#
# ⚠️ **它照单全收实得值** —— 这正是它危险的地方：如果量错了（比如解析器坏了、报 0），
# 它会把错误一起写进期望值，闸门从此形同虚设。所以：
#   * 它是**显式**动作（`v3 verify --fix-claims`），**不挂在 `v3 refresh` 里自动跑**；
#   * 每一处改动都**打印出来**（id、旧值、新值）—— 人要逐条扫一眼"这个变化讲不讲得通"；
#   * 期望值不是整数的、量不出来的、执行出错的，一律**跳过并说明**，不猜。


@dataclass(frozen=True)
class ClaimEdit:
    """一处「按实测改写期望值」的改动，附**给人看**的描述与过期提示。"""

    id: str
    old: object
    new: object
    text: str
    text_stale: bool

    def line(self) -> str:
        tail = "（描述里还写着旧值，请顺手改）" if self.text_stale else ""
        return f"{self.id}: {self.old} → {self.new}{tail}"


def claim_value_slots(source: str) -> dict[str, tuple[int, int]]:
    """``断言 id -> 期望值那个字面量在**源码字节串**里的 (起, 止) 偏移``。

    用 `ast` 拿位置，不用正则：`Claim(...)` 的参数有的跨行、有的带尾注，
    正则迟早会咬到别的东西上；而 `ast` 给的是**精确**的 ``lineno/col_offset``
    （Python 3.8+ 还有 ``end_lineno/end_col_offset``）。

    ⚠️ 偏移是**字节**偏移，不是字符偏移 —— ``col_offset`` 按 CPython 的约定是
    「该节点首 token 的 UTF-8 字节偏移」，而断言表里**每一行都有中文**
    （文档名、描述），两者差得很多。按字符算会把刀口切进中文中间，写出乱码。
    """
    tree = ast.parse(source)
    slots: dict[str, tuple[int, int]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "Claim" or len(node.args) < 6:
            continue
        ident, value = node.args[0], node.args[5]
        if not (isinstance(ident, ast.Constant) and isinstance(ident.value, str)):
            continue
        if value.end_lineno is None or value.end_col_offset is None:  # pragma: no cover
            continue
        slots[ident.value] = (
            _offset(source, value.lineno, value.col_offset),
            _offset(source, value.end_lineno, value.end_col_offset),
        )
    return slots


def _offset(source: str, lineno: int, col: int) -> int:
    """``(1 起的行号, 0 起的字节列)`` → 字节偏移（见 `claim_value_slots` 的警告）。

    行按 ``str.splitlines`` 切（与 `ast` 同一套换行规则），再逐行编码 ——
    直接对 ``source.encode()`` 调 ``bytes.splitlines`` 会漏掉 ``\\x0b``/``\\u2028``
    这类只有字符串才认的换行，行号一错，下面全错。
    """
    lines = [line.encode("utf-8") for line in source.splitlines(keepends=True)]
    return sum(len(line) for line in lines[: lineno - 1]) + col


def apply_value_edits(source: str, edits: dict[str, object]) -> str:
    """把新的期望值写回源码文本（按偏移**倒序**替换，避免后面的偏移失效）。

    ``edits`` 的键是断言 id；值是要写进去的新值。全程在字节串上做 ——
    刀口来自 `ast`，是字节偏移；先在字符上切、再编码，中文行就错位了。
    """
    slots = claim_value_slots(source)
    todo = [(slots[ident], value) for ident, value in edits.items() if ident in slots]
    out = source.encode("utf-8")
    for (start, end), value in sorted(todo, key=lambda item: -item[0][0]):
        out = out[:start] + str(value).encode("utf-8") + out[end:]
    return out.decode("utf-8")


def fix_claims(
    *, source: Path | None = None, write: bool = False, only: str = ""
) -> tuple[list[ClaimEdit], list[str]]:
    """把**实测值**写回断言表：返回 ``(改动清单, 跳过原因)``。

    调用方**必须把改动清单逐条打出来**（见本节开头那段：这一步的危险在于"照单全收"）。

    清单里的每一条都是 :class:`ClaimEdit`；``.text_stale`` 是**提示不是错误**：
    断言描述里还写着旧值时提醒一句，但**不代改**。描述是给人看的标签，
    而有些旧数字是**故意留在描述里的历史对照**（``chr.tech_definitions``
    的描述那句"178 是 1.14.2 旧值"就属于这种），按数字一律替换会把句子改错。

    ⚠️ 比的是**导入时那份** ``CLAIMS``：同一进程里跑第二遍仍会拿旧期望值去比，
    因此第二遍的"改动"是假的（CLI 每次是新进程，实际使用不受影响；
    测试要重载断言表再断言幂等）。
    """
    path = source or (config.REPO / "src/pdx/verify_claims_1152.py")
    text = path.read_text(encoding="utf-8")
    slots = claim_value_slots(text)
    changes: list[ClaimEdit] = []
    skipped: list[str] = []
    edits: dict[str, object] = {}
    for claim in current_claims():
        if only and only not in claim.id:
            continue
        if claim.scope == "machine_snapshot":
            skipped.append(f"{claim.id}: 保留注明日期的本机观测值")
            continue
        if claim.id not in slots:
            skipped.append(f"{claim.id}: 断言表源码里找不到它的期望值字面量")
            continue
        if not isinstance(claim.expected, int):
            skipped.append(
                f"{claim.id}: 期望值不是整数（{type(claim.expected).__name__}），不自动改"
            )
            continue
        result = check(claim)
        if result.error:
            skipped.append(f"{claim.id}: 量不出来（{result.error}）")
            continue
        if result.ok:
            continue
        if not isinstance(result.actual, int):
            skipped.append(
                f"{claim.id}: 实得值不是整数（{type(result.actual).__name__}），不自动改"
            )
            continue
        edits[claim.id] = result.actual
        changes.append(
            ClaimEdit(
                id=claim.id,
                old=claim.expected,
                new=result.actual,
                text=claim.text,
                text_stale=mentions_number(claim.text, claim.expected),
            )
        )
    if write and edits:
        path.write_text(apply_value_edits(text, edits), encoding="utf-8", newline="\n")
    return changes, skipped


#: 数字在**自然文本**里的边界：前面不能是数字/逗号/点，后面不能是数字/逗号/点。
#: 不这么切，``1`` 会在 ``1.14.2`` 里命中、``178`` 会在 ``1178`` 里命中。
_NUMBER_EDGE = r"(?<![\d,.]){}(?![\d,.])"


def mentions_number(text: str, value: object) -> bool:
    """文本里是否**作为独立数字**提到了 ``value``（千分位逗号不算边界内）。

    用于 `fix_claims` 的 ``text_stale`` 提示 ——「描述里的数字与期望值对不上」
    是最容易骗过眼睛的一类过期：表里印着"NAI 有 1017 个参数"，
    右边一列却写着实得 1018。
    """
    return re.search(_NUMBER_EDGE.format(re.escape(str(value))), text) is not None


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
    # **迁移到归属标记后，这张表清空了** —— 它原先的 10 条全是「同一行并列了
    # 好几个口径、静态文本分不清断言要的是哪一个」（如 doc 06 的 texticon
    # 432/436、doc 16 的 47/48、doc 12 的 prefix 计数）。
    #
    # 标记把「猜」换成了「绑定」：数字后面直接写明它属于哪条断言，于是这些
    # 纠缠不再是问题 —— 绑定过的断言根本不参与锚点扫描（见 find_doc_drift）。
    # 表还留着，是因为**没有标记的那些**断言仍可能遇到同类纠缠：
    # 新增条目时请写清「文档其实是对的，两个数字各是什么口径」。
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


# ── 归属标记的体检与修复 ────────────────────────────────────
@dataclass(slots=True)
class MarkerIssue:
    """一处标记问题。"""

    doc: str
    line: int
    id: str
    detail: str

    def describe(self) -> str:
        return f"{self.doc}:{self.line} <!--claim:{self.id}--> —— {self.detail}"


def check_markers(docs_dir: Path | None = None) -> list[MarkerIssue]:
    """标记体检（两条，都不需要游戏）。

    * **孤儿标记**：``<!--claim:x-->`` 指向的断言不存在（断言被删/改了 id，
      而文档里的标记没跟着改）—— 标记一旦指向空处，它就只是装饰；
    * **数字不符**：标记前的数字与断言期望值不一致 —— ``v3 verify --fix`` 可修。

    「有标记的断言不再参与锚点漂移扫描」这条规则也在这里生效
    （见 :func:`find_doc_drift`）：绑定比扫描精确，两套同时跑只会互相打脸。
    """
    by_id = {c.id: c for c in current_claims()}
    out: list[MarkerIssue] = []
    for m in all_markers(docs_dir or config.docs_root()):
        claim = by_id.get(m.id)
        if claim is None:
            out.append(MarkerIssue(m.doc, m.line, m.id, "没有这条断言（断言被删或 id 写错）"))
            continue
        if isinstance(claim.expected, int) and claim.expected != m.value:
            out.append(
                MarkerIssue(
                    m.doc,
                    m.line,
                    m.id,
                    f"标记处写着 {m.value}，断言期望 {claim.expected}（跑 `v3 verify --fix` 可修）",
                )
            )
    return out


def fix_markers(docs_dir: Path | None = None, *, write: bool = False) -> list[MarkerFix]:
    """按断言期望值改写标记处的数字。

    ``write=False`` 时只算出改动清单 —— 与 ``--fix`` 共用同一条实现，
    免得「检查说会改 A、实际改了 B」。
    """
    expected = {c.id: c.expected for c in current_claims() if isinstance(c.expected, int)}
    fixes, _checked = apply_fixes(docs_dir or config.docs_root(), expected, write=write)
    return fixes


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
    docs_dir = docs_dir or config.docs_root()
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

    #: 已经被**归属标记**钉住的 ``(文档, 断言)`` 对 —— 它们不需要启发式扫描：
    #: 标记直接说明「这个数字属于哪条断言」，比「锚点词 + 量级接近」精确得多。
    #: 于是 ``TEXT_SCAN_EXEMPT`` / ``KNOWN_METRIC_MIXUPS`` 里那些「锚点太通用」
    #: 的豁免可以随迁移逐条删掉（见 pdx.markers）。
    bound = marker_ids_by_doc(docs_dir or config.docs_root())

    for claim in current_claims():
        if not isinstance(claim.expected, int) or not claim.expected:
            continue
        if claim.id in TEXT_SCAN_EXEMPT:
            continue
        if claim.id in bound.get(claim.doc, set()):
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
            # 容差不能大于**量本身**：期望 1 时窗口是 ``0 < |v-1| <= 2``，
            # 也就是 0 / 2 / 3 全算「量级接近」，于是任何带锚点、又恰好不含
            # 「1」的行（``| 2 | `achievements` | 9 | 0 |``）都成了候选 ——
            # 实测一条期望 1 的断言在 doc 08 报了 13 处、doc 16 报了 8 处，
            # 全是无关的相邻计数。期望 2 同理（窗口会盖住 1 与 3）。
            #
            # 夹到 ``expected - 1`` 之后，期望 1 的容差是 0：漂移扫描对它
            # **不再产出信号**（数值核验照跑，见 ``v3 verify``）。
            # 这是有意的取舍：一个「只有 1 个文件」的断言，正文里写 2 也
            # 未必是漂移（可能说的是另一件事），静态文本分不清 ——
            # 与其报一堆噪声淹没真信号，不如让它只在数值那面看守。
            tolerance = min(tolerance, max(0, claim.expected - 1))
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
#: ``tests/test_defines_tables.py``：那个测试直接比对
#: 「文档现值 vs `pdx.defines.doc_table_rows()` 的输出」，比文本扫描强得多
#: （文本扫描只能发现「某个数字不对」，那个测试能发现**哪一行**不对）。
TEXT_SCAN_EXEMPT: dict[str, str] = {
    # 迁移到**归属标记**之后，这张表几乎空了：59 条里有 58 条的断言现在带标记，
    # 而带标记的断言根本不再参与锚点扫描（标记是精确绑定，扫描是启发式猜测）。
    # 判定规则：**先问这条断言的数字有没有标记** —— 有就不需要豁免，
    # 没有才需要在这里写清楚「为什么扫描它会满屏误报」。
    "def.file_interfaces": "锚点 'interfaces' 与相邻的块数/行号同量级 → 误报 8 处；"
    "该数字在生成表里（doc 05 §2.x 的 interfaces 块表），另见 test_defines_tables.py",
    "ai.script_values_doc09": "该数字在 §4 的**表**里（正文没有），而同一节正文里的 31 是"
    "「Kuromi's AI 覆盖的 NAI 参数数」—— 期望 33 的容差 ±2 正好罩住它（误报 1 处）。"
    "数值核验照跑；要让它也有标记，得先把 §4 那张表改成生成表",
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


def _check_machine_product(claim: Claim, actual: object, mods: dict) -> CheckResult:
    """Check the local aggregate against the per-Mod rows in the same artifact."""
    titles = {"mods_total": "已分析 Mod 数", "mods_files": "已分析 Mod 的内容文件总数"}
    rows = mods.get("各mod")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return CheckResult(claim, actual, False, "Mod 产物缺少逐项分析记录")
    if claim.kind == "mods_total":
        expected = len(rows)
    else:
        counts = [row.get("文件") for row in rows]
        if not all(type(count) is int and count >= 0 for count in counts):
            return CheckResult(claim, actual, False, "Mod 产物含缺失或无效的逐项文件数")
        expected = sum(counts)
    measured = replace(claim, text=titles[claim.kind], expected=expected)
    return CheckResult(measured, actual, type(actual) is int and actual == expected)


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
#: 而入库的精简快照（`tools/out/snapshots/*.compact.json`，约 6.0 MiB）
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


def _snap_common_dirs(snap: Snapshot, target: str) -> object:
    """``common/`` 的子目录数 = 快照里出现的目录数。

    **只有 ``target`` 为空时才答得出来**：快照的 ``common_entries``
    记的是「common 各子目录里有哪些条目」，没有更下一层的目录结构。
    早先这里直接无视 target，于是 `dir_subdirs` 带 target 的断言
    离线会拿到 **136**（common 自己的），报出一个看着像漂移、其实是口径串了的失败
    —— 实测踩过（doc 11 的「history 有 22 个子目录」）。
    现在返回 ``None``：调用方把它当「这条离线核不了」，好过给一个错的数。

    ⚠️ 带 target 的断言**不要用这个 kind**（`--from-snapshot` 会把 ``None``
    记成失败）：那类断言请用 `tree_subdirs` —— 它没有离线映射，
    会被正确地当成「需读游戏本体」跳过。
    """
    if target:
        return None
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


def _snap_game_version(snap: Snapshot, target: str) -> object:
    """版本指纹也能用**入库快照**核验（CI 上没游戏时要的就是这个）。

    ``版本`` 是快照的**顶层**字段（与 ``域`` 平级），不在 ``sections`` 里 ——
    第一版写成 ``snap.sections.get("版本")``，离线跑出 3 条「快照里没有对应域」。
    """
    return snap.version.get(target)


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
    "game_version_field": _snap_game_version,
}


# ── 第二份离线真值：入库的官方文档清单 ──────────────────────
#: 入库的当前官方文档清单。
#: 里带着每篇的字节数 —— 那正好是 ``md_files`` / ``md_total_bytes`` /
#: ``md_max_bytes`` 三条断言要的真值，而且**不需要游戏**。
#:
#: 为什么单独一份而不是塞进快照：快照是「某一版游戏的结构域」，清单是
#: 「官方文档的指纹」，两者的更新时机与用途都不同（见 ``v3 mirror``）。
#: 但它们同属「入库的离线真值」，所以由同一个 ``--from-snapshot`` 路径消费 ——
#: 对 CI 而言「真值从哪来」不重要，重要的是**不用装游戏**。
def _manifest_docs() -> dict[str, dict[str, object]]:
    return docs_mirror.entries()


def _man_md_files(_target: str) -> object:
    docs = _manifest_docs()
    return len(docs) if docs else None


def _man_md_total_bytes(_target: str) -> object:
    docs = _manifest_docs()
    sizes = [int(str(m["字节"])) for m in docs.values()]
    return sum(sizes) if sizes else None


def _man_md_max_bytes(_target: str) -> object:
    docs = _manifest_docs()
    sizes = [int(str(m["字节"])) for m in docs.values()]
    return max(sizes) if sizes else None


_MANIFEST_GETTERS: dict[str, Callable[[str], object]] = {
    "md_files": _man_md_files,
    "md_total_bytes": _man_md_total_bytes,
    "md_max_bytes": _man_md_max_bytes,
}


def snapshot_kinds() -> frozenset[str]:
    """**无游戏时**能被离线真值核验覆盖的断言类型（快照 ∪ 官方文档清单）。"""
    return frozenset(_SNAPSHOT_GETTERS) | frozenset(_MANIFEST_GETTERS)


def latest_compact_snapshot_path() -> Path | None:
    """所选原版版本的**精简快照**路径；没有该版本时返回 ``None``。

    「哪份快照算数」只有这一处定义：:func:`latest_compact_snapshot`（读内容）
    与离线闸门（:mod:`pdx.vanilla_index`，要在输出里写明真值来自哪个文件）
    都走它 —— 两处各写一份 glob，迟早会出现「verify 认、闸门不认」。
    """
    if not SNAPSHOT_DIR.is_dir():
        return None
    require_current()
    path = SNAPSHOT_DIR / f"{CURRENT_CONTRACT.snapshot_label}.compact.json"
    return path if path.is_file() else None


def latest_compact_snapshot() -> Snapshot | None:
    """仓库里最新的一份**精简快照**；一份都没有时返回 ``None``。

    只认 ``*.compact.json`` —— 完整快照不入库，而且体积大一个数量级。
    """
    path = latest_compact_snapshot_path()
    if path is None:
        return None
    snap = Snapshot.load(path)
    snap.require_version()
    return snap


def verify_from_snapshot(
    snap: Snapshot | None = None, claims: list[Claim] | None = None
) -> list[CheckResult]:
    """用**入库的离线真值**核验能被它覆盖的那部分断言。

    两份真值，先查快照、再查官方文档清单：

    * 精简快照（``tools/out/snapshots/*.compact.json``）—— 目录条目名、
      defines 命名空间、DLC 清单；
    * 当前官方文档清单记录篇数与逐篇字节数。

    覆盖不到的断言类型**不出现在结果里**（用 :func:`snapshot_kinds` 查范围），
    而不是报成失败 —— 这条路的定位就是「无游戏时能查多少查多少」。
    """
    snap = snap or latest_compact_snapshot()
    if snap is not None:
        snap.require_version()
    out: list[CheckResult] = []
    for claim in claims if claims is not None else current_claims():
        getter = _SNAPSHOT_GETTERS.get(claim.kind)
        try:
            if getter is not None:
                if snap is None:
                    continue
                actual: object = getter(snap, claim.target)
                missing = "快照里没有对应域或条目"
            else:
                man_getter = _MANIFEST_GETTERS.get(claim.kind)
                if man_getter is None:
                    continue
                actual = man_getter(claim.target)
                missing = "官方文档清单不存在或为空（跑 `v3 mirror write`）"
        except (KeyError, TypeError, AttributeError) as exc:
            out.append(CheckResult(claim, None, False, f"{type(exc).__name__}: {exc}"))
            continue
        if actual is None:
            out.append(CheckResult(claim, None, False, missing))
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
    for claim in claims if claims is not None else current_claims():
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
        if claim.scope == "machine_snapshot":
            out.append(_check_machine_product(claim, actual, mods))
        else:
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
    docs_dir = docs_dir or config.docs_root()
    known = known_values
    if known is None:
        known = {int(c.expected) for c in current_claims() if isinstance(c.expected, int)}

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
