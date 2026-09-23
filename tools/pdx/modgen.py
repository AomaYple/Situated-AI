"""数据源 → mod 产物的生成器（阶段 3 并行轨的第一步）。

为什么要有它
------------
P3 说「引擎脚本由 Python 生成，人只改数据源」，F10 说「生成器优先、单一数据源」——
本模块就是这条纪律的落点：**`mod/` 下的脚本、本地化、档案文档全部由这里从
`mod/data/*.toml` 编译出来**，人只改 TOML。

它替掉的是"手写一版脚本 → 三个地方各写一遍数字 → 谁也不记得为什么是 20 不是 25"
这条路。手写的失效方式很安静：脚本里的 -20、本地化里的文案、文档里的说明
分别漂移，游戏照跑，只是行为与设计不一致。

口径（写清楚，免得以后各算各的）
--------------------------------
* **每张表都必须带非空 `why`** —— 不只是数字。空 `why` 当场报错（:class:`DataError`），
  这是 P10 从"纪律"变成"可执行检查"的那一步；
* **数字一律写成 `amount = N`**（同表内配 `why`）。缩写形式只有一种，于是
  :func:`why_report` 与闸门 ⑤ 能机械地枚举"每个数字 + 它的依据"；
* **产物路径 = 原版目录树的镜像**：`common/<原版目录>/sitai_*.txt` 与
  `localization/<语言>/sitai_*.yml`。F7 的「平铺不建子目录」指的是
  **每个原版目录下只放我们的文件、不再自建子目录**（自建子目录在 1.14.3 实测
  不被引擎枚举 —— 探针 `zz_probe_subdir_probe` 就是为这条留的证据）；
* **游戏侧文件一律写 UTF-8 BOM**（`encoding="utf-8-sig"`）：`common/` 下 3,026 个
  `.txt` 有 3,002 个带 BOM，`localization/` 的 `.yml` 同样带 —— 缺 BOM 的表现是
  "这份文件像没生效"，且只会写进 error.log（探针实测踩过）。`.md` 与 `.json`
  **不带** BOM：前者不是游戏侧文件，后者的读取方（启动器）按 JSON 解析。

产物清单（每份档案）
--------------------
===============================  ==========================================
``common/scripted_effects/``      冲击记账效果（变量 + 挂修正）
``common/static_modifiers/``      压力修正（真实的合法性/贵族/财政变化）
``common/static_modifiers/``      （可选）改革侧输入修正（`[reform_inputs]`，B2 处理段）
``common/journal_entries/``       改革窗口 JE（判据驱动）
``common/defines/``               节奏杠杆（按块 + 参数覆盖 ``NAI``）
``common/ai_strategies/``         递牌（本档案为空，F5）
``localization/<语言>/``          文案（中英）
``sitai_<id>.md``                 档案文档（每个数字与它的依据）
``.metadata/metadata.json``       启动器要的元数据（不带 BOM）
===============================  ==========================================

> **文档（`.md`）不在往返净度的范围内**：它是给人看的，由闸门 ⑤ 的可复现性守着。

数据源 schema v1（阶段 4 · 第一步）
-----------------------------------
* 一份数据源 = 一份**档案**：必填 `archive / memory / pressure / journal_entry / cards /
  localization / references`，可选 `reform_inputs`（第二处理段）与 `tempo`（节奏杠杆）；
* **`[tempo]` 与 `.metadata/metadata.json` 是 mod 级产物**：`defines` 没有单国写法，
  所以 `[tempo]` 全仓只允许**一份**（0 份或 2 份都当场报错）；元数据由**全部档案合成一份**
  （一份 mod 只有一个 `id` 与一个 `supported_game_version`，因此档案之间的 `game_version`
  必须一致）；
* **加一个处境 = 加一份 `mod/data/*.toml`**：既有档案的产物逐字节不变
  （``build_all`` 的组合规则保证这条，用例钉着它）。
"""

from __future__ import annotations

import json
import re
import tomllib
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import config
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

#: 数据源 schema 版本。不匹配就报错，不做兼容猜测（P13：不许静默降级）。
SCHEMA_VERSION = 1

#: 数据源目录（仓库根下）。
DATA_DIR = config.REPO / "mod" / "data"

#: 产物根（仓库根下）。**它就是 mod 根** —— 原版目录树的镜像。
PRODUCT_DIR = config.REPO / "mod"

#: 数据源扩展名。
DATA_SUFFIX = ".toml"

#: 我们自己的文件前缀（F7 命名空间）。
FILE_PREFIX = "sitai_"

#: 游戏侧文件（要写 BOM 的那些）。
GAME_SIDE_SUFFIXES = (".txt", ".yml")

#: 支持的语言：游戏目录名 → `.yml` 里的语言声明行。新增一种语言 = 这里加一行
#: + 数据源的每条本地化补一个同名字段（缺字段会报错，不会静默漏语言）。
LANGUAGES: dict[str, str] = {"english": "l_english", "simp_chinese": "l_simp_chinese"}

#: JE 的判据块顺序。**固定顺序**是确定性生成的一部分：数据源里换个书写次序
#: 不该让产物变样（否则"两次生成逐字节一致"会被无意义的编辑打破）。
GATE_ORDER = ("is_shown_when_inactive", "possible", "complete", "fail", "invalid")

#: 修正名的合法前缀（F7）：策略 `ai_strategy_sitai_*`、JE `je_sitai_*`、其余 `sitai_*`。
#:
#: 引擎认的是**它自己的**前缀（`je_` 让它找 journal_entries、`ai_strategy_` 让它
#: 找策略），所以 `sitai_` 只能排在后面 —— 于是判据写成"可选引擎前缀 + sitai_"，
#: 而不是"必须以 sitai_ 开头"。
NAMESPACE_PREFIX = "sitai_"

#: 命名空间的完整判据（见 :data:`NAMESPACE_PREFIX` 的注释）。
NAMESPACE_RE = re.compile(r"^(?:ai_strategy_|je_)?sitai_[a-z0-9_]+$")

#: 生成文件的注释头。**改产物没用**这件事必须写在文件里 —— 下一个人打开的是产物，
#: 不是生成器。（不带结尾换行：产物文本一律由 `"\n".join(...)` 拼，行内不再埋换行，
#: 否则每行注释都会多出一个空行。）
GEN_HEADER = (
    "# ⚠️ 本文件由 `v3 modgen` 生成（tools/pdx/modgen.py）—— 改这里没用，改数据源 mod/data/*.toml。"
)

#: 文档类产物的注释头（markdown 引用块）。
DOC_HEADER = "> ⚠️ 本文件由 `v3 modgen` 生成 —— 改这里没用，改数据源 `mod/data/*.toml`。"

#: mod 版本号。
#:
#: **为什么不是从数据源读**：它是发布节奏（mod 的第几个版本），不是设计数字 ——
#: 设计数字才受 P10 的 `why` 约束。游戏版本相反，它是"档案对哪个引擎有效"，
#: 所以写在数据源的 `archive.game_version` 里由作者显式钉住。
MOD_VERSION = "0.1.0"

#: 缩进（与生成物一致：Tab，原版脚本的写法）。
TAB = "\t"

#: 本地化文件的键版本号。`KEY:0 "值"` 的 `0` 是给译者看的新旧标记，
#: 新写的键一律 0（原版新键也是 0）。
LOC_VERSION = 0

#: mod 元数据的产物路径（不属于任何原版目录树，所以单列）。
METADATA_REL = ".metadata/metadata.json"


class _NoDifficultyError(Exception):
    """内部哨兵：没有任何数据源声明 `[difficulty]`（不是数据源错误，见该函数说明）。"""


class DataError(ValueError):
    """数据源不合法（结构、类型、`why` 缺失、命名空间越界…）。

    刻意**不**继承 OSError / 不吞异常：数据源写错时必须当场停下，
    而不是生成一份"看起来正常"的产物。
    """


# ── 通用条目 ────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Number:
    """数据源里的一个数字 + 它的依据。"""

    path: str
    value: float
    why: str


@dataclass(frozen=True, slots=True)
class Param:
    """``key = amount`` 形式的参数（变量参数、修正字段、牌面字段共用）。

    ``arg`` 是**非数值的设置项**（目前只有 :class:`Signals` 的 `set_strategy` 用）：
    它的右值是**原版标识符**（策略 id），不是数。两种形式互斥 —— ``amount`` 参与
    闸门 ③ 的稀释预算与事实表（:func:`facts`），``arg`` 只进事实表
    （字符串参数没有"价格"可言）。
    """

    key: str
    amount: float
    why: str
    arg: str = ""


@dataclass(frozen=True, slots=True)
class Clause:
    """一条判据：``key op arg``（数值形式写成 ``amount``）。"""

    key: str
    why: str
    op: str = "="
    arg: str | None = None
    amount: float | None = None

    def render(self) -> str:
        return f"{self.key} {self.op} {self.operand()}"

    def operand(self) -> str:
        return self.arg if self.arg is not None else num(self.amount or 0)

    def fact(self) -> str:
        """事实表里的值：``op + 操作数``（与 :func:`readback` 反解出来的一致）。"""
        return f"{self.op}{self.operand()}"


@dataclass(frozen=True, slots=True)
class Condition(Clause):
    """JE 的一条判据，额外带它属于哪个判据块（``gate``）。"""

    gate: str = "possible"


@dataclass(frozen=True, slots=True)
class Tempo:
    """节奏杠杆：覆盖某个 defines 块下的若干参数。

    **mod 级表**：`defines` 没有单国写法，所以 `[tempo]` 全仓只允许一份
    （见 :func:`build_all` 的检查）；第二份档案不该复制一遍。
    """

    block: str
    why: str
    keys: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class Memory:
    """处境记忆：变量 + 写它的效果（谁把处境判成处境，由实验给结论）。"""

    variable: str
    effect: str
    why: str
    params: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class Pressure:
    """压力：静态修正 + 挂它的参数。"""

    name: str
    icon: str
    why: str
    params: tuple[Param, ...]
    effects: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class Inputs:
    """改革侧输入：**第二个「效果 + 修正」对**（可选表 `[reform_inputs]`）。

    为什么档案需要第二个修正（而不是往 `[pressure]` 里再塞两条字段）：
    阶段 3 的 A/B 阶梯要在**一局之内**分开施加两处理 —— B 段只加冲击、B2 段再追加
    改革侧输入。挤进同一个修正就没有"只加冲击"的那一段，B 与 B2 的差分也就无从谈起
    （执行文档的失败长相要求两层分开报，前提是两处输入能分开施加）。
    """

    name: str
    effect: str
    icon: str
    why: str
    params: tuple[Param, ...]
    effects: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class Signals:
    """窗口开/关时递出的**原版策略牌**（`set_strategy`）。

    为什么这是 B 级而不是 A 级（F5：能改世界就不占槽）：世界状态（变量 + 修正）
    只改得了 AI 的**输入**，改不了它**已经挂着的那张牌** —— 而原版把"动不动手改法"
    卡在牌上（`change_law_chance`：反动 3.5 / 保守 2.5 / 进步 10）。阶段 3 实测过：
    只压世界状态，牌会被重抽到**保守**，而保守的动手概率**比反动还低** ⇒ 法律一条没改
    （`阶段3-结果.md` §三）。所以"整条路线要换"时**必须递牌**。
    递的是**原版自己的牌**（`ai_strategy_progressive_agenda` 等），不是我们自建的新牌
    —— 不新增槽位竞争，也不新增要被引擎读取的键。

    `set_strategy` 是脚本效果（`effect_localization/00_country_effects_loc.txt:40`），
    原版在 JE 里就这么用（`journal_entries/05_grunderzeit.txt:118`、
    `events/peoples_springtime.txt:780/980/1097`）—— 它**绕开** `CHANGE_STRATEGY_THRESHOLD`
    的累积掷骰（期望 ≈9.6 年一次，`defines/00_ai.txt:38-39`）。
    """

    set_strategy: tuple[Param, ...]
    clear_strategy: tuple[Param, ...]
    why: str

    @property
    def empty(self) -> bool:
        return not self.set_strategy and not self.clear_strategy


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """改革窗口 JE。"""

    name: str
    group: str
    icon: str
    why: str
    fields: tuple[Param, ...]
    conditions: tuple[Condition, ...]
    signals: Signals


@dataclass(frozen=True, slots=True)
class Localization:
    """一条本地化：键 + 每种语言的值。"""

    key: str
    why: str
    values: dict[str, str]


#: 难度三档的**档位 id**（契约 J5：`史实友好` / **`一视同仁`（默认）** / `无情`）。
#:
#: 为什么写成常量而不是让数据源随便取名：这三档是**对外契约**（玩家在开局规则界面里
#: 看到的就是这三档），名字漂了契约就漂了。数据源只能在这三个 id 里挑，改不了集合。
DIFFICULTY_TIERS: tuple[str, ...] = ("history_friendly", "uniform", "harsh")

#: 默认档（`01a` J 节第 5 条原文：**`一视同仁`（默认）**）。
#:
#: 为什么默认不是"史实友好"：这个 mod 的全部主张是「处境对谁都成立」——
#: 默认给玩家开小灶会让"世界活了"变成"世界对我温柔了"。
DIFFICULTY_DEFAULT = "uniform"

#: 玩家侧修正名的后缀（**只有带 `player_effects` 的档位**才会生成那几条修正）。
#:
#: 为什么放在生成器里：它表达的是"这一条是玩家肩上的那一份"这层**限定语**，
#: 与档位名是同一件事的两半；让数据源把两半各写一遍，只会让它们有机会对不上（P9）。
DIFFICULTY_MODIFIER_SUFFIX: dict[str, str] = {
    "english": " (your share)",
    "simp_chinese": "（你这一份）",
}


#: P11「面板三行」的三个槽位（`key` = 数据源里的键，`suffix` = 本地化键的后缀）。
#:
#: 为什么要有这一组（而不是把三行揉进 JE 的 `_reason` 里）：G3 的判据是
#: **试玩者能复述「当前目标 + 主因」**，而一份散文式说明里，"目标"与"主因"是混在一起的
#: —— 复述不出来的时候，我们**分不清是哪一行没写清楚**。拆成三个键之后：
#:
#: * 每个键都能单独被核对（`v3 modgen --check` 会逐键比字数）；
#: * 缺哪一行当场看得见（三种行都有 `why`，闸门 ⑤ 按表检查）；
#: * 将来做脚本化 GUI（阶段 6 的"必要时"）时，三个键可以直接接到三行控件上。
PANEL_LINES: tuple[tuple[str, str], ...] = (
    ("goal", "goal"),
    ("pressure", "pressure"),
    ("last_change", "last_change"),
)


@dataclass(frozen=True, slots=True)
class Probe:
    """探针要盯的东西（**每份档案显式声明**，可选表 `[probe]`）。

    ``reform_law``：`ab_probe` 的"行为层②"用哪条法判"改革真的发生了"。
    **允许为空**（= 没查实）—— 空的时候套件**不产出**那条判据：宁可少一条读数，
    也不给一条会对某些国家立刻为真的假判据（奥斯曼/埃及在历史文件里没有土地法，
    写死 `law_serfdom` 时"不是农奴制"当场成立，实测踩过）。
    """

    why: str
    reform_law: str


@dataclass(frozen=True, slots=True)
class DifficultyTier:
    """难度的一档：id + 中英文名与说明 + 这一档**给玩家加什么**。

    ``player_effects`` = 这一档在**玩家**身上额外施加的修正（`一视同仁` 为空 = 不加戏）。
    **不是**"玩家豁免处境压力"：世界状态对谁都成立（这个 mod 的主张），难度调的是
    **玩家肩上的那一份** —— `01a:240` 的原话就是"玩家被压死 → 难度分档"。
    """

    id: str
    #: 规则键（`[difficulty].key`）—— 设置名由它派生，而 `has_game_rule` 读的就是设置名。
    rule_key: str
    label: dict[str, str]
    desc: dict[str, str]
    why: str
    #: 玩家侧修正的名字（`sitai_<档案 id>_difficulty_<档位>`）；`player_effects` 为空时不用。
    modifier: str
    player_effects: tuple[Param, ...]
    player_why: str

    @property
    def setting(self) -> str:
        return f"setting_{self.rule_key}_{self.id}"


@dataclass(frozen=True, slots=True)
class Difficulty:
    """难度三档（**mod 级**：全仓只允许一份，照 `[tempo]` 的口径）。"""

    key: str
    why: str
    tiers: tuple[DifficultyTier, ...]
    owner_id: str
    #: 玩家侧修正的图标（原版路径，闸门 ② 会核它存在）。
    icon: str = ""

    def tier(self, tier_id: str) -> DifficultyTier:
        return next(item for item in self.tiers if item.id == tier_id)

    def tiers_with_player_effects(self) -> tuple[DifficultyTier, ...]:
        """有玩家侧修正的档位（`一视同仁` 按设计为空 —— 默认不加戏）。"""
        return tuple(item for item in self.tiers if item.player_effects)

    @property
    def rule_file(self) -> str:
        return f"common/game_rules/sitai_{self.owner_id}_difficulty.txt"

    @property
    def modifier_file(self) -> str:
        return f"common/static_modifiers/sitai_{self.owner_id}_difficulty.txt"


@dataclass(frozen=True, slots=True)
class Card:
    """一张递牌（C 级）。本档案为空，闸门 ③ 按价格表给它定价。"""

    name: str
    slot: str
    weight: float
    why: str
    possible: tuple[Clause, ...]
    fields: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class Reference:
    """声明式引用：形状上认不出来、只能靠作者声明的那类原版词汇。"""

    kind: str
    name: str
    why: str


@dataclass(frozen=True, slots=True)
class Archive:
    """一份档案编译后的全部结构化事实。"""

    source: str
    id: str
    title: str
    country: str
    game_version: str
    why: str
    tempo: Tempo | None
    memory: Memory
    pressure: Pressure
    journal_entry: JournalEntry
    localization: tuple[Localization, ...]
    cards: tuple[Card, ...]
    cards_why: str
    references: tuple[Reference, ...]
    numbers: tuple[Number, ...]
    whys: tuple[tuple[str, str], ...]
    inputs: Inputs | None = None
    #: P11 的三行解释：``(槽位, 本地化键, why)``。**可空** —— 没写 `[panel]` 的档案
    #: 不生成这三个键（缺省不是"生成一个空行"，见 :data:`PANEL_LINES`）。
    panel: tuple[tuple[str, str, str], ...] = ()
    #: 难度三档（**mod 级**：0 份或 2 份都当场报错，照 `[tempo]` 的口径）。
    difficulty: Difficulty | None = None
    #: 探针口径（可选表 `[probe]`）：本档案盯哪条法。
    probe: Probe | None = None

    @property
    def effect_file(self) -> str:
        return f"common/scripted_effects/{FILE_PREFIX}{self.id}_effects.txt"

    @property
    def modifier_file(self) -> str:
        return f"common/static_modifiers/{FILE_PREFIX}{self.id}_pressure.txt"

    @property
    def inputs_file(self) -> str:
        return f"common/static_modifiers/{FILE_PREFIX}{self.id}_reform_inputs.txt"

    @property
    def journal_file(self) -> str:
        return f"common/journal_entries/{FILE_PREFIX}{self.id}_window.txt"

    @property
    def defines_file(self) -> str:
        """节奏杠杆的产物路径。

        名字仍带**声明它的那份档案**的 id（`sitai_<id>_tempo.txt`）—— 它是全局的，
        档案只是它的来源（见 :func:`defines_text` 的注释头）。没有 `[tempo]` 的档案
        不产出这个文件，所以 :func:`archive_files` 只在 `tempo is not None` 时收它。
        """
        return f"common/defines/{FILE_PREFIX}{self.id}_tempo.txt"

    @property
    def doc_file(self) -> str:
        return f"{FILE_PREFIX}{self.id}.md"

    def loc_file(self, lang: str) -> str:
        return f"localization/{lang}/{FILE_PREFIX}{self.id}_l_{lang}.yml"

    def card_file(self, card: Card) -> str:
        slug = card.name.removeprefix("ai_strategy_")
        return f"common/ai_strategies/{slug}.txt"


def archive_files(archive: Archive) -> tuple[str, ...]:
    """这份档案**自己的**产物路径（不含 mod 级产物）。

    闸门 ④ 用它把"从产物反解出来的事实"按档案切开 —— 多档案时拿全产物并集去比，
    会把别家档案的事实算成"多出"。
    """
    out = [archive.effect_file, archive.modifier_file, archive.journal_file, archive.doc_file]
    if archive.tempo is not None:
        out.append(archive.defines_file)
    if archive.inputs is not None:
        out.append(archive.inputs_file)
    if archive.difficulty is not None:
        # 难度三档的两个产物（照 `[tempo]` 的口径按**声明它的档案**命名）。
        # ⚠️ 条件必须与 `_build_one` 里完全一致：修正文件在"没有任何档位带玩家侧修正"
        # 时**不产出** —— 这里多列一个，闸门 ④/⑤ 会报"产物读不到"（实测踩过）。
        out.append(archive.difficulty.rule_file)
        if archive.difficulty.tiers_with_player_effects():
            out.append(archive.difficulty.modifier_file)
    out.extend(archive.loc_file(lang) for lang in sorted(LANGUAGES))
    out.extend(archive.card_file(card) for card in archive.cards)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Built:
    """一次 build 的产物：相对路径 → 文本（**不含 BOM**，写盘时才加）。"""

    archive_ids: tuple[str, ...]
    files: dict[str, str]
    numbers: tuple[Number, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self.files))

    @property
    def game_side(self) -> tuple[str, ...]:
        return tuple(p for p in self.paths if p.endswith(GAME_SIDE_SUFFIXES))


# ── 数字与文本的小工具 ──────────────────────────────────────
def num(value: float) -> str:
    """数字 → PDX 字面量。

    整数不带小数点（原版写 ``-20`` 不写 ``-20.0``）；小数用 Python 的最短往返
    表示（``repr``），因此 ``0.2`` 写成 ``0.2`` 而不是 ``0.20000000000000001``。
    """
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def _require_table(raw: object, path: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise DataError(f"{path} 应当是表（table），实为 {type(raw).__name__}")
    return raw


def _require_text(raw: Mapping[str, object], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DataError(f"{path}.{key} 必须是非空字符串")
    return value.strip()


def _require_seq(raw: Mapping[str, object], key: str, path: str) -> list[object]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise DataError(f"{path}.{key} 应当是数组")
    return value


def _entries(raw: Mapping[str, object], key: str, path: str) -> list[dict[str, object]]:
    return [
        _require_table(item, f"{path}.{key}[{i}]")
        for i, item in enumerate(_require_seq(raw, key, path))
    ]


def _amount(raw: Mapping[str, object], path: str) -> float:
    value = raw.get("amount")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataError(f"{path}.amount 必须是数字")
    return float(value)


def _why(raw: Mapping[str, object], path: str) -> str:
    return _require_text(raw, "why", path)


def _arg(raw: Mapping[str, object], path: str) -> str:
    """取 ``arg``（非数值的右值，例如原版策略 id）。"""
    return _require_text(raw, "arg", path)


# ── why 的机械校验（P10）────────────────────────────────────
def audit(raw: object, path: str = "") -> tuple[tuple[Number, ...], tuple[tuple[str, str], ...]]:
    """递归遍历数据源：收齐**每个数字**与**每张表的依据**，并检查空 `why`。

    一次收全再报错（而不是遇到第一个就抛）：数据源缺依据时，作者要的是一份
    "哪几处缺"的清单，不是一条一条试。

    ⚠️ 口径是**每张非根表都要有 why**，容器表（如 `[panel]`）也不例外 ——
    容器表的 `why` 回答的是「**为什么这几行要放在一起**」，那不是噪声：
    它能挡住"随手往容器里塞第四行"这种漂移。**不要**为容器开例外：
    开一次例外，以后每张新表都会问"我算不算容器"（2026-09-22 试过，退回）。
    """
    numbers: list[Number] = []
    whys: list[tuple[str, str]] = []
    missing: list[str] = []

    def walk(node: object, where: str) -> None:
        if isinstance(node, dict):
            why = node.get("why")
            if not where:
                pass  # 根表：整份数据源本身不需要 why（每张子表各带一条）
            elif not isinstance(why, str) or not why.strip():
                missing.append(where)
            else:
                whys.append((where, why.strip()))
            if "amount" in node:
                numbers.append(
                    Number(path=f"{where}.amount", value=_amount(node, where), why=str(why or ""))
                )
            for key, value in node.items():
                walk(value, f"{where}.{key}" if where else str(key))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{where}[{index}]")

    walk(raw, path)
    if missing:
        raise DataError(
            "数据源里这些表没有 why（P10：每个数字都必须带依据，判据与文案同样如此）：\n  "
            + "\n  ".join(missing)
        )
    return tuple(numbers), tuple(whys)


# ── 数据源的解析 ────────────────────────────────────────────
def read_source(path: Path) -> dict[str, object]:
    """读一份 TOML 数据源。读不了 / 不是表都当场报错。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DataError(f"读不到数据源 {path}：{type(exc).__name__}: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8-sig"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise DataError(f"数据源不是合法 TOML：{path}（{type(exc).__name__}: {exc}）") from exc
    return _require_table(data, str(path))


def _params(raw: Mapping[str, object], key: str, path: str) -> tuple[Param, ...]:
    """解析一组参数条目：每条要么给 ``amount``（数字），要么给 ``arg``（标识符）。

    为什么要显式**互斥校验**：两者同时出现时，"``set_strategy = 1.0``" 这种产物会带着
    一个没人看的数字悄悄生成出来 —— 而那正是「每个数字都有依据」（P10）最容易被绕过的地方。
    """
    out: list[Param] = []
    for i, item in enumerate(_entries(raw, key, path)):
        where = f"{path}.{key}[{i}]"
        has_amount = "amount" in item
        has_arg = "arg" in item
        if has_amount == has_arg:
            raise DataError(f"{where} 必须**恰好**给一个 amount 或 arg（现在 amount={has_amount}）")
        out.append(
            Param(
                key=_require_text(item, "key", where),
                amount=_amount(item, where) if has_amount else 0.0,
                why=_why(item, where),
                arg=_arg(item, where) if has_arg else "",
            )
        )
    return tuple(out)


#: `set_strategy` 允许递出的**原版**策略 id。
#:
#: ⚠️ 这里刻意**只列原版的牌**：递自建牌会抢政治槽（每国同时只有一张政治牌在用，
#: 阶段 2 实测 1.05%/国·月重抽），而 F5 的口径是"能改世界就不占槽、只有整条路线要换
#: 才递牌"。递原版已有的牌不新增竞争，只是把落点拨到那一条路线上去。
#: 三张议程牌的差异见 `docs/design/backlog.md` B53/B54。
SET_STRATEGY_WHITELIST: frozenset[str] = frozenset(
    {
        "ai_strategy_progressive_agenda",
        "ai_strategy_reactionary_agenda",
        "ai_strategy_conservative_agenda",
        "ai_strategy_egalitarian_agenda",
    }
)

#: `[journal_entry.signals]` 允许的键 → 它对应生成器的哪个块。
SIGNAL_KEYS: dict[str, str] = {
    "set_strategy": "immediate",
    "clear_strategy": "on_complete",
}


def _signals(journal_raw: Mapping[str, object], source: str) -> Signals:
    """解析可选的 ``[journal_entry.signals]`` 表。

    可选是**有意的**：绝大多数档案只改世界状态（A 级）就够，不需要递牌；
    硬性要求会让数据源多写一堆空表。缺省时 ``Signals.empty`` 为真，产物里
    **不生成** ``immediate`` / ``on_complete`` 两个块（不是生成空块）。
    """
    if "signals" not in journal_raw:
        return Signals(set_strategy=(), clear_strategy=(), why="（本档案不递牌）")
    raw = _require_table(journal_raw["signals"], f"{source}:journal_entry.signals")
    set_params = _params(raw, "set_strategy", "journal_entry.signals")
    clear_params = _params(raw, "clear_strategy", "journal_entry.signals")
    for param in (*set_params, *clear_params):
        if not param.arg:
            raise DataError(
                f"journal_entry.signals.{param.key} 必须用 `arg` 而不是 `amount` —— "
                "递牌递的是标识符（`set_strategy = ai_strategy_x`），"
                "写数字会生成一句没人认的 `set_strategy = 1`"
            )
        if param.arg not in SET_STRATEGY_WHITELIST:
            raise DataError(
                f"journal_entry.signals.{param.key} 的 arg={param.arg!r} 不在白名单里。"
                f"可用：{sorted(SET_STRATEGY_WHITELIST)}（只许递原版已有的牌，见 P10 与 F5）"
            )
    return Signals(
        set_strategy=set_params,
        clear_strategy=clear_params,
        why=_why(raw, "journal_entry.signals"),
    )


def _clause(item: dict[str, object], path: str, *, gate: str | None = None) -> Condition:
    """一条判据。

    ``gate`` 只有 JE 的判据需要（它决定挂在 ``possible`` 还是 ``complete`` 里）；
    递牌的 ``possible`` 里没有这一层，所以是**可选**字段 —— 硬性要求会让
    数据源多写一堆无意义的 `gate = "possible"`。
    """
    op = item.get("op", "=")
    if not isinstance(op, str):
        raise DataError(f"{path}.op 必须是字符串")
    arg = item.get("arg")
    if arg is not None and not isinstance(arg, str):
        raise DataError(f"{path}.arg 必须是字符串")
    has_amount = "amount" in item
    if arg is None and not has_amount:
        raise DataError(f"{path} 既没有 arg 也没有 amount —— 判据没有操作数")
    if gate is None and "gate" in item:
        gate = _require_text(item, "gate", path)
    return Condition(
        key=_require_text(item, "key", path),
        why=_why(item, path),
        op=op,
        arg=arg,
        amount=_amount(item, path) if has_amount else None,
        gate=gate or "",
    )


def parse_source(data: Mapping[str, object], source: str) -> Archive:
    """把一份已读入的数据源编译成 :class:`Archive`。"""
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise DataError(
            f"{source} 的 schema_version 是 {version!r}，本生成器只认 {SCHEMA_VERSION}"
            "（口径见 tools/pdx/modgen.py 的模块文档）"
        )

    numbers, whys = audit(data)

    archive = _require_table(data.get("archive"), f"{source}:archive")
    memory_raw = _require_table(data.get("memory"), f"{source}:memory")
    pressure_raw = _require_table(data.get("pressure"), f"{source}:pressure")
    journal_raw = _require_table(data.get("journal_entry"), f"{source}:journal_entry")
    cards_raw = _require_table(data.get("cards"), f"{source}:cards")

    # `[tempo]` 是**可选**的 mod 级表（schema v1）：第二份档案不该复制一遍全局 defines。
    # "恰好一份"这条由 build_all 在全仓范围上判 —— 单份数据源看不出这件事。
    tempo: Tempo | None = None
    if "tempo" in data:
        tempo_raw = _require_table(data["tempo"], f"{source}:tempo")
        tempo = Tempo(
            block=_require_text(tempo_raw, "block", "tempo"),
            why=_why(tempo_raw, "tempo"),
            keys=_params(tempo_raw, "keys", "tempo"),
        )
    memory = Memory(
        variable=_require_text(memory_raw, "variable", "memory"),
        effect=_require_text(memory_raw, "effect", "memory"),
        why=_why(memory_raw, "memory"),
        params=_params(memory_raw, "params", "memory"),
    )
    pressure = Pressure(
        name=_require_text(pressure_raw, "name", "pressure"),
        icon=_require_text(pressure_raw, "icon", "pressure"),
        why=_why(pressure_raw, "pressure"),
        params=_params(pressure_raw, "params", "pressure"),
        effects=_params(pressure_raw, "effects", "pressure"),
    )
    conditions = tuple(
        _clause(item, f"journal_entry.conditions[{i}]")
        for i, item in enumerate(_entries(journal_raw, "conditions", "journal_entry"))
    )
    unknown = sorted({c.gate for c in conditions} - set(GATE_ORDER))
    if unknown:
        raise DataError(
            f"journal_entry.conditions 里有不认识的判据块 {unknown}；"
            f"可用：{list(GATE_ORDER)}（顺序固定，见 GATE_ORDER 的注释）"
        )
    journal = JournalEntry(
        name=_require_text(journal_raw, "name", "journal_entry"),
        group=_require_text(journal_raw, "group", "journal_entry"),
        icon=_require_text(journal_raw, "icon", "journal_entry"),
        why=_why(journal_raw, "journal_entry"),
        fields=_params(journal_raw, "fields", "journal_entry"),
        conditions=conditions,
        signals=_signals(journal_raw, source),
    )
    journal_name = journal.name
    # `[panel]`（可选表，三行解释 P11）在后面与 `localization` 一起解析 ——
    # 键名由 JE 名派生（`<je 名>_goal` 等），所以必须在 journal 之后。

    # `[reform_inputs]` 是**可选**表：老档案（只有冲击一处处理）照样编译。
    # 缺省不是"静默降级"——产物清单与档案文档都会写明这一份档案有没有第二处理段。
    inputs: Inputs | None = None
    if "reform_inputs" in data:
        inputs_raw = _require_table(data["reform_inputs"], f"{source}:reform_inputs")
        inputs = Inputs(
            name=_require_text(inputs_raw, "name", "reform_inputs"),
            effect=_require_text(inputs_raw, "effect", "reform_inputs"),
            icon=_require_text(inputs_raw, "icon", "reform_inputs"),
            why=_why(inputs_raw, "reform_inputs"),
            params=_params(inputs_raw, "params", "reform_inputs"),
            effects=_params(inputs_raw, "effects", "reform_inputs"),
        )

    localization: list[Localization] = []
    for index, item in enumerate(_require_seq(data, "localization", "localization")):
        where = f"localization[{index}]"
        entry = _require_table(item, where)
        values: dict[str, str] = {}
        for lang in LANGUAGES:
            text = entry.get(lang)
            if not isinstance(text, str) or not text.strip():
                raise DataError(
                    f"{where}（键 {entry.get('key')!r}）缺 {lang} 文案 —— "
                    "支持的语言见 modgen.LANGUAGES，缺一种就是漏一种"
                )
            if '"' in text:
                raise DataError(
                    f"{where} 的 {lang} 文案里有裸双引号 —— `.yml` 的值用双引号包裹，"
                    "引擎对转义的支持没有实测证据，所以这里直接拒绝（P13）"
                )
            values[lang] = text
        localization.append(
            Localization(
                key=_require_text(entry, "key", where), why=_why(entry, where), values=values
            )
        )

    # `[panel]` 是**可选**表：三行解释（P11）。缺省 = 不生成那三个键。
    # 每行既要文案（进 `localization`）又要 `why`（P10）⇒ 在这里一起收，
    # 文案走的仍是同一个 `localization` 列表（单一数据源，P9）。
    panel: list[tuple[str, str, str]] = []
    if "panel" in data:
        panel_raw = _require_table(data["panel"], f"{source}:panel")
        for slot, suffix in PANEL_LINES:
            if slot not in panel_raw:
                raise DataError(
                    f"{source}:panel 缺 `{slot}` —— 三行解释要么三行都写，要么整表不写"
                    f"（可用槽位：{[name for name, _ in PANEL_LINES]}）"
                )
            line = _require_table(panel_raw[slot], f"{source}:panel.{slot}")
            key = f"{journal_name}_{suffix}"
            line_values: dict[str, str] = {}
            for lang in LANGUAGES:
                text = line.get(lang)
                if not isinstance(text, str) or not text.strip():
                    raise DataError(f"{source}:panel.{slot} 缺 {lang} 文案")
                if '"' in text:
                    raise DataError(f"{source}:panel.{slot} 的 {lang} 文案里有裸双引号")
                line_values[lang] = text
            line_why = _why(line, f"{source}:panel.{slot}")
            localization.append(Localization(key=key, why=line_why, values=line_values))
            panel.append((slot, key, line_why))

    # **把三行接进 JE 的说明里**（阶段 6 的 G3）：引擎真正显示的那一处是
    # `journal_entry.gui:742` 的 `text = "[JournalEntry.GetReason]"` ⇒ 读的是
    # `<JE 名>_reason` 这条 loc。三行各自仍是**独立键**（能单独核对、将来能接到
    # 脚本化 GUI 的三行控件上），但从这一刻起它们也**真的上屏**了。
    #
    # ⚠️ 为什么不是只靠 `<JE 名>_goal`：引擎会为它报
    # `journal_entry_type.cpp:476 Journal entry has redundant loc for <JE 名>_goal`
    # （实测 2026-09-23），也就是说"goal 那一槽到底显不显示"**没有把握**；
    # 而 `_reason` 有 GUI 代码为证。于是：说明里三行齐全（目标/压力/上次改主意的原因），
    # `_goal` 那一条照旧保留 —— 两处都有目标不算错，缺一处才会让 G3 判不了。
    #
    # ⚠️ 拼接用的是**字面量** `\n\n`（两个字符），不是真换行：数据源里的换行就是
    # 字面量（见 committed 的 yml —— 每条 key 一行、文件 9 行）。第一版写成真换行，
    # 结果是 yml 变 12 行、`_reason` 的值被拆成 4 行而**后三行没有 key** ⇒ 一份坏掉的
    # 本地化文件（反解时静默丢掉那三行）。
    if panel:
        reason_key = f"{journal_name}_reason"
        reason_index = next(
            (index for index, item in enumerate(localization) if item.key == reason_key), None
        )
        if reason_index is None:
            # **缺 `_reason` 就报错**，不是"那就只留三个独立键"：引擎显示的是
            # `[JournalEntry.GetReason]`，"没接进去"等于三行**根本没上屏**，
            # 而产物看上去一切正常 —— G3 判的正是"试玩者能不能复述"，静默失败最贵。
            raise DataError(
                f"{source}:panel 需要一条 `{reason_key}` 本地化（引擎显示的是它）—— "
                "三行解释要上屏就得接进 JE 说明，请补一条 "
                f'`[[localization]] key = "{reason_key}"`'
            )
        reason_entry = localization[reason_index]
        merged = {lang: reason_entry.values[lang] for lang in LANGUAGES}
        # ⚠️ 循环变量**不能叫 `_why`**：那会把同名的模块函数在**整个函数作用域**里
        # 遮蔽掉，于是上面 `Pressure(...)` 那几处 `_why(...)` 直接
        # `UnboundLocalError: cannot access local variable '_why'`（实测踩过）。
        for _slot_name, panel_key, _panel_why in panel:
            panel_entry = next(item for item in localization if item.key == panel_key)
            for lang in LANGUAGES:
                merged[lang] = f"{merged[lang]}\\n\\n{panel_entry.values[lang]}"
        localization[reason_index] = Localization(
            key=reason_key, why=reason_entry.why, values=merged
        )

    # `[probe]`（可选表）：探针口径 —— 本档案盯哪条法（B80）。
    probe: Probe | None = None
    if "probe" in data:
        raw = _require_table(data["probe"], f"{source}:probe")
        reform_law = raw.get("reform_law", "")
        if not isinstance(reform_law, str):
            raise DataError(f"{source}:probe.reform_law 必须是字符串（留空 = 没查实）")
        if reform_law and not reform_law.startswith("law_"):
            raise DataError(
                f"{source}:probe.reform_law 要写原版的法律键（law_ 开头），现在 {reform_law!r}"
            )
        probe = Probe(why=_why(raw, f"{source}:probe"), reform_law=reform_law)

    # `[difficulty]`（可选表，**mod 级**）：难度三档（阶段 6 / 契约 J5）。
    # 与 `[tempo]` 同一口径：全仓恰好一份，校验交给 `_check_difficulty`。
    difficulty: Difficulty | None = None
    if "difficulty" in data:
        raw = _require_table(data["difficulty"], f"{source}:difficulty")
        difficulty = Difficulty(
            key=_require_text(raw, "key", f"{source}:difficulty"),
            why=_why(raw, f"{source}:difficulty"),
            # 产物与修正名都按**声明它的那份档案**命名（照 `[tempo]` 的口径：
            # 它是全局的，档案只是它的来源）。
            owner_id=_require_text(archive, "id", "archive"),
            icon=_require_text(raw, "icon", f"{source}:difficulty"),
            tiers=_parse_difficulty_tiers(
                raw, source, _require_text(archive, "id", "archive"), localization
            ),
        )

    cards: list[Card] = []
    for index, item in enumerate(_entries(cards_raw, "items", "cards")):
        where = f"cards.items[{index}]"
        weight_raw = _require_table(item.get("weight"), f"{where}.weight")
        cards.append(
            Card(
                name=_require_text(item, "name", where),
                slot=_require_text(item, "slot", where),
                weight=_amount(weight_raw, f"{where}.weight"),
                why=_why(item, where),
                possible=tuple(
                    _clause(entry, f"{where}.possible[{i}]")
                    for i, entry in enumerate(_entries(item, "possible", where))
                ),
                fields=_params(item, "fields", where),
            )
        )

    references = tuple(
        Reference(
            kind=_require_text(entry, "kind", f"references[{i}]"),
            name=_require_text(entry, "name", f"references[{i}]"),
            why=_why(entry, f"references[{i}]"),
        )
        for i, entry in enumerate(
            _require_table(item, f"references[{i}]")
            for i, item in enumerate(_require_seq(data, "references", "references"))
        )
    )

    parsed = Archive(
        source=source,
        id=_require_text(archive, "id", "archive"),
        title=_require_text(archive, "title", "archive"),
        country=_require_text(archive, "country", "archive"),
        game_version=_require_text(archive, "game_version", "archive"),
        why=_why(archive, "archive"),
        tempo=tempo,
        memory=memory,
        pressure=pressure,
        journal_entry=journal,
        localization=tuple(localization),
        cards=tuple(cards),
        cards_why=_why(cards_raw, "cards"),
        references=references,
        numbers=numbers,
        whys=whys,
        inputs=inputs,
        panel=tuple(panel),
        difficulty=difficulty,
        probe=probe,
    )
    _check_namespace(parsed)
    return parsed


def _check_namespace(archive: Archive) -> None:
    """F7：命名空间 `sitai_*`、文件 `sitai_*.txt`。

    这条检查在**生成之前**做（闸门 ① 也会做一遍）—— 早早报错的代价远低于
    "产出一份污染了原版命名空间的文件"。
    """
    named = {
        "memory.variable": archive.memory.variable,
        "memory.effect": archive.memory.effect,
        "pressure.name": archive.pressure.name,
        "journal_entry.name": archive.journal_entry.name,
    }
    if archive.inputs is not None:
        named["reform_inputs.name"] = archive.inputs.name
        named["reform_inputs.effect"] = archive.inputs.effect
    for card in archive.cards:
        named[f"cards.{card.name}"] = card.name
    bad = [f"{k}={v!r}" for k, v in named.items() if not NAMESPACE_RE.match(v)]
    if bad:
        raise DataError(
            f"这些名字不在命名空间 `{(NAMESPACE_RE.pattern)}` 里（F7）：{', '.join(bad)}"
        )


def load_data(path: Path) -> Archive:
    """读一份数据源并编译成档案（含 `why` 校验与命名空间校验）。"""
    return parse_source(read_source(path), path.name)


def data_files(data_dir: Path | None = None) -> tuple[Path, ...]:
    """数据源目录下的全部档案（按文件名排序 —— 确定性的第一环）。"""
    base = data_dir or DATA_DIR
    if not base.is_dir():
        return ()
    return tuple(sorted(base.glob(f"*{DATA_SUFFIX}")))


def load_all(data_dir: Path | None = None) -> tuple[Archive, ...]:
    """读全部数据源。一份都没有时报错（空产物不是"成功"）。"""
    files = data_files(data_dir)
    if not files:
        raise DataError(f"{data_dir or DATA_DIR} 下没有 {DATA_SUFFIX} 数据源")
    return tuple(load_data(path) for path in files)


# ── 产物文本 ────────────────────────────────────────────────
#: 一个可渲染节点：一行文本（``key = value`` / 注释 / 空行），或 ``(块名, 子节点)``。
Node = str | tuple[str, "list[Node]"]


def _render(node: Node, indent: int = 0) -> list[str]:
    """把节点渲染成行。

    为什么要有它（而不是拼字符串）：脚本是**嵌套**的（效果里套 set_variable、
    JE 里套 possible），手拼缩进一旦错一层，产物在游戏里表现为"这段不生效"，
    而肉眼要盯着看很久。这里缩进由 ``indent`` 推出来，嵌套多深都不会错。
    空行不补缩进 —— 否则产物里会出现尾随空白，逐字节比对时成为噪声。
    """
    pad = TAB * indent
    if isinstance(node, str):
        return ["" if not node else f"{pad}{node}"]
    name, body = node
    out = [f"{pad}{name} = {{"]
    for child in body:
        out.extend(_render(child, indent + 1))
    out.append(f"{pad}}}")
    return out


def _comment(*lines: str) -> list[Node]:
    """注释段落（末尾补一个空行 —— 与脚本正文分开）。"""
    out: list[Node] = [f"# {line}" if line else "#" for line in lines]
    out.append("")
    return out


def _difficulty_branches(archive: Archive) -> list[Node]:
    """冲击效果里"给玩家追加难度修正"的那几个 `if` 块（没有难度表就返回空）。

    判据用 `is_ai = no` + `has_game_rule = <设置名>`：前者保证只碰玩家，
    后者是原版同款读法。时长**复用压力修正的 `years`**（同一段窗口，
    否则会出现"压力还在、难度修正没了"的半截状态）。
    """
    difficulty = archive.difficulty
    if difficulty is None:
        return []
    years = next((item for item in archive.pressure.params if item.key == "years"), None)
    if years is None:
        # 没有 years 就没法对齐窗口 ⇒ 宁可不生成（生成一条"永久"的难度修正
        # 会和压力修正的寿命错开，那是最难查的一类不一致）。闸门 ⑤ 会看到
        # "数据源声明了档位、产物里没有分支"吗？不会 —— 所以这里当场报错。
        raise DataError(
            f"{archive.source}:difficulty 需要 [pressure.params] 里有 `years`"
            "（难度修正与压力修正必须同一段窗口，见 why）"
        )
    return [
        (
            "if",
            [
                ("limit", ["is_ai = no", f"has_game_rule = {tier.setting}"]),
                (
                    "add_modifier",
                    [f"name = {tier.modifier}", f"years = {num(years.amount)}"],
                ),
            ],
        )
        for tier in difficulty.tiers_with_player_effects()
    ]


def effects_text(archive: Archive) -> str:
    """冲击记账效果：写记忆变量 + 挂压力修正（有第二处理段时再附一个效果）。"""
    memory = archive.memory
    set_variable: Node = (
        "set_variable",
        [f"name = {memory.variable}", *(f"{p.key} = {num(p.amount)}" for p in memory.params)],
    )
    add_modifier: Node = (
        "add_modifier",
        [
            f"name = {archive.pressure.name}",
            *(f"{p.key} = {num(p.amount)}" for p in archive.pressure.params),
        ],
    )
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"{archive.title} · 冲击记账（A 级：真实世界状态 —— 变量 + 修正，不占任何槽位）。",
            "调用方：A/B 实验（B 组显式施加冲击）。本档案刻意**不绑 on_action**："
            "「什么才算这次冲击」的判定留给实验给结论，",
            "由谁写、写在哪，见本档案 why 与数据源（每个数字都带依据，P10）。",
            f"变量 {memory.variable}；压力修正 {archive.pressure.name}。",
        ),
        (memory.effect, [set_variable, add_modifier, *_difficulty_branches(archive)]),
    ]
    inputs = archive.inputs
    if inputs is not None:
        lines += [
            "",
            *_comment(
                f"改革侧输入（A 级：同样是真实世界状态）：{inputs.why}",
                "为什么单独一个效果：实验的 B 段只施加冲击、B2 段才追加这一处 ——",
                "两处合并在一个效果里就分不出是哪一处起了作用（执行文档：两层分开报）。",
                f"修正 {inputs.name}；效果名 {inputs.effect}（不绑 on_action，由实验显式调用）。",
            ),
            (
                inputs.effect,
                [
                    (
                        "add_modifier",
                        [
                            f"name = {inputs.name}",
                            *(f"{p.key} = {num(p.amount)}" for p in inputs.params),
                        ],
                    )
                ],
            ),
        ]
    return "\n".join(_flatten(lines))


def inputs_text(archive: Archive) -> str:
    """改革侧输入修正：把原版自己的读入抬起来（不递牌，仍走 A 级）。

    只有数据源里有 `[reform_inputs]` 时才生成 —— 调用方要先看
    :attr:`Archive.inputs` 是不是 ``None``（生成器不猜）。
    """
    inputs = archive.inputs
    if inputs is None:  # pragma: no cover - 调用方按 Archive.inputs 分支，这里只兜底
        raise DataError(f"档案 {archive.id} 没有 [reform_inputs]，不该走到这里")
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"改革侧输入（A 级）：{inputs.why}",
            f"每条字段的依据见 {FILE_PREFIX}{archive.id}.md（由 why_report 生成）。",
            "⚠️ 这一份**不是**冲击本身：它是实验的第二处理段（B2）才挂的东西 ——",
            "写进 [pressure] 会让「只加冲击」的那一段消失。",
        ),
        (
            inputs.name,
            [f"icon = {inputs.icon}", *(f"{p.key} = {num(p.amount)}" for p in inputs.effects)],
        ),
    ]
    return "\n".join(_flatten(lines))


def modifier_text(archive: Archive) -> str:
    """压力修正：真实的合法性 / 贵族 / 财政变化。"""
    pressure = archive.pressure
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"处境压力（A 级）：{archive.title}。每条字段都照原版同族用法取档位，",
            f"每条的依据见 {FILE_PREFIX}{archive.id}.md（由 why_report 生成）。",
        ),
        (
            pressure.name,
            [f"icon = {pressure.icon}", *(f"{p.key} = {num(p.amount)}" for p in pressure.effects)],
        ),
    ]
    return "\n".join(_flatten(lines))


def difficulty_rule_text(difficulty: Difficulty) -> str:
    """难度三档的 `game_rules` 文件（阶段 6 / 契约 J5）。

    机制只用**原版有先例**的那一种：设置块里写 `flag = <设置名>`，脚本侧用
    `has_game_rule = <设置名>` 读（原版 `00_default_strategy.txt:4601/7096/…` 就是这么读的）。
    `game_rules.md:5` 还写了 `apply_modifier`，但 1.14.3 的 `common/game_rules/` 里
    **0 处使用**（实测）—— 先例为零的写法不当承重墙。
    """
    settings: list[Node] = [(tier.setting, [f"flag = {tier.setting}"]) for tier in difficulty.tiers]
    return "\n".join(
        _flatten(
            [
                GEN_HEADER,
                "",
                *_comment(
                    f"难度三档（{difficulty.why}）",
                    "三档是**对外契约**（01a J 节第 5 条）：史实友好 / 一视同仁（默认）/ 无情。",
                    "默认档**不加戏**：这个 mod 的主张是「处境对谁都成立」，",
                    "默认给玩家开小灶会让「世界活了」变成「世界对我温柔了」。",
                    "读取方式：脚本侧 `has_game_rule = <设置名>`（原版同款用法）。",
                ),
                (
                    difficulty.key,
                    [
                        f"default = {difficulty.tier(DIFFICULTY_DEFAULT).setting}",
                        "",
                        *settings,
                    ],
                ),
            ]
        )
    )


def difficulty_modifier_text(difficulty: Difficulty) -> str:
    """难度档位给**玩家**追加的修正（`一视同仁` 按设计为空 ⇒ 这里可能没有内容）。

    为什么改的是玩家侧而不是"世界状态"：世界状态对谁都成立；难度调的是**玩家肩上
    那一份**（`01a:240`："玩家被压死 → 难度分档"）。
    """
    tiers = difficulty.tiers_with_player_effects()
    if not tiers:
        return ""
    blocks: list[Node] = []
    for tier in tiers:
        blocks += [
            "",
            *_comment(f"{tier.id}：{tier.player_why}"),
            (
                tier.modifier,
                [
                    f"icon = {difficulty.icon}",
                    *(f"{item.key} = {num(item.amount)}" for item in tier.player_effects),
                ],
            ),
        ]
    return "\n".join(
        _flatten(
            [
                GEN_HEADER,
                "",
                *_comment(
                    f"难度档位的玩家侧修正（{difficulty.why}）",
                    "由冲击效果按 `has_game_rule` 施加：玩家命中哪一档，就挂哪一条。",
                    "每个数字的依据见档案文档（P10）。",
                ),
                *blocks,
            ]
        )
    )


def journal_text(archive: Archive) -> str:
    """改革窗口 JE：is_shown / possible / complete 判据 + weight + 递牌信号。"""
    journal = archive.journal_entry
    body: list[Node] = [f'icon = "{journal.icon}"', f"group = {journal.group}"]
    for gate in GATE_ORDER:
        picked = [c for c in journal.conditions if c.gate == gate]
        if not picked:
            continue
        body.append("")
        body.append((gate, [c.render() for c in picked]))
    if journal.fields:
        body.append("")
        body.extend(f"{p.key} = {num(p.amount)}" for p in journal.fields)
    # 递牌：窗口开时换路线（immediate 在 add_journal_entry 时执行），关时换回来。
    # 为什么挂在 JE 上而不是挂在施加冲击的那个效果里：**判据与动作要在一起** ——
    # "窗口开"是判据（legibility 的三行也贴在它上面），"递牌"是窗口的后果。
    # 挂在效果里会让"冲击"与"换路线"绑死，无法分开测（阶段 3 的教训）。
    if journal.signals.set_strategy:
        body.append("")
        body.append(
            (
                "immediate",
                [f"set_strategy = {p.arg}" for p in journal.signals.set_strategy],
            )
        )
    if journal.signals.clear_strategy:
        body.append("")
        body.append(
            (
                "on_complete",
                [f"set_strategy = {p.arg}" for p in journal.signals.clear_strategy],
            )
        )
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"改革窗口 JE（{archive.title}）：判据驱动 —— 只有压力够大才开。",
            "这个 JE 的作用**只有三条**（2026-09-22 实测复核，别读多）：",
            "  ① **玩家可见性**：G3 的三行解释挂在它身上（P11）；",
            "  ② **世界状态判据**：原版脚本可以用 `has_journal_entry = <本 JE 名>` 读它；",
            "  ③ **递牌**：`immediate` 里给该国换一张**原版**策略牌（见下面的 signals 依据）。",
            "⚠️ **它喂不到原版 AI 牌**：原版 212 处 `has_journal_entry` 全部硬编码**具名 JE**",
            "（`ai_strategies/03_political_strategies.txt:137` 读的是 je_metternich 这一串），",
            "**没有「读任意 JE」的通用谓词** —— 我们自己的 JE 一张牌也喂不到。",
            "意图位移的真正通道是**递牌**（`set_strategy`）与**法律承诺**（law commitment），",
            "原因与实测见 `docs/design/backlog.md` B52 / B53–B60。",
            *((f"递牌依据：{journal.signals.why}",) if not journal.signals.empty else ()),
        ),
        (journal.name, body),
    ]
    return "\n".join(_flatten(lines))


def defines_text(archive: Archive) -> str:
    """节奏杠杆：按「块 + 参数」覆盖，**不复制**原版 defines 文件。

    只有声明了 `[tempo]` 的那份档案会产出这个文件（mod 级表，全仓一份）——
    调用方要先看 :attr:`Archive.tempo` 是不是 ``None``（生成器不猜）。
    """
    tempo = archive.tempo
    if tempo is None:  # pragma: no cover - 调用方按 Archive.tempo 分支，这里只兜底
        raise DataError(f"档案 {archive.id} 没有 [tempo]，不该走到这里")
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"节奏杠杆（**全局作用域**：{archive.title} 只是它的来源档案）：只覆盖 {tempo.block} 块的 {len(tempo.keys)} 个键，",
            "不复制原版 00_ai.txt（KB 05 §1.7 的按「块 + 参数」覆盖；阶段 2 的 storm 变体实测生效）。",
            "⚠️ defines 没有单国写法：这两个键一改，**所有国家**的 AI 重抽节奏都变 —— 别把它当成单国效果。",
            "覆盖范围就是下面这几个键 —— 原版别的参数一个都不抄。",
        ),
        (tempo.block, [f"{p.key} = {num(p.amount)}" for p in tempo.keys]),
    ]
    return "\n".join(_flatten(lines))


def card_text(archive: Archive, card: Card) -> str:
    """一张递牌（本档案为空；骨架留着，因为它决定闸门 ③ 的输入形状）。

    ``archive`` 目前只用于注释头（档案 id）—— 保留这个形参是因为牌的
    traceability 迟早要引档案级信息，而调用点（:func:`build`）已按档案分发。
    """
    body: list[Node] = [f"type = {card.slot}"]
    if card.possible:
        body.extend(["", ("possible", [c.render() for c in card.possible])])
    body.extend(["", ("weight", [f"value = {num(card.weight)}"])])
    if card.fields:
        body.append("")
        body.extend(f"{p.key} = {num(p.amount)}" for p in card.fields)
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"递牌（C 级）：{card.name} —— 占 {card.slot} 槽一个位置（档案 {archive.id}）。",
            "定价见闸门 ③（阶段 2 的等效竞争权重表）；档案里没有牌是 F5 的结果，不是漏写。",
        ),
        (card.name, body),
    ]
    return "\n".join(_flatten(lines))


def _flatten(nodes: Sequence[Node]) -> list[str]:
    """把一串节点渲染成行（顶层 indent = 0）。"""
    out: list[str] = []
    for node in nodes:
        out.extend(_render(node))
    return out


def loc_text(archive: Archive, lang: str) -> str:
    """一个语言的本地化文件。

    格式照原版：``l_<语言>:`` 行 + 每行一个 `` KEY:版本 "值"``。**注释头放在
    语言声明行之后**：抽查原版 `localization/english/` 前 60 个 `.yml`，首行是
    语言声明的是 60/60、首行是注释或空行的是 0 —— "首行必须是语言声明" 没有反例，
    而注释在语言行之后是原版常态（如 je_lobby_text_l_english.yml），所以不去试探它。
    """
    lines = [f"{LANGUAGES[lang]}:", GEN_HEADER]
    lines.extend(
        f' {entry.key}:{LOC_VERSION} "{entry.values[lang]}"' for entry in archive.localization
    )
    return "\n".join(lines) + "\n"


def metadata_payload(archives: Sequence[Archive]) -> dict[str, object]:
    """mod 级元数据的内容 —— **唯一来源**（:func:`metadata_text` 与事实表都读它）。

    一份 mod 只有一份元数据，所以它必须由**全部**档案导出，而不是某一份档案的私产：

    * ``name`` / ``short_description``：把各档案的标题与 `why` 连起来
      （单档案时与阶段 3 的产物**逐字节一致**，闸门 ⑤ 守着这条）；
    * ``id``：各档案 id 按字典序用 `-` 连接（单档案时就是 `sitai.<id>`）；
    * ``supported_game_version``：取第一个档案的版本 —— 不一致由 :func:`build_all` 拦下。
    """
    if not archives:
        raise DataError("没有档案就没有元数据（空产物不是成功）")
    return {
        "name": "SITAI 处境档案 · " + "、".join(a.title for a in archives),
        "id": f"{NAMESPACE_PREFIX.rstrip('_')}.{'-'.join(sorted(a.id for a in archives))}",
        "version": MOD_VERSION,
        "supported_game_version": archives[0].game_version,
        "short_description": "\n\n".join(a.why for a in archives),
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": False},
    }


def metadata_text(archives: Sequence[Archive]) -> str:
    """`descriptor` 用的元数据（JSON，**不带 BOM** —— 读它的是启动器）。"""
    return json.dumps(metadata_payload(archives), ensure_ascii=False, indent=2) + "\n"


def doc_text(archive: Archive) -> str:
    """档案文档：人读的那一份 —— 每个数字、每条判据、每个引用与它的依据。"""
    lines = [
        f"# 档案 · {archive.title}",
        "",
        DOC_HEADER,
        "",
        (
            f"* **档案 id**：`{archive.id}`　**国家**：`{archive.country}`　"
            f"**游戏版本**：`{archive.game_version}`"
        ),
        f"* **本档案修什么毛病**：{archive.why}",
        f"* **递牌**：{len(archive.cards)} 张 —— {archive.cards_why}",
        "",
        "## 产物清单",
        "",
        "| 文件 | 作用 |",
        "|---|---|",
        f"| `{archive.effect_file}` | 冲击记账效果（写 `{archive.memory.variable}` + 挂 `{archive.pressure.name}`） |",
        f"| `{archive.modifier_file}` | 压力修正（真实的合法性 / 贵族 / 财政变化） |",
        f"| `{archive.journal_file}` | 改革窗口 JE（判据驱动） |",
        *(
            [(f"| `{archive.defines_file}` | 节奏杠杆（覆盖 `{archive.tempo.block}` 块） |")]
            if archive.tempo is not None
            else ["| —— | 本档案不声明 `[tempo]`（全仓一份的 mod 级表，由另一份数据源声明） |"]
        ),
        *(
            [
                (
                    f"| `{archive.inputs_file}` | 改革侧输入修正（第二处理段 B2 才挂；"
                    f"`{archive.inputs.effect}` 施加） |"
                )
            ]
            if archive.inputs is not None
            else [
                (
                    "| —— | 本档案没有第二处理段（数据源里没有 `[reform_inputs]`）："
                    "实验只有「加冲击 / 不加冲击」两段 |"
                )
            ]
        ),
        *(f"| `{archive.loc_file(lang)}` | {lang} 文案 |" for lang in sorted(LANGUAGES)),
        "| `.metadata/metadata.json` | mod 元数据（启动器读；不带 BOM） |",
        "",
        "## 每个数字与它的依据（P10）",
        "",
        why_report(archive),
        "",
        "## 判据（JE）",
        "",
        "| 判据块 | 判据 | 为什么 |",
        "|---|---|---|",
        *(f"| `{c.gate}` | `{c.render()}` | {c.why} |" for c in archive.journal_entry.conditions),
        "",
        "## 面板三行（P11 / G3）",
        "",
        *(
            [
                "| 行 | 本地化键 | 为什么是这一行 |",
                "|---|---|---|",
                *(f"| {slot} | `{key}` | {why} |" for slot, key, why in archive.panel),
                "",
                (
                    "> 为什么拆成三个键而不是揉进 `_reason`：G3 判的是**试玩者能复述**"
                    "「当前目标 + 主因」，揉在一起就分不清是哪一行没写清楚。缺行当场可见。"
                ),
            ]
            if archive.panel
            else ["> 本档案**没有** `[panel]`（三行解释）—— 缺省不生成那三个键。"]
        ),
        "",
        "## 声明式引用（闸门 ② 逐条核对）",
        "",
        "| 类别 | 名字 | 为什么 |",
        "|---|---|---|",
        *(f"| `{r.kind}` | `{r.name}` | {r.why} |" for r in archive.references),
        "",
        "## 复算",
        "",
        "```text",
        "v3 modgen --write     # 数据源 → 产物（改完 TOML 必跑）",
        "v3 modguard           # 五道闸门（不通过不许进游戏）",
        "v3 modgen --why       # 只列每个数字与它的依据",
        "```",
        "",
    ]
    return "\n".join(lines)


# ── 编译 ────────────────────────────────────────────────────
def _parse_difficulty_tiers(
    raw: Mapping[str, object],
    source: str,
    owner_id: str,
    localization: list[Localization],
) -> tuple[DifficultyTier, ...]:
    """解析三档，并把三档的本地化键（`setting_*` / `setting_*_desc`）收进 loc 表。

    三条硬校验：**档位集合必须正好是契约那三档**、**规则键要有 loc**、
    **每档都要有中英文名与说明**（缺一个玩家就会在开局规则界面看到裸键）。
    """
    tiers_raw = _require_table(raw.get("tiers"), f"{source}:difficulty.tiers")
    # 容器表自己也有 `why`（审计要求每张非根表都带依据）—— 它不是档位，先剔掉再比集合。
    unknown = sorted(set(tiers_raw) - set(DIFFICULTY_TIERS) - {"why"})
    missing = [name for name in DIFFICULTY_TIERS if name not in tiers_raw]
    if unknown or missing:
        raise DataError(
            f"{source}:difficulty.tiers 必须正好是 {list(DIFFICULTY_TIERS)}"
            f"（多出来：{unknown or '无'}；缺：{missing or '无'}）—— 三档是对外契约，"
            "名字由 `DIFFICULTY_TIERS` 钉住，数据源只能在三档里填内容"
        )
    rule_key = _require_text(raw, "key", f"{source}:difficulty")
    if not rule_key.startswith("sitai_"):
        raise DataError(
            f"{source}:difficulty.key 必须以 sitai_ 开头（F7 命名空间），现在 {rule_key!r}"
        )
    if f"rule_{rule_key}" not in {item.key for item in localization}:
        raise DataError(
            f"{source}:difficulty 需要一条 `rule_{rule_key}` 本地化（规则名要在界面上显示）"
        )
    tiers: list[DifficultyTier] = []
    for tier_id in DIFFICULTY_TIERS:
        where = f"{source}:difficulty.tiers.{tier_id}"
        item = _require_table(tiers_raw[tier_id], where)
        labels: dict[str, str] = {}
        descs: dict[str, str] = {}
        for lang in LANGUAGES:
            labels[lang] = _require_text(item, f"label_{lang}", where)
            descs[lang] = _require_text(item, f"desc_{lang}", where)
        player_effects = _params(item, "player_effects", where) if "player_effects" in item else ()
        tier = DifficultyTier(
            id=tier_id,
            rule_key=rule_key,
            label=labels,
            desc=descs,
            why=_why(item, where),
            modifier=f"sitai_{owner_id}_difficulty_{tier_id}",
            player_effects=player_effects,
            player_why=_require_text(item, "player_why", where) if player_effects else "",
        )
        tiers.append(tier)
        localization.append(
            Localization(
                key=tier.setting, why=tier.why, values={lang: labels[lang] for lang in LANGUAGES}
            )
        )
        localization.append(
            Localization(
                key=f"{tier.setting}_desc",
                why=tier.why,
                values={lang: descs[lang] for lang in LANGUAGES},
            )
        )
        if player_effects:
            # 修正名要在国家的修正列表里显示 —— 缺了它就是裸键（闸门 ② 会判红）。
            localization.append(
                Localization(
                    key=tier.modifier,
                    why=tier.player_why,
                    values={
                        lang: f"{labels[lang]}{DIFFICULTY_MODIFIER_SUFFIX[lang]}"
                        for lang in LANGUAGES
                    },
                )
            )
    return tuple(tiers)


def _check_difficulty(archives: Sequence[Archive]) -> Difficulty | None:
    """`[difficulty]` 是全仓一份的 **mod 级**表：2 份当场报错；**0 份返回 None**。

    0 份为什么不报错：三档是对外契约（`01a` J5），但"发布的那一份必须有"属于**闸门**
    的判据（`modguard.gate_determinism`），不该让每个最小夹具都背一张 mod 级契约表 ——
    这条检查第一次写进编译期时，仓库里 61 条与难度无关的用例当场红。
    """
    owners = [archive for archive in archives if archive.difficulty is not None]
    if not owners:
        # ⚠️ **0 份不在这里报错**（与 `[tempo]` 的政策不同，理由有实测依据）：
        # "发布的那一份必须有难度表"由闸门 ⑤ 看守（`modguard.gate_determinism`），
        # 因为编译期硬约束的实际效果是"每个最小夹具都要带一张 mod 级契约表" ——
        # 加这条检查时仓库里 61 条用例当场红，而它们测的都不是难度。
        # 写了两份仍然是数据源自相矛盾，编译期就报（下面那条）。
        raise _NoDifficultyError
    if len(owners) > 1:
        raise DataError(
            "这些数据源都声明了 [difficulty]："
            + "、".join(archive.source for archive in owners)
            + " —— 规则名与设置名是全局的，全仓只允许一份（改哪一份而不是两份都留）"
        )
    found = owners[0].difficulty
    assert found is not None  # 上面已经筛过
    return found


def _check_tempo(archives: Sequence[Archive]) -> None:
    """`[tempo]` 是全仓一份的 **mod 级**表：0 份或 2 份都当场报错（schema v1）。

    为什么 0 份也报错：`defines` 是全局的，"整份 mod 不带节奏段"是个**设计决定**
    （节奏覆盖是"喂进去的输入能被读到"的前提，见 `mod/data/ru_defeat.toml` 的
    `[tempo].why`），不能靠"少了一个文件"来隐式表达（P13：不许静默降级）。
    """
    owners = [archive for archive in archives if archive.tempo is not None]
    if not owners:
        raise DataError(
            "没有任何数据源声明 [tempo]：defines 是全局的，节奏杠杆全仓只允许一份 —— "
            "整份 mod 要不要节奏段必须显式写出来，不能靠少一个产物来表达"
        )
    if len(owners) > 1:
        raise DataError(
            "这些数据源都声明了 [tempo]："
            + "、".join(archive.source for archive in owners)
            + " —— defines 没有单国写法，全仓只允许一份（改哪一份而不是两份都留）"
        )


def _check_game_version(archives: Sequence[Archive]) -> None:
    """一份 mod 只有一个 `supported_game_version`：档案之间不一致就是数据源在骗人。"""
    versions = sorted({archive.game_version for archive in archives})
    if len(versions) > 1:
        raise DataError(
            "这些数据源的 game_version 不一致："
            + "、".join(versions)
            + " —— 元数据只有一份，钉住的引擎版本只能有一个（改数据源，不是改这里）"
        )


def _build_one(archive: Archive) -> Built:
    """单份档案**自己的**产物（不含 mod 级的 `.metadata/metadata.json`）。"""
    files: dict[str, str] = {
        archive.effect_file: effects_text(archive),
        archive.modifier_file: modifier_text(archive),
        archive.journal_file: journal_text(archive),
        archive.doc_file: doc_text(archive),
    }
    if archive.tempo is not None:
        files[archive.defines_file] = defines_text(archive)
    if archive.inputs is not None:
        files[archive.inputs_file] = inputs_text(archive)
    if archive.difficulty is not None:
        # 两个产物都按**声明它的那份档案**命名（照 `[tempo]` 的口径）。
        files[archive.difficulty.rule_file] = difficulty_rule_text(archive.difficulty)
        modifiers = difficulty_modifier_text(archive.difficulty)
        if modifiers:
            files[archive.difficulty.modifier_file] = modifiers
    for lang in sorted(LANGUAGES):
        files[archive.loc_file(lang)] = loc_text(archive, lang)
    for card in archive.cards:
        files[archive.card_file(card)] = card_text(archive, card)
    return Built(archive_ids=(archive.id,), files=files, numbers=archive.numbers)


def build(archive: Archive) -> Built:
    """把**一份**档案编译成 ``relpath → 文本``（相对产物根）。

    就是 ``build_all([archive])`` 的简写 —— 两条路径共用同一套组合规则，
    免得"单档案构建"与"多档案构建"悄悄分叉。
    """
    return build_all([archive])


def build_all(archives: Sequence[Archive]) -> Built:
    """把多份档案合成一次构建。

    三件事在这里一次做完（都是"单份数据源看不出、必须全仓看"的检查）：

    * 产物路径冲突 = 两份档案写了同一个文件 —— 当场报错：静默覆盖会让
      "哪份档案在起作用"变成无解的问题；
    * `[tempo]` 恰好一份、档案之间 `game_version` 一致（schema v1，见模块文档）；
    * mod 级元数据**最后**合成一份（它读的是全部档案）。
    """
    if not archives:
        raise DataError("一份档案都没有：产物不能凭空生成（数据源目录是空的？）")
    _check_tempo(archives)
    # 没有难度表不是编译错误：契约项在位由 `test_modgen_difficulty.py` 的
    # 「真实数据源」用例看守（见 `_check_difficulty` 的说明）。
    with suppress(_NoDifficultyError):
        _check_difficulty(archives)
    _check_game_version(archives)

    files: dict[str, str] = {}
    numbers: list[Number] = []
    ids: list[str] = []
    for archive in archives:
        built = _build_one(archive)
        clash = sorted(set(built.files) & set(files))
        if clash:
            raise DataError(
                f"档案 {archive.id} 与前面的档案写了同一个产物路径：{clash} —— "
                "产物路径由 `sitai_<档案 id>_*` 派生，改 id 而不是让它互相覆盖"
            )
        files.update(built.files)
        numbers.extend(built.numbers)
        ids.append(archive.id)
    files[METADATA_REL] = metadata_text(archives)
    return Built(archive_ids=tuple(ids), files=files, numbers=tuple(numbers))


def summary(built: Built) -> str:
    """给人看的构建摘要。"""
    lines = [
        f"档案：{'、'.join(built.archive_ids)}",
        f"产物 {len(built.files)} 个（游戏侧 {len(built.game_side)} 个）：",
    ]
    lines.extend(f"  {path}" for path in built.paths)
    numbers = len(built.numbers)
    lines.append(f"带依据的数字 {numbers} 个（`v3 modgen --why` 展开）")
    return "\n".join(lines)


# ── 写盘与核对 ──────────────────────────────────────────────
def _writes_bom(rel: str) -> bool:
    """这份产物要不要写 BOM。

    游戏侧（`.txt` / `.yml`）**要** —— 原版 3,026 个 `.txt` 里 3,002 个带 BOM，
    缺 BOM 的表现是"文件像没生效"。`.md`（给人看的）与 `.json`（启动器按 JSON 解析）
    **不要**。
    """
    return rel.endswith(GAME_SIDE_SUFFIXES)


def write(built: Built, root: Path | None = None) -> list[Path]:
    """把产物写进仓库里的产物根，并清掉**被取代的旧文件**。

    清理的判据：产物根下所有 `sitai_*` 文件里，不在本次构建结果中的那些。
    为什么必须清：数据源删掉一条（或改了档案 id）之后，旧文件会继续被游戏加载，
    表现是"改了数据源却没变化" —— 最容易被误信的一类失败。
    """
    base = root or PRODUCT_DIR
    written: list[Path] = []
    for rel, text in sorted(built.files.items()):
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8-sig" if _writes_bom(rel) else "utf-8"
        path.write_text(text, encoding=encoding, newline="\n")
        written.append(path)
    for stale in stale_files(built, base):
        stale.unlink()
        _prune_empty(stale.parent, base)
    return written


def _prune_empty(path: Path, base: Path) -> None:
    """删掉因清理而空掉的目录（只删我们自己产物根下的空壳）。"""
    while path != base and base in path.parents:
        if any(path.iterdir()):
            return
        path.rmdir()
        path = path.parent


def stale_files(built: Built, root: Path | None = None) -> list[Path]:
    """产物根下**该清掉**的旧文件：我们的文件里不在本次构建结果中的那些。"""
    base = root or PRODUCT_DIR
    if not base.is_dir():
        return []
    wanted = {base / rel for rel in built.files}
    return [
        path
        for path in sorted(base.rglob(f"{FILE_PREFIX}*"))
        if path.is_file() and path not in wanted
    ]


def check(built: Built, root: Path | None = None) -> list[str]:
    """盘上产物与生成结果不一致的地方（手改 / 过期 / 多余 / 缺 BOM）。

    返回人读的问题清单，空列表 = 干净。``v3 modgen --check`` 与闸门 ⑤ 都用它 ——
    「产物是不是生成出来的」这件事必须能被机械地回答。
    """
    base = root or PRODUCT_DIR
    problems: list[str] = []
    for rel, text in sorted(built.files.items()):
        path = base / rel
        if not path.is_file():
            problems.append(f"缺产物：{rel}（跑 `v3 modgen --write`）")
            continue
        raw = path.read_bytes()
        if _writes_bom(rel):
            if not raw.startswith(b"\xef\xbb\xbf"):
                problems.append(f"缺 UTF-8 BOM：{rel}")
                continue
            raw = raw[3:]
        if raw.decode("utf-8", errors="replace") != text:
            problems.append(f"与数据源不一致（被手改或数据源改过没重生成）：{rel}")
    problems.extend(
        f"多余产物（被取代的旧文件）：{path.relative_to(base).as_posix()}"
        for path in stale_files(built, base)
    )
    return problems


# ── why 报告 ────────────────────────────────────────────────
def why_report(archive: Archive) -> str:
    """每个数字 + 它的依据（markdown 表）。也是档案文档正文章节。"""
    rows = [
        "| 位置 | 数值 | 依据 |",
        "|---|---:|---|",
        *(f"| `{n.path}` | {num(n.value)} | {n.why} |" for n in archive.numbers),
    ]
    return "\n".join(rows)


def why_tables(archive: Archive) -> str:
    """没有数字的那些表（判据块、引用、说明）的依据清单。"""
    rows = [
        "| 位置 | 依据 |",
        "|---|---|",
        *(f"| `{path}` | {why} |" for path, why in archive.whys),
    ]
    return "\n".join(rows)


# ── 事实表与反解（闸门 ④ 的两端）────────────────────────────
def metadata_facts(archives: Sequence[Archive]) -> list[tuple[str, str]]:
    """mod 级元数据的事实表（路径与 :func:`readback` 读出来的三条一致）。"""
    payload = metadata_payload(archives)
    return sorted(
        (f"metadata.{key}", str(payload.get(key, "")))
        for key in ("id", "version", "supported_game_version")
    )


def facts(archive: Archive) -> list[tuple[str, str]]:
    """数据源 → 扁平事实表 ``(路径, 值)``。

    路径用点号串起结构（``modifier.<名>.<字段>``），值一律是字符串 —— 于是
    "数据源"与"从产物反解出来的东西"可以直接做集合比对（闸门 ④）。

    **单档案口径**：`metadata.*` 走 :func:`metadata_facts`（单档案时与旧的
    `sitai.<id>` 写法逐字节一致），`[tempo]` 只有声明了它的档案才有这几条。
    """
    out: list[tuple[str, str]] = [
        (f"effects.{archive.memory.effect}.set_variable.name", archive.memory.variable),
        (f"effects.{archive.memory.effect}.add_modifier.name", archive.pressure.name),
        (f"modifier.{archive.pressure.name}.icon", archive.pressure.icon),
        (f"journal_entry.{archive.journal_entry.name}.icon", archive.journal_entry.icon),
        (f"journal_entry.{archive.journal_entry.name}.group", archive.journal_entry.group),
        *metadata_facts([archive]),
    ]
    out.extend(
        (f"effects.{archive.memory.effect}.set_variable.{p.key}", num(p.amount))
        for p in archive.memory.params
    )
    out.extend(
        (f"effects.{archive.memory.effect}.add_modifier.{p.key}", num(p.amount))
        for p in archive.pressure.params
    )
    out.extend(
        (f"modifier.{archive.pressure.name}.{p.key}", num(p.amount))
        for p in archive.pressure.effects
    )
    out.extend(
        (f"journal_entry.{archive.journal_entry.name}.{p.key}", num(p.amount))
        for p in archive.journal_entry.fields
    )
    out.extend(
        (f"journal_entry.{archive.journal_entry.name}.{c.gate}.{c.key}", c.fact())
        for c in archive.journal_entry.conditions
    )
    # 递牌信号：`immediate` / `on_complete` 两个块。**只有声明了信号的档案**才有这几条
    # —— 缺省不生成空块，所以事实表里也不该凭空多出条目（闸门 ④ 是集合比对）。
    out.extend(
        (f"journal_entry.{archive.journal_entry.name}.immediate.set_strategy", p.arg)
        for p in archive.journal_entry.signals.set_strategy
    )
    out.extend(
        (f"journal_entry.{archive.journal_entry.name}.on_complete.set_strategy", p.arg)
        for p in archive.journal_entry.signals.clear_strategy
    )
    # ⚠️ 三行解释（P11）**不进事实表**：它们的键名由 JE 名 + 固定后缀派生
    # （`<je 名>_goal` 等），值则由 `localization.*` 那一组事实覆盖 ——
    # 再记一份就是同一个事实写两遍（P9）。它能被核对的部分（键存在 + 文案齐 + why 非空）
    # 由闸门 ② 与 ⑤ 分别负责。
    if archive.tempo is not None:
        out.extend(
            (f"defines.{archive.tempo.block}.{p.key}", num(p.amount)) for p in archive.tempo.keys
        )
    difficulty = archive.difficulty
    if difficulty is not None:
        out.append(
            (
                f"gamerule.{difficulty.key}.default",
                difficulty.tier(DIFFICULTY_DEFAULT).setting,
            )
        )
        out.extend(
            (f"gamerule.{difficulty.key}.setting.{tier.setting}.flag", tier.setting)
            for tier in difficulty.tiers
        )
        for tier in difficulty.tiers_with_player_effects():
            out.append((f"modifier.{tier.modifier}.icon", difficulty.icon))
            out.extend(
                (f"modifier.{tier.modifier}.{item.key}", num(item.amount))
                for item in tier.player_effects
            )
        # 冲击效果里那几个 `if` 分支（按出现顺序编号；顺序就是 `DIFFICULTY_TIERS` 的顺序）
        years = next((item for item in archive.pressure.params if item.key == "years"), None)
        for index, tier in enumerate(difficulty.tiers_with_player_effects()):
            prefix = f"effects.{archive.memory.effect}.if[{index}]"
            out.append((f"{prefix}.limit.is_ai", "no"))
            out.append((f"{prefix}.limit.has_game_rule", tier.setting))
            out.append((f"{prefix}.add_modifier.name", tier.modifier))
            if years is not None:
                out.append((f"{prefix}.add_modifier.years", num(years.amount)))
    if archive.inputs is not None:
        inputs = archive.inputs
        out.append((f"effects.{inputs.effect}.add_modifier.name", inputs.name))
        out.extend(
            (f"effects.{inputs.effect}.add_modifier.{p.key}", num(p.amount)) for p in inputs.params
        )
        out.append((f"modifier.{inputs.name}.icon", inputs.icon))
        out.extend((f"modifier.{inputs.name}.{p.key}", num(p.amount)) for p in inputs.effects)
    for card in archive.cards:
        out.append((f"card.{card.name}.slot", card.slot))
        out.append((f"card.{card.name}.weight", num(card.weight)))
        out.extend((f"card.{card.name}.possible.{c.key}", c.fact()) for c in card.possible)
        out.extend((f"card.{card.name}.{p.key}", num(p.amount)) for p in card.fields)
    for entry in archive.localization:
        out.extend((f"localization.{lang}.{entry.key}", entry.values[lang]) for lang in LANGUAGES)
    return sorted(out)


def _scalar(node: object) -> str:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Block):
        return f"{{{len(node)}项}}"
    return ""


def _top(parsed_path: str, text: str) -> list[Assignment]:
    """解析一份生成物并返回顶层赋值；解析出错就报错（闸门 ④ 会把它当红）。"""
    parsed = parse_text(text, parsed_path)
    if parsed.errors:
        raise DataError(f"{parsed_path} 解析失败：{parsed.errors}")
    return parsed.top_assignments


def _block_of(node: Assignment | None) -> Block | None:
    return node.value if node is not None and isinstance(node.value, Block) else None


def _facts_effects(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        if block is None:
            continue
        for label in ("set_variable", "add_modifier"):
            inner = _block_of(block.first(label))
            out.extend(
                (f"effects.{top.key}.{label}.{item.key}", _scalar(item.value))
                for item in (inner.assignments() if inner else [])
            )
        # 难度分支：`if = { limit = { … } add_modifier = { … } }`，按出现顺序编号。
        for index, item in enumerate(entry for entry in block.assignments() if entry.key == "if"):
            inner = _block_of(item)
            if inner is None:
                continue
            limit = _block_of(inner.first("limit"))
            out.extend(
                (f"effects.{top.key}.if[{index}].limit.{clause.key}", _scalar(clause.value))
                for clause in (limit.assignments() if limit else [])
            )
            add = _block_of(inner.first("add_modifier"))
            out.extend(
                (f"effects.{top.key}.if[{index}].add_modifier.{field.key}", _scalar(field.value))
                for field in (add.assignments() if add else [])
            )
    return out


def _facts_gamerules(rel: str, text: str) -> list[tuple[str, str]]:
    """`common/game_rules/*.txt` → `gamerule.<规则键>.*`。

    规则块里每个 `setting_* = { flag = … }` 记一条；`default = …` 记一条。
    """
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        if block is None:
            continue
        default = block.first("default")
        if default is not None:
            out.append((f"gamerule.{top.key}.default", _scalar(default.value)))
        for item in block.assignments():
            if not item.key.startswith("setting_"):
                continue
            inner = _block_of(item)
            flag = inner.first("flag") if inner is not None else None
            out.append(
                (f"gamerule.{top.key}.setting.{item.key}.flag", _scalar(flag.value) if flag else "")
            )
    return out


def _facts_modifier(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        out.extend(
            (f"modifier.{top.key}.{item.key}", _scalar(item.value))
            for item in (block.assignments() if block else [])
        )
    return out


def _facts_journal(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        if block is None:
            continue
        for item in block.assignments():
            inner = _block_of(item)
            if item.key in GATE_ORDER:
                out.extend(
                    (
                        f"journal_entry.{top.key}.{item.key}.{clause.key}",
                        f"{clause.op}{_scalar(clause.value)}",
                    )
                    for clause in (inner.assignments() if inner else [])
                )
            elif inner is not None:
                # `immediate` / `on_complete`：里面的每条赋值**再展开一层**。
                # 为什么要展开而不是记成"这个块有 1 项"：数据源是按**路径**写事实的
                # （`…immediate.set_strategy = ai_strategy_progressive_agenda`），
                # 闸门 ④ 是两份事实表的集合比对 —— 粒度不一致就会既"缺"又"多"，
                # 而那两行报错看起来像真丢了东西。实测：不展开时 4 条（2 缺 2 多）。
                out.extend(
                    (f"journal_entry.{top.key}.{item.key}.{sub.key}", _scalar(sub.value))
                    for sub in inner.assignments()
                )
            else:
                out.append((f"journal_entry.{top.key}.{item.key}", _scalar(item.value)))
    return out


def _facts_defines(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        out.extend(
            (f"defines.{top.key}.{item.key}", _scalar(item.value))
            for item in (block.assignments() if block else [])
        )
    return out


def _facts_card(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        if block is None:
            continue
        weight = _block_of(block.first("weight"))
        value = weight.first("value") if weight is not None else None
        out.append((f"card.{top.key}.weight", _scalar(value.value) if value else ""))
        possible = _block_of(block.first("possible"))
        out.extend(
            (f"card.{top.key}.possible.{clause.key}", f"{clause.op}{_scalar(clause.value)}")
            for clause in (possible.assignments() if possible else [])
        )
        out.extend(
            (f"card.{top.key}.{item.key}", _scalar(item.value))
            for item in block.assignments()
            if item.key not in {"weight", "possible"}
        )
    return out


def _facts_loc(rel: str, text: str) -> list[tuple[str, str]]:
    lang = rel.split("/")[1]
    return [(f"localization.{lang}.{key}", value) for key, value in parse_loc_text(text).items()]


#: 产物目录 → 反解器。键是 ``(产物根下的第一层, 第二层)`` ——
#: 与 F7 的「平铺」同构：我们的文件只出现在这些位置。
_FACT_READERS: dict[tuple[str, str], Callable[[str, str], list[tuple[str, str]]]] = {
    ("common", "scripted_effects"): _facts_effects,
    ("common", "static_modifiers"): _facts_modifier,
    ("common", "journal_entries"): _facts_journal,
    ("common", "defines"): _facts_defines,
    ("common", "game_rules"): _facts_gamerules,
    ("common", "ai_strategies"): _facts_card,
    **{("localization", lang): _facts_loc for lang in LANGUAGES},
}


def readback(files: Mapping[str, str]) -> list[tuple[str, str]]:
    """产物 → 同一套扁平事实表（闸门 ④ 的另一端）。

    刻意**独立于生成器**：这里按 PDX 语法把文件解析回来，而不是回放生成时的字符串。
    两边共用同一套 render 函数就成了自说自话 —— 那样"往返净度"只能证明
    "我按我写的写了一遍"。
    """
    out: list[tuple[str, str]] = []
    for rel in sorted(files):
        text = files[rel]
        if rel == METADATA_REL:
            payload = json.loads(text)
            out.extend(
                (f"metadata.{key}", str(payload.get(key, "")))
                for key in ("id", "version", "supported_game_version")
            )
            continue
        parts = rel.split("/")
        reader = _FACT_READERS.get((parts[0], parts[1])) if len(parts) == 3 else None
        if reader is not None:
            out.extend(reader(rel, text))
    return sorted(out)


#: 本地化条目行：``KEY:版本 "值"``。**与 :mod:`pdx.localization` 的口径一致**
#: （键是第一个 ``:`` 之前的部分、版本号可缺省、值可能没有引号），
#: 这里自己写一遍是因为反解要比对**值**，而那边只返回键。
_LOC_ENTRY = re.compile(r"^\s*([^\s:#][^:]*?)\s*:\s*(\d+)?\s*(.*)$")


def parse_loc_text(text: str) -> dict[str, str]:
    """把一份 `.yml` 解析成 ``键 → 值``（本地化不是花括号语法，单独处理）。"""
    pattern = _LOC_ENTRY
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        key, _version, value = match.group(1), match.group(2), match.group(3).strip()
        if key.startswith("l_"):
            continue  # 语言声明行，不是条目
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        out[key] = value
    return out


__all__ = [
    "DATA_DIR",
    "DATA_SUFFIX",
    "FILE_PREFIX",
    "GATE_ORDER",
    "GEN_HEADER",
    "LANGUAGES",
    "MOD_VERSION",
    "NAMESPACE_PREFIX",
    "PRODUCT_DIR",
    "SCHEMA_VERSION",
    "Archive",
    "Built",
    "Card",
    "Clause",
    "Condition",
    "DataError",
    "Inputs",
    "JournalEntry",
    "Localization",
    "Memory",
    "Number",
    "Param",
    "Pressure",
    "Reference",
    "Tempo",
    "archive_files",
    "audit",
    "build",
    "build_all",
    "card_text",
    "check",
    "data_files",
    "defines_text",
    "doc_text",
    "effects_text",
    "facts",
    "inputs_text",
    "journal_text",
    "load_all",
    "load_data",
    "loc_text",
    "metadata_facts",
    "metadata_payload",
    "metadata_text",
    "modifier_text",
    "num",
    "parse_loc_text",
    "parse_source",
    "read_source",
    "readback",
    "stale_files",
    "summary",
    "why_report",
    "why_tables",
    "write",
]
