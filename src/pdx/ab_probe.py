"""A/B 实验探针的生成器（阶段 3）：**一局之内按日期自动换臂**。

**实验要回答什么**（H2，见 `docs/design/exec/阶段3-最小闭环.md`）：
真实的战败冲击能不能让同一个国家在**行为层**产生可测差分 —— 不只是策略卡换个名字。

**设计：一局跑完整条阶梯**（为什么不是"两局各点一次决议"）
--------------------------------------------------------
实测踩过的两件事决定了这个形状：

1. **一局只能有一个角色**：角色由"点哪个决议"决定时，A/B 要开两局；两局之间的世界
   已经漂了（不同的随机数、不同的开局抽牌），差分就掺进了"两局不同"这个噪声。
2. **必须一局之内分两处施加**：冲击只压了贵族与合法性，而原版改革派牌的权重读的是
   工业家/知识界（`ai_strategy_progressive_agenda`，03_political_strategies.txt:528-544）
   —— 第二处理段（改革侧输入）要能在**同一个世界、同一个剧本**里追加。

于是探针自带一个**臂阶梯**：点一次决议武装，之后按**月度脉冲计数的月份**自动换臂：

======  ===========  ==========================================================
臂      起止月       进入这一臂时做什么
======  ===========  ==========================================================
`A`     第 1–12 月   什么都不做（对照组：窗口与法律应当一动不动）
`B`     第 13–36 月  调用legacy 档案 mod 的 `sitai_ru_defeat_shock`（冲击）
`B2`    第 37 月起   再调用 `sitai_ru_reform_input`（改革侧输入）
======  ===========  ==========================================================

**幂等**是这条阶梯的硬要求：`stage` 变量单调递增，每个效果**只施加一次**
（不靠"有没有修正"这类会被其它系统碰到的判据），因此重复跑月度脉冲、
中途读档、甚至再点一次决议重置，都不会把同一处输入叠两遍。

**仍然保持**（与前一版一致的口径，改动只落在"怎么换臂"）：

* **0 张牌**（F5）：本探针不新增任何 `ai_strategy_*`，只读不写；
* **只记俄罗斯**：G2 问的是单国差分，日志不给全世界刷行；
* **行为层与策略层分开记**：法律与 JE 是行为层（看得见的东西），槽位是策略层；
  阶段 3 的失败长相写死了「只有策略层动 = H2 不成立」；
* **五档合法性诊断**（`LEG;b55/b60/b70/b75/b80`）：没有"打印一个数字"的已证可用写法
  （阶段 2 的教训：`[This.GetTag]` 不是合法 loc 命令），所以用夹逼档位；
* **`PLAYER` 诊断行**：玩家必须是**旁观者** —— 玩家扮演俄罗斯时它不是 AI，
  问不出"AI 自己改革"（口径在阶段 3 中途反过来，见 `pdx.ab.health` 的第②条）。

**scripted_tests 套件也在这里生成**：`tools/scripted_tests/sitai_ab.txt` 把判据交给
**引擎自己每天判**（成功/失败/跳过，见游戏目录里的 `scripted_tests.md`），另有四个
原版套件的收敛覆盖（否则它们会跑到 1879 年，把整套自动化拖住）。实测：游戏**会**读
mod 提供的套件（"只读安装目录"那条假设已被证伪，见 `exec/阶段3-归档清点.md` §三）。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import ai_surface, config, experiments, h1_probe
from pdx.h1 import SLOT_SHORT, SLOTS
from pdx.textio import deploy_tree

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: 探针 mod 目录名。
PROBE_MOD = "zz_probe_ab"

#: legacy 档案 mod 安装到用户 mod 目录时的目录名 —— **只作兜底**（正常路径从档案 id 拼，见 :func:`deploy`）。
MOD_DIR_NAME = "sitai_ru_defeat"

#: 探针源目录（仓库内，可审阅）。
PROBE_DIR = config.REPO / "tools" / "probe" / PROBE_MOD

#: legacy 档案 mod 的冲击效果（由 `mod/legacy/common/scripted_effects/sitai_ru_defeat_effects.txt` 生成）。
SHOCK_EFFECT = "sitai_ru_defeat_shock"

#: legacy 档案 mod 的**改革侧输入**效果与修正（同源文件；闸门 ② 保证它们真实存在）。
INPUT_EFFECT = "sitai_ru_reform_input"
INPUT_MODIFIER = "sitai_ru_reform_inputs"

#: 主角国家 —— **只作兜底与文档用途**，真正的来源见 :func:`load_target`。
SUBJECT = "RUS"


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    """探针要盯的那份档案（从 `mod/data/*.toml` **读出来**，不手抄）。

    为什么要这样（P9 单一数据源 + P3 不手写生成物）：探针里原来硬编码了
    `SUBJECT = "RUS"` / `je_sitai_ru_reform_window` / `sitai_ru_defeat_shock` ——
    加**第二份档案**（阶段 5 要做的）时，这些名字得在人脑里同步一遍，
    而"手写的东西迟早会漂"是这个仓库反复踩过的坑（G-EXIT-1 的判据就是
    "加一份数据源 ⇒ Python 侧 0 行改动"）。
    ⇒ 现在从**数据源**读：档案 id、国家、JE 名、效果名全由 `modgen` 编译出来。
    """

    dir_name: str
    subject: str
    journal_entry: str
    shock_effect: str
    shock_variable: str
    input_effect: str
    input_modifier: str
    archive_id: str
    #: 本档案的**压力修正名**（`[pressure].name`，由 `modgen` 编译出来）。
    #:
    #: 为什么探针需要它（t18 判别性实验，2026-09-25）：t18 的那张牌的门是
    #: `possible = { has_modifier = <压力修正> }`，而**月读数里从来没有一行直读它**
    #: —— 「门到底开没开」只能从变量 `has_variable` 旁证。B 臂 0/13 之后这一点
    #: 直接决定了「不可归因」（见 `docs/design/exec/阶段5-新增牌-结果.md` §5）。
    #: 门名从**数据源**读（不手抄）：手抄的后果是改名之后探针**静默读一个不存在的修正**、
    #: 永远报 `no`，而这与"门真的没开"在日志里长得一模一样。
    #: 空字符串 = 这份档案没有压力修正 ⇒ 不写 `GATE` 行（不能写一行永远为 `no` 的读数）。
    pressure_modifier: str = ""
    #: "行为层②"用哪条法判"改革真的发生了"。**空 = 该档案没查实**（B80）。
    #:
    #: 为什么允许为空：套件原来写死 `NOT = { has_law = law_type:law_serfdom }`，
    #: 而奥斯曼与埃及的历史文件里**没有**土地法那一组（实测）⇒ 对它们这条判据
    #: **立刻为真**，报出一个假的"法律换了"。空的时候干脆不判。
    reform_law: str = ""


def load_target(archive_id: str | None = None) -> ProbeTarget | None:
    """从仓库的数据源读出探针要盯的档案；**读不到就给 ``None``**（不编一个假的）。

    读不到时调用方必须报错（P13）：用一个猜出来的国家名生成探针，
    会让"这个探针在盯谁"变成一件看不出来的错事。

    ``archive_id`` 是**显式选档案**（阶段 5 起 `mod/data/` 里有多份档案，
    探针一次只盯一份）。不给就按数据源的加载顺序取第一份 —— 顺序由
    `modgen.load_all()` 决定（按文件名排序），**探针文本里会写明它盯的是谁**，
    所以"默认是哪一份"是可复核的，不用记在脑子里。
    """
    from . import modgen  # noqa: PLC0415  -- 避免 import 期把 modgen 的依赖链拉进来

    try:
        archives = modgen.load_all()
    except (OSError, modgen.DataError):  # pragma: no cover - 数据源坏了时另有用例守着
        return None
    if not archives:
        return None
    if archive_id is None:
        first = archives[0]
    else:
        picked = [archive for archive in archives if archive.id == archive_id]
        if not picked:
            # 点名了却没有 ⇒ **报错**，不要"回落到第一份"（那会让人以为探针盯的是 A，
            # 实际盯的是 B —— 这正是这类工具最容易出的静默错误）。
            raise KeyError(
                f"数据源里没有档案 {archive_id!r}；现有：{'、'.join(a.id for a in archives)}"
            )
        first = picked[0]
    return ProbeTarget(
        dir_name="-".join(archive.id for archive in archives),
        subject=first.country,
        journal_entry=first.journal_entry.name,
        shock_effect=first.memory.effect,
        shock_variable=first.memory.variable,
        input_effect=first.inputs.effect if first.inputs is not None else "",
        input_modifier=first.inputs.name if first.inputs is not None else "",
        archive_id=first.id,
        reform_law=first.probe.reform_law if first.probe is not None else "",
        pressure_modifier=first.pressure.name if first.pressure is not None else "",
    )


#: 臂阶梯的两个计数器：`stage` 单调递增（幂等靠它）、`month` 数月度脉冲。
MONTH_VAR = "sitai_probe_ab_month"
STAGE_VAR = "sitai_probe_ab_stage"


@dataclass(frozen=True, slots=True)
class ArmStep:
    """阶梯上的一臂：从第几个月起、进入时施加什么。"""

    role: str
    at_month: int
    effect: str | None
    note: str


def ladder_for(target: ProbeTarget) -> tuple[ArmStep, ...]:
    """臂阶梯（**唯一的定义处**）：从 ``target`` 派生出要调的效果名。

    为什么必须按 target 派生（2026-09-23 修）：阶段 5 起 `mod/data/` 里有多份档案，
    而这里原来读的是模块级的 `SHOCK_EFFECT` / `INPUT_EFFECT`（= 俄国那两个效果名）。
    于是"探针盯奥地利、却去调俄国的效果"—— 生成出来的文本**看不出来错**，
    跑起来只会得到"什么都没发生"。角色名与起始月与档案无关（A/B/B2 恒为 1/13/37），
    所以 `ROLES` / `ARM_START` 仍然是模块级常量。
    """
    return (
        ArmStep("A", 1, None, "对照组：什么都不做"),
        ArmStep(
            "B", 13, target.shock_effect, f"处理①：{target.archive_id} 的冲击（变量 + 压力修正）"
        ),
        ArmStep(
            "B2",
            37,
            target.input_effect or None,
            "处理②：追加改革侧输入（工业家/知识界政治力量）",
        ),
    )


#: 默认阶梯（= 默认 target 那一份）。**生成文本里用的是 :func:`ladder_for`**；
#: 这个常量留给"只看角色与月份"的下游（分析器的 `ROLES` / `ARM_START` 由它派生）。
LADDER: tuple[ArmStep, ...] = (
    ArmStep("A", 1, None, "对照组：什么都不做"),
    ArmStep("B", 13, SHOCK_EFFECT, "处理①：冲击（变量 + 压力修正）"),
    ArmStep(
        "B2",
        37,
        INPUT_EFFECT,
        "处理②：追加改革侧输入（工业家/知识界政治力量）",
    ),
)

#: 角色（= 臂名）：A 对照、B 冲击、B2 追加改革侧输入。与 `pdx.ab` **同源**（P9）。
ROLES = tuple(step.role for step in LADDER)

#: 角色 → 起始月（供分析器/文档解释"第几个月开始算这一臂"）。
ARM_START: dict[str, int] = {step.role: step.at_month for step in LADDER}

#: 每个月的自报里"冲击在不在"用的判据（legacy 档案 mod 写的变量）。
#: 冲击记忆变量 —— **只作兜底与文档用途**，真正的来源是 :func:`load_target`。
SHOCK_VAR = "sitai_ru_defeat_memory"

#: 每个月要记的法律（改革相关；都是原版存在的 law_type）。
LAWS = (
    # 土地法那一组（**各国不一样**：俄国/大清/波斯是农奴制，奥地利是庄园制，
    # 新大陆是 latifundias —— 少列一条，某个国家的土地法就读不到）
    "law_serfdom",
    "law_manorialism",
    "law_latifundias",
    "law_expanded_latifundias",
    "law_tenant_farmers",
    "law_commercialized_agriculture",
    # 权力分配 / 言论 / 兵役 / 经济（改革方向上的常见落点）
    "law_autocracy",
    "law_wealth_voting",
    "law_censorship",
    "law_peasant_levies",
    "law_traditionalism",
)

#: 每个月要记的**政治策略牌**：候选集**从原版现读**（`common/ai_strategies/` 里
#: `type = political` 的全部牌），不再手写。
#:
#: ⚠️ 这里原先是一份手写的三张牌清单（2026-09-23 修，B87）：
#: `progressive_agenda` / `conservative_agenda` / `reactionary_agenda` —— **少了
#: `ai_strategy_egalitarian_agenda`**，而那张牌**就在我们自己递牌的白名单里**
#: （`modgen.SET_STRATEGY_WHITELIST`）。后果不是"少一格读数"而是**静默失真**：
#: 国家挂着那张牌时，`if / else_if` 三条全不匹配、链尾又没有兜底 ⇒ **这个月一行都不记**，
#: 而"没记"与"没有牌"在这套日志里长得一模一样；分析器按档案声明的
#: `[probe].reform_card` 去问"那张牌出现过吗"，对 egalitarian 这份档案**必然为假**。
#: 同一类失真在 `h1_probe` 的注释里已经写过一次（手写清单随版本漂移，
#: 表现是"某个槽位永远落进兜底桶"）。⇒ 候选集现读、并补 `default` 与 `none` 两条兜底。
#:
#: 与 `_slot_chains` 的关系：那条链记的是"三槽各自落在哪张牌"，本条记的是
#: "政治槽这张牌是哪一张"（`STRATEGY;<完整牌名>`，分析器的行为层直接读数）。
POLITICAL_SLOT = "political"


def strategy_candidates(vanilla: list[ai_surface.Card]) -> list[str]:
    """政治槽的候选牌名（**原版现读**，升序去重）。

    单独一个函数是为了让测试能直接钉住它 —— 这份清单曾经漏掉一张牌，
    而漏掉的表现是日志里**什么都没有**，测试不主动问就永远发现不了。
    """
    return h1_probe.vanilla_chain_cards(vanilla, POLITICAL_SLOT)


#: 本仓 mod 的**产物根**（`common/ai_strategies/*.txt` 在这里）。
MOD_ROOT = config.REPO / "mod" / "legacy"

#: 我们自己的牌在自报里用的 kind。**只能是大写字母**：`pdx.ab` 的行正则是
#: `ZZPROBE AB;(?P<kind>[A-Z]+);(?P<rest>.+?)$`（`ab.py:114`）——
#: 所以牌名不能放进 kind，只能放进**取值位**（一个国家同月只挂一张政治牌 ⇒ 单值）。
CARD_KIND = "CARD"


def own_cards(root: Path | None = None) -> list[str]:
    """本仓 mod 的**政治槽**牌名（从盘上产物现读；升序去重；没有牌就是空列表）。

    为什么要有它（B87 的教训，两个方向都是**静默失真**）：
    手写清单会随档案增减漂移 —— 多写一张不存在的牌名，那一格永远是"读不到"；
    少写一张真牌，它挂着的时候链会落进兜底桶，看上去像"没有牌"。

    为什么读**产物**而不是 `mod/data/*.toml`：产物由 `v3 modgen` 落盘、闸门 ⑤ 保证
    与数据源逐字节一致（P3/P9），而这里只要名字；也免得把整个生成器拉进探针的依赖里
    （t16 正在改数据源时，探针生成不该因此报错）。
    """
    base = root or MOD_ROOT
    return sorted(
        {card.name for card in ai_surface.read_cards(base) if card.slot == POLITICAL_SLOT}
    )


def own_card_chain(ours: list[str], *, tab: str = "\t") -> str:
    """我们自己的牌**逐月"在/不在"**读数（`CARD;<牌名短写|none>;<国名>`）。

    形状照 `state_line`（同一条道理：**两个分支都要写**）—— 链首插入
    （见 :func:`on_actions_text`）只能"命中才写"，而这条链每月都写一行，
    且**独立于那条链的语义**：两条读数一旦不一致，就说明链被挪动过
    （`test_ab_probe.py` 的顺序用例之外的第二道防线）。

    ``ours`` 为空时只写 `none` 一行：**不能**只写 `else = { … }` ——
    没有配对的 `if`，那是一个引擎会报错的悬空 else。
    """
    if not ours:
        return (
            f'{tab * 3}debug_log = "ZZPROBE AB;{CARD_KIND};none;'
            f'[THIS.GetCountry.GetNameNoFormatting]"'
        )
    lines: list[str] = []
    for index, name in enumerate(ours):
        keyword = "if" if index == 0 else "else_if"
        short = name.removeprefix("ai_strategy_")
        lines.append(
            f"{tab * 3}{keyword} = {{\n"
            f"{tab * 4}limit = {{ has_strategy = {name} }}\n"
            f'{tab * 4}debug_log = "ZZPROBE AB;{CARD_KIND};{short};'
            f'[THIS.GetCountry.GetNameNoFormatting]"\n'
            f"{tab * 3}}}"
        )
    lines.append(
        f"{tab * 3}else = {{\n"
        f'{tab * 4}debug_log = "ZZPROBE AB;{CARD_KIND};none;'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"{tab * 3}}}"
    )
    return "\n".join(lines)


#: 难度三档的**设置名**（口径 `docs/design/exec/阶段6-国家身份开局-取证口径.md` §3.3）。
#: `has_game_rule` 读的就是**设置名**（不是规则名 `sitai_difficulty`）—— 原版同款用法见
#: `03_political_strategies.txt` 里 7 处读 `has_game_rule` 的地方，本 mod 的效果侧
#: （`sitai_ru_defeat_effects.txt`）那两条 `if = { limit = { has_game_rule = … } }` 也是它。
#: ⚠️ 这一族是**实机判据**：harsh 局要出现 `RULE;<设置名>_harsh;yes` 且**另两档各有一行 `no`**。
#: 🔧 2026-09-25 **把族名写进来**（原来这句有歧义，害得执行者把"另两档的 no"归给了第一族，
#: 于是 L13 的期望模型写错、自检才撞出来）：那两行 `no` **不是**这里写的，而是**第二族**
#: （逐档 `if/else`，kind = `RULEHISTORY`/`RULEUNIFORM`/`RULEHARSH`）写的。两族分工：
#: * **第一族**（下面这个互斥链 `if / else_if / else_if / else`，kind = `RULE`）——
#:   **只写命中的那一档**（`RULE;<设置名>;yes;<国名>`）；一档都没命中才写 `RULE;none;yes`。
#:   ⇒ 另两档**根本没有 `RULE` 行**，别去那里找它们的 `no`。
#: * **第二族**（:func:`difficulty_rule_lines` 的后半段）—— 每档一条 `yes`/`no`，
#:   "另两档是 no"这条**承重组合**靠它。理由是 `if` 命中即停 ⇒ 只靠第一族时
#:   "没命中"与"没记"分不开（B87 同族）。
#: 🔧 2026-09-25 **字面量同步（t88 之后）**：这里原来写的是 `setting_sitai_difficulty_*`，
#: 而 t88 把设置块的 **flag 名去掉了 `setting_` 前缀**（引擎按 `setting_<flag>` 查本地化 ⇒
#: 带前缀会查成 `setting_setting_…`、值框显示原始键 —— 那正是 t88 修的玩家可见缺陷）。
#: ⇒ `has_game_rule` 读的是**设置名/flag 名**，现在必须是**不带前缀**的 `sitai_difficulty_*`。
#: 不改的后果**不是报错而是静默判错**：三个 `if` 全部不命中 ⇒ 走 :func:`difficulty_rule_lines`
#: 的 `else` 兜底写下 `RULE;none;yes`，看起来"有读数"，实际什么都没证。
DIFFICULTY_SETTINGS: tuple[str, ...] = (
    "sitai_difficulty_history_friendly",
    "sitai_difficulty_uniform",
    "sitai_difficulty_harsh",
)

#: 三档的短名（按 :data:`DIFFICULTY_SETTINGS` 的顺序）与它们在自报里用的 kind。
#: kind 只能是 `[A-Z]+`（`ab.py:114`）—— 所以 `RULEHISTORY` / `RULEUNIFORM` / `RULEHARSH`。
RULE_SHORTS: tuple[str, ...] = ("history_friendly", "uniform", "harsh")

#: 短名 → kind（见 :func:`difficulty_rule_lines` 里"为什么另两档不能也叫 RULE"）。
RULE_KINDS: dict[str, str] = {
    "history_friendly": "RULEHISTORY",
    "uniform": "RULEUNIFORM",
    "harsh": "RULEHARSH",
}


def difficulty_rule_lines(*, tab: str = "\t") -> str:
    """难度档位的逐月读数 —— 两族行，各有各的用途（口径 §3.3 第 1 条）。

    1. **互斥链**（`if / else_if / else_if / else`，kind = `RULE`）：回答"这一局挂在
       **哪一档**"，命中写成 `RULE;sitai_difficulty_<档>;yes;<国名>`；
       一档都没命中时写 `RULE;none;yes` —— 于是"规则没进这一局 / 设置名写错"也是
       **写出来**的一行，不是缺席。
    2. **三档各自的 if/else**（kind = `RULEHISTORY` / `RULEUNIFORM` / `RULEHARSH`，
       取值就是 `yes` / `no`）：保证**另两档也各留一行 `no`**。承重判据要的是
       「`…_harsh;yes` **且**另两档 `no`」这个**组合**；只发互斥链时，另两档根本不出现在
       日志里，而"没记"与"没有"分不开（B87 那一族的静默失真）。

    ⚠️ 为什么另两档不能也叫 `RULE`：`pdx.ab` / `h1` 的行正则要求 kind 是 `[A-Z]+`
    （`ab.py:114`），而且**同一 (时刻, 国家) 下每个 kind 只留一条**（`rows[key][kind] = parts[0]`）
    ⇒ 三行同 kind 会互相覆盖，只剩最后一行。所以"哪一档"编进 kind，取值只放 yes/no。
    """
    branches = [
        f"{tab * 3}{'if' if index == 0 else 'else_if'} = {{\n"
        f"{tab * 4}limit = {{ has_game_rule = {setting} }}\n"
        f'{tab * 4}debug_log = "ZZPROBE AB;RULE;{setting};yes;'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"{tab * 3}}}"
        for index, setting in enumerate(DIFFICULTY_SETTINGS)
    ]
    branches.append(
        f"{tab * 3}else = {{\n"
        f'{tab * 4}debug_log = "ZZPROBE AB;RULE;none;yes;'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"{tab * 3}}}"
    )
    pairs = "\n".join(
        f"{tab * 3}if = {{\n"
        f"{tab * 4}limit = {{ has_game_rule = {setting} }}\n"
        f'{tab * 4}debug_log = "ZZPROBE AB;{RULE_KINDS[short]};yes;'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"{tab * 3}}}\n"
        f"{tab * 3}else = {{\n"
        f'{tab * 4}debug_log = "ZZPROBE AB;{RULE_KINDS[short]};no;'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"{tab * 3}}}"
        for short, setting in zip(RULE_SHORTS, DIFFICULTY_SETTINGS, strict=True)
    )
    return "\n".join(["\n".join(branches), "", pairs])


#: legacy 档案 mod 侧难度设置名的**唯一真相**在**产物**里：`mod/legacy/common/game_rules/*_difficulty.txt`。
#: 为什么读产物而不是 `mod/data/*.toml`：与 :func:`own_cards` 同一条道理 —— 这里只要设置名，
#: 免得把整个生成器拉进探针的依赖里；产物由 `v3 modgen` 落盘、闸门 ⑤ 保证与数据源逐字节一致。
DIFFICULTY_RULE_GLOB = "common/game_rules/*_difficulty.txt"

#: 产物里设置块内的 `flag = <设置名>` 那一行（块名与 flag 同串：`modgen.DifficultyTier.name`）。
_FLAG_LINE = re.compile(r"flag\s*=\s*(\S+)")


def mod_difficulty_settings(root: Path | None = None) -> tuple[str, ...]:
    """从**产物**读三档的**设置名**（`flag` 的值，按文件顺序去重；读不到就是空元组）。

    设置名 = 引擎眼里的规则设置名 = `has_game_rule` 的取值（口径 §3.3 第 1 条）。
    """
    base = root or MOD_ROOT
    names: list[str] = []
    for path in sorted((base / "common" / "game_rules").glob("*_difficulty.txt")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for line in text.splitlines():
            found = _FLAG_LINE.fullmatch(line.strip())
            if found is not None and found.group(1) not in names:
                names.append(found.group(1))
    return tuple(names)


@dataclass(frozen=True, slots=True)
class DifficultyCheck:
    """**探针写死的三档设置名**（:data:`DIFFICULTY_SETTINGS`）与**legacy 档案 mod 产物**的一致性读数。

    为什么要有它（t90 那族的静默失真）：那份字面量是写死的，而
    `tests/test_ab_probe.py` 里钉它的用例**以它自己为参照** —— 数据源改名而这里没跟时
    没有任何用例会红，实机只是照旧每月写一行 `RULE;none;yes`：看起来「有读数」，实际什么都
    没证（B87「没记与没得分不开」、B85「没看到被当成没有」同族）。

    ⚠️ **两种失败不是一回事**，文案与用例都分开（2026-09-29 队长口径）：

    * :attr:`mod` 为空 ⇒ **「一行都没有」**：产物侧压根读不到设置名 —— 要么产物没生成
      （跑 `v3 modgen --write`），要么这份 mod 就没有难度表。这时「没读到」不许写成「对不上」。
    * :attr:`mod` 非空而 :attr:`hits` 为空 ⇒ **「命中 0 条」**：两侧都有串、一条都对不上
      ⇒ 引擎里三个 `if has_game_rule` 全不命中、走 `else` 兜底写 `RULE;none;yes`。
    """

    probe: tuple[str, ...]
    mod: tuple[str, ...]

    @property
    def hits(self) -> tuple[str, ...]:
        """两侧**同串**的设置名（真正的命中数）。"""
        known = set(self.mod)
        return tuple(name for name in self.probe if name in known)

    @property
    def missing(self) -> tuple[str, ...]:
        """探针写了、产物里没有 ⇒ 这一条 `has_game_rule` 永远不会命中。"""
        known = set(self.mod)
        return tuple(name for name in self.probe if name not in known)

    @property
    def extra(self) -> tuple[str, ...]:
        """产物里有、探针没写 ⇒ 这一档探针读不到。"""
        known = set(self.probe)
        return tuple(name for name in self.mod if name not in known)

    @property
    def ok(self) -> bool:
        return bool(self.mod) and not self.missing and not self.extra

    def sides(self) -> str:
        """两侧现读的串 —— 报错文案里必须点名是哪一侧、具体是什么（不读代码就能改）。"""
        probe = "、".join(self.probe) or "（空）"
        found = "、".join(self.mod) or "（空）"
        return f"探针字面量（ab_probe.DIFFICULTY_SETTINGS）：{probe}；产物 `flag`：{found}"

    def text(self) -> str:
        """把不一致说成一句能照做的话 —— **「一行都没有」与「命中 0 条」各自成句**。"""
        where = f"{MOD_ROOT.name}/{DIFFICULTY_RULE_GLOB}"
        if not self.mod:
            return (
                f"一行都没有：`{where}` 里读不到任何设置名（`flag = …`）。"
                "这不是名字写错（那一支是两侧都有串、一条都对不上）—— 是产物侧压根没有难度表："
                "先跑 `v3 modgen --write`；产物照样没有的话，就是这份 mod 没有难度表，"
                "别拿这份探针判难度。"
            )
        if not self.hits:
            return (
                f"命中 0 条：{self.sides()} —— 一条都对不上 ⇒ 探针里三个 "
                "`if has_game_rule = …` 全不命中、走 `else` 兜底每月只写一行 "
                "`RULE;none;yes`：看起来「有读数」，实际什么都没证（t90 那族静默失真）。"
                "同步 `ab_probe.DIFFICULTY_SETTINGS`，或把数据源里的档位名改回来。"
            )
        parts: list[str] = []
        if self.missing:
            parts.append(f"探针有而产物没有：{'、'.join(self.missing)}")
        if self.extra:
            parts.append(f"产物有而探针没写：{'、'.join(self.extra)}")
        return (
            f"难度设置名对不上：{self.sides()} —— {'；'.join(parts)}"
            " ⇒ 对不上的那几档永远读不到（静默失真）。"
        )


def difficulty_check(root: Path | None = None) -> DifficultyCheck:
    """两侧现读一次返回读数（**不抛**：怎么出声由调用方定，生成期走 :func:`require_difficulty_match`）。"""
    return DifficultyCheck(probe=DIFFICULTY_SETTINGS, mod=mod_difficulty_settings(root))


def require_difficulty_match(root: Path | None = None) -> DifficultyCheck:
    """对不上就报错 —— P13 同族：读不到就报错，不生成一份注定什么都证不了的探针。"""
    check = difficulty_check(root)
    if not check.ok:
        raise RuntimeError(check.text())
    return check


#: 自励阶梯：**不点决议**，由月度脉冲按 `is_ai` 自动武装 —— 观察者局没有玩家国家，
#: 决议点不了（阶段 3 的结构性阻断，见 `阶段3-结果.md` §六）。
#:
#: `(月, 说明, 要调的效果名)`。月份与 `LADDER` 的臂起点**对齐**：第 13 月施加冲击（B 臂）、
#: 第 37 月追加改革侧输入（B2 臂）。
#:
#: ⚠️ 这里**刻意不递牌**：递牌是**legacy 档案 mod 的 JE 自己的事**（`[journal_entry.signals]`，
#: 窗口一开就递）。探针在这里再递一次就把"牌是不是闸门"与"窗口机制对不对"两个变量
#: 搅在一起了 —— 一次只动一个变量。
SELFARM: tuple[tuple[int, str, str], ...] = (
    (13, "施加战败冲击", SHOCK_EFFECT),
    (37, "追加改革侧输入", INPUT_EFFECT),
)

#: 自励进度计数器（单调递增 ⇒ 每一格只施加一次）。
SELFARM_VAR = "sitai_probe_ab_selfarm"

#: 决议武装过的标记。自励看到它就**完全不介入** —— 玩家自己掌权的那一局不该被自动施加。
MANUAL_VAR = "sitai_probe_ab_manual"

# ⚠️ **t18 的 test 0 专测牌已按口径撤掉**（t15 §1.4 的「用完即撤」）：它曾在
#    `common/ai_strategies/` 下临时发过一张 `possible = { always = no }` + `weight = 10000`
#    的牌，配一条 `set_strategy` 直置与一行 `GATE0` 自报。结论 = **门不挡直置**
#    （7/7 行 `yes`、零报错）⇒ 递牌不作承重；那张牌若留着会污染之后每一局
#    （权重 10000 会几乎占满政治槽）。原始读数与判词见
#    `docs/design/exec/阶段5-新增牌-结果.md`；判据见 `阶段5-新增牌-口径.md` §1.4 / §7。

#: 「**立法开没开**」要盯的法（2026-09-22 新增的 `ENACT` 读数）。
#:
#: 为什么必须有这一行：阶段 3 重做的实机结果是"牌换了、法不动"，而三个候选
#: （政府支持不足 / 怕革命 / 权重不够）在"每月只记法律名"的读数下**长得一模一样**。
#: `is_enacting_law` 是引擎触发器（真在推这条法时为真），它把
#: **从未开立法** 与 **开了没成** 分开 —— 前者指向"AI 不肯动手"，后者指向"立法过程"。
#:
#: 旧二进制候选名称搜索未找到通用接口；2026-10-05 原版脚本核对已纠正：
#: `enacting_any_law = yes` 可读任意立法是否进行（00_code_on_actions.txt:4549），
#: `exists = currently_enacting_law` 也有原版先例。此历史仪器继续按下列局部清单
#: 记录具体法律，新仪器从原版全量法律生成枚举，避免局部清单漏判。
#:
#: 为什么是这 20 条（覆盖俄罗斯开局最可能被推的组，不是全量 138 条）：
#: 土地改革整组（AI 改革的主战场）+ 权力分配整组（进步牌的 `max_progressiveness` 上限
#: 直接作用在这一组）+ 征税 + 奴隶制 + 义务教育。多问一条只是多一行日志，
#: 但**漏掉正在被推的那一条**就会得到假结论，所以宁可多列。
ENACT_LAWS: tuple[str, ...] = (
    # 土地改革（`lawgroup_land_reform`）—— 我们那条链的正主
    "law_serfdom",
    "law_tenant_farmers",
    "law_commercialized_agriculture",
    "law_peasant_proprietorship",
    "law_collectivized_agriculture",
    "law_homesteading",
    # 权力分配（`lawgroup_distribution_of_power`）—— 进步牌上限直接管这一组
    "law_autocracy",
    "law_oligarchy",
    "law_technocracy",
    "law_landed_voting",
    "law_wealth_voting",
    "law_census_voting",
    "law_universal_suffrage",
    # 征税 / 经济
    "law_consumption_based_taxation",
    "law_land_based_taxation",
    "law_per_capita_based_taxation",
    "law_proportional_taxation",
    "law_graduated_taxation",
    # 奴隶制 / 教育（改革派最爱推的两组）
    "law_slavery_banned",
    "law_compulsory_primary_school",
)

#: 政府在谁手里：只记与我们这条链直接相关的三个 IG（不做全量 IG 表）。
#: `landowners` 是守旧方的核心（`law_tenant_farmers` 把它 -0.25 政治力量），
#: `intelligentsia` / `industrialists` 是`progressive_agenda` 的 `pro_interest_groups`。
GOVERNMENT_IGS: tuple[tuple[str, str], ...] = (
    ("ig_landowners", "landowners"),
    ("ig_intelligentsia", "intelligentsia"),
    ("ig_industrialists", "industrialists"),
)

#: **要给"入阁距离"建趋势的那三个 IG**（两个改革派 + 一个守旧方作对照）。
#:
#: 为什么需要它：阶段 3 重做的结论是「政府里只有地主 ⇒ AI 从不行动」，而
#: `is_in_government` 只有真/假 —— **看不出改革派离入阁有多远**。
#: 于是"再加一点压力够不够"这个问题在二元读数下**无法回答**。
#: `ig_clout`（引擎触发器，`trigger_localization/00_trigger_localization.txt:2936`）
#: 给的是一个**可比较的量**，按档位夹逼就能把它变成趋势（与合法性那五档同一手法）。
CLOUT_IGS: tuple[tuple[str, str], ...] = (
    ("ig_intelligentsia", "intelligentsia"),
    ("ig_industrialists", "industrialists"),
    ("ig_landowners", "landowners"),
)

#: clout 的档位（**升序**；夹逼读法见 `on_actions_text` 的 CLOUT 段）。
#:
#: 为什么是这五档：`is_powerful` 的门槛是 **0.20**（`defines/00_defines.txt:189`
#: `POWERFUL_IG_THRESHOLD = 0.20`、`CUTOFF = 0.18`），所以 0.18 / 0.25 两档直接对应
#: "强势 / 边缘"这条线；0.03 以下在政治上基本等于不存在，0.08 / 0.12 是"有没有发言权"的中间段。
CLOUT_BANDS: tuple[float, ...] = (0.03, 0.08, 0.12, 0.18, 0.25)


def clout_band_name(value: float) -> str:
    """0.12 → ``b12``（百分数，两位数字宽；与 `LEG` 的 `b55` 同口味）。"""
    return f"b{round(value * 100):02d}"


#: 生成文件的头注释。与 h1 探针同一句式，但**指向自己的生成器** ——
#: 从前这里借用 `h1_probe.GEN_HEADER`，产物头部因此写着 `v3 h1-probe`（会误导人）。
GEN_HEADER = "# ⚠️ 本文件由 `v3 ab-probe` 生成（src/pdx/ab_probe.py）—— 改这里没用，改生成器。\n"

#: 缩进符（与原版脚本一致）。
TAB = "\t"

#: scripted_tests 的相对路径（相对探针根目录）。
SUITE_REL = "tools/scripted_tests/sitai_ab.txt"

#: 原版**自带**的套件：它们的 `last_date` 在 1870–1900 年。
#:
#: 为什么要在探针里覆盖它们：引擎会把 `tools/scripted_tests/` 下的**每一份**都当套件跑，
#: 只要套件还在跑，`-scripted_tests` 这一局就不会收工 —— 自动化的"跑到第 N 月就杀进程"
#: 会一直被原版那几套拖着。覆盖成"立即收敛"是唯一不改游戏安装目录的解法。
#:
#: ⚠️ 实测口径：mod 提供的套件**会**被读到（"只读安装目录"的假设已被证伪，
#: 见 `exec/阶段3-归档清点.md` §三）—— 所以这些文件放仓库即可，不必写进游戏目录。
VANILLA_SUITES = ("germany", "ip3", "italy", "springtime")

#: 收敛覆盖的到期日：开局 4 天之后，套件当天即"到日期仍未命中" → 判跳过、收工。
CONVERGE_DATE = "1836.1.5"

#: 探针的运行模式。默认 :data:`MODE_NATURAL` = 阶段 3 起一直在用的 A/B 阶梯（引擎真实节奏）。
#:
#: :data:`MODE_CONTROL` 是 t18 第 10 条的**判别性实验模式**（2026-09-25 加）。它要分开的
#: 两条活假设是：(i) 门从未开（压力修正没挂上）；(ii) 那张牌根本进不了政治槽。为此它做四件事，
#: **每一件都在生成物里写死、并逐月自报**：
#:
#: 1. **隔离直置**：只挂压力修正、**不设记忆变量**。档案 JE 的判据读的是
#:    `has_variable = <记忆变量>`（数据源 `[journal_entry.conditions]`）⇒ 变量不设 ⇒
#:    窗口不开 ⇒ 档案自己那条 `set_strategy = progressive_agenda` **一次都不执行**。
#:    这正是 B 臂 0/13 说不清的两个原因之一（另一个是门没有直读）。
#: 2. **门必开**：第 1 个月起无条件挂 `[pressure].name`（幂等：已挂着就不再挂）。
#: 3. **两张哨兵牌**（本探针自己的产物，**只在这个模式生成**）：
#:    * `…_sentinel_open`（门 = **变量**，权重 10000）在第 1–2 月开窗；
#:    * `…_sentinel_gate`（门 = **`has_modifier`**，与真牌同形，权重 10000）在第 3–4 月开窗。
#:    它们回答的是"**有没有重掷**"与"**带这种门的牌能不能进池**"，从而把上面两条假设分开。
#:    窗口靠窗口变量的 `days` 到期关掉（两个窗口**不重叠**），闸门变量只点一次。
#: 4. **风暴节奏**：覆盖 `NAI` 的两个键，把重掷从"攒够 100 点"压到"每周都掷"。原版是
#:    `CHANGE_STRATEGY_THRESHOLD = 100` + 每周 20% 概率 +1 点（`common/defines/00_ai.txt:38-39`）
#:    ⇒ 单靠周通道 ≈9.6 年一次（阶段 2 实测 0.37%/月）⇒ **24 个月的天然观测窗里重掷期望 ≈0.2 次**，
#:    B 臂那种"12 个月看落点"的判据**天生观测不到重掷**。先例：`h1_probe` 的 `storm` 变体
#:    （阶段 2 实测生效）、`modguard.py:63` 引作"改原版全局参数的唯一合法方式"。
#:
#: ⚠️ 第 4 件是**实验干预**：它改的是 AI **什么时候**重抽，不改"抽谁"的语义（权重与 `possible`
#: 求值走的是同一条路）。所以它只用来回答"进不进得了池"，**不许**拿它的落点频率去说自然节奏。
MODE_ENV = "V3_AB_MODE"

#: 默认模式：引擎真实节奏（不挂压力、不加哨兵、不改 defines）。
MODE_NATURAL = "natural"

#: 判别性实验模式（见 :data:`MODE_ENV` 上那段）。
MODE_CONTROL = "control"

#: 合法模式（顺序 = 报错信息里的枚举顺序）。
MODES: tuple[str, ...] = (MODE_NATURAL, MODE_CONTROL)


def active_mode(env: Mapping[str, str] | None = None) -> str:
    """这一次生成用哪个模式 —— 只认**显式**的环境变量，默认 :data:`MODE_NATURAL`。

    为什么用环境变量而不是再加一个 CLI 开关（取舍与代价都写明）：向 `v3 ab-probe`
    加 `--mode` 要改 `src/pdx/cli.py`，而那个文件不在 t18 的 inScope 里。
    环境变量是**一次性**的（每个进程一份），不会像"目录里放个标记文件"那样在**下一局**
    悄悄改变生成物；值不合法就地报错，**不回落**到默认。

    ⚠️ 它**不是**静默开关：模式写进每一份生成文件的头，并且探针**逐月**自报
    `MODE` / `STORM` 两行；读数侧（:func:`card_verdict`）可以要求这两行与预期一致，
    不一致直接判红 —— 于是"把控制局的读数当成自然局"这件事没有静默空间。
    """
    raw = (env if env is not None else os.environ).get(MODE_ENV, "").strip().lower()
    if not raw:
        return MODE_NATURAL
    if raw not in MODES:
        raise ValueError(f"{MODE_ENV}={raw!r} 不是合法模式；可选：{'、'.join(MODES)}；不给 = 默认")
    return raw


#: 两张哨兵牌的名字。前缀 `zz_probe_ab_` ⇒ `probe_lint.OUR_PREFIXES` 认得它们是我们
#: 自己的东西（`has_strategy` 的读数不会判"原版里没有这张牌"）。
SENTINEL_OPEN = "ai_strategy_zz_probe_ab_sentinel_open"
SENTINEL_GATE = "ai_strategy_zz_probe_ab_sentinel_gate"

#: 哨兵牌的**窗口变量**（`possible` 读它）与**闸门变量**（只点一次，防止窗口被重新点亮）。
SENTINEL_OPEN_VAR = "sitai_probe_ab_sentinel_open"
SENTINEL_GATE_VAR = "sitai_probe_ab_sentinel_gate"
SENTINEL_OPEN_LATCH = "sitai_probe_ab_latch_open"
SENTINEL_GATE_LATCH = "sitai_probe_ab_latch_gate"

#: 哨兵权重：**压倒性地大**。理由不是"想让它赢"，而是"要么看见它、要么证明确实没有重掷"：
#: 政治槽其余候选的权重和按阶段 2 的价格表是 S≈33 ⇒ 任何一次重掷里哨兵赢的概率 ≈99.7%，
#: 于是"哨兵没出现"几乎只能是"重掷没发生"。窗口一关它就不在池里，**不遮**真牌。
SENTINEL_WEIGHT = 10000

#: 两个哨兵窗口（月，闭区间）与窗口时长（天）。**不重叠**是硬要求：两个 10000 权重的牌
#: 同时在池里时"谁赢"是随机的，那就等于同时测两件事、结论说不清。
SENTINEL_OPEN_MONTHS: tuple[int, int] = (1, 2)
SENTINEL_GATE_MONTHS: tuple[int, int] = (3, 4)
SENTINEL_DAYS = 60


def sentinel_card_text(name: str, clauses: tuple[str, ...], why: str) -> str:
    """一张哨兵牌（`possible` 的每个子句一行）。**只在 `control` 模式生成**。"""
    possible = "\n".join(f"{TAB * 2}{clause}" for clause in clauses)
    return (
        f"{GEN_HEADER}"
        f"# {why}\n"
        f"# ⚠️ 只在 `{MODE_ENV}={MODE_CONTROL}` 时生成；`{MODE_NATURAL}` 模式下这份文件**不存在**"
        f"（`write()` 会清掉另一种模式留下的文件）。\n"
        f"\n"
        f"{name} = {{\n"
        f"{TAB}type = {POLITICAL_SLOT}\n"
        f"\n"
        f"{TAB}possible = {{\n"
        f"{possible}\n"
        f"{TAB}}}\n"
        f"\n"
        f"{TAB}weight = {{\n"
        f"{TAB * 2}value = {SENTINEL_WEIGHT}\n"
        f"{TAB}}}\n"
        f"}}\n"
    )


def sentinel_files(pressure: str) -> dict[str, str]:
    """`control` 模式多出来的两张哨兵牌（相对探针根目录）。"""
    return {
        "common/ai_strategies/zz_probe_ab_sentinel_open.txt": sentinel_card_text(
            SENTINEL_OPEN,
            (f"has_variable = {SENTINEL_OPEN_VAR}",),
            "哨兵①：门 = **变量**。它测的是「到底有没有重掷」 —— 权重 10000 在池里，"
            "只要引擎重掷一次就几乎必然落它。",
        ),
        "common/ai_strategies/zz_probe_ab_sentinel_gate.txt": sentinel_card_text(
            SENTINEL_GATE,
            (f"has_modifier = {pressure}", f"has_variable = {SENTINEL_GATE_VAR}"),
            f"哨兵②：门 = `has_modifier = {pressure}`，**与真牌同形**。"
            "它测的是「`possible` 里读修正这条外推在实机上成不成立」（t15 §7 那个问题）。",
        ),
    }


def defines_text() -> str:
    """`control` 模式的风暴覆盖：按「块 + 参数」覆盖 `NAI` 的两个键（**不复制**原版 `00_ai.txt`）。"""
    return (
        f"{GEN_HEADER}"
        f"# ⚠️ 这是**实验干预**，不是正式版设计：它改的是 AI **什么时候**重抽，不改「抽谁」的语义。\n"
        f"#\n"
        f"# 原版值：`CHANGE_STRATEGY_THRESHOLD = 100`、`CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE = 20`\n"
        f"# （`common/defines/00_ai.txt:38-39`；同文件 :41 起是那三条加速通道：换统治者 +100、\n"
        f"#   改政体 +100、立法 +25）。原版语义 = 攒够 100 个「变更点」才重抽一次，\n"
        f"# 而周通道每周只有 20% 概率 +1 点 ⇒ 单靠它 ≈9.6 年一次（= 政治槽实测 0.37%/月）。\n"
        f"#\n"
        f"# 本模式把门槛压到 1、周概率拉满 ⇒ **每周都重抽**。为什么必须这么做：\n"
        f"# 24 个月的天然窗口里重掷期望 ≈0.2 次 ⇒ 「12 个月看落点」的判据观测不到重掷，\n"
        f"# 于是「没抽到」与「进不了池」分不开（t18 的 B 臂 0/13 就是这么来的）。\n"
        f"# 先例：`h1_probe` 的 `storm` 变体（阶段 2 实测生效）；`modguard.py:63` 把这种写法\n"
        f"# 记作「我们改原版全局参数的唯一合法方式」（KB 05 §1.7 的按「块 + 参数」覆盖）。\n"
        f"NAI = {{\n"
        f"{TAB}CHANGE_STRATEGY_THRESHOLD = 1\n"
        f"{TAB}CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE = 100\n"
        f"}}\n"
    )


def control_monthly_lines(target: ProbeTarget, *, tab: str = "\t") -> str:
    """`control` 模式在月度体里多做的三件事（挂门 + 两张哨兵的窗口）。

    为什么写在**月度体**而不是臂阶梯里：阶梯的语义是"第 N 月起施加**一次**"，而哨兵窗口
    要"开**也得关**" —— 用阶梯写不出"第 1–2 月开着、第 3 月起必须关掉"。幂等靠两个闸门变量
    （只点一次）+ 窗口变量自己的 `days` 到期。

    读不到 `[pressure].name` 就**报错**，不生成：否则门永远为假，实验会静默变成"什么都没测"。
    """
    pressure = target.pressure_modifier
    if not pressure:
        raise RuntimeError(
            f"control 模式要求档案 {target.archive_id!r} 声明 [pressure].name（门名从数据源读）——"
            "读不到就报错，不生成一份门永远为假的探针"
        )
    open_lo, open_hi = SENTINEL_OPEN_MONTHS
    gate_lo, gate_hi = SENTINEL_GATE_MONTHS
    return "\n".join(
        [
            f"{tab * 3}# ══ control 模式（判别性实验）══ 见 `{MODE_ENV}` 那一段的说明。",
            f"{tab * 3}# ① 门必开：第 1 个月起无条件挂压力修正，**不设记忆变量** ⇒ 归档的直置一次都不发生。",
            f"{tab * 3}if = {{",
            f"{tab * 4}limit = {{",
            f"{tab * 5}var:{MONTH_VAR} >= 1",
            f"{tab * 5}NOT = {{ has_modifier = {pressure} }}",
            f"{tab * 4}}}",
            f"{tab * 4}add_modifier = {{ name = {pressure} years = 10 }}",
            f"{tab * 3}}}",
            f"{tab * 3}# ② 哨兵①（门 = 变量）：第 {open_lo}–{open_hi} 月开窗 ⇒ 证明「引擎真的在重揗」。",
            f"{tab * 3}if = {{",
            f"{tab * 4}limit = {{",
            f"{tab * 5}NOT = {{ has_variable = {SENTINEL_OPEN_LATCH} }}",
            f"{tab * 5}var:{MONTH_VAR} >= {open_lo}",
            f"{tab * 4}}}",
            f"{tab * 4}set_variable = {{ name = {SENTINEL_OPEN_LATCH} value = 1 }}",
            f"{tab * 4}set_variable = {{ name = {SENTINEL_OPEN_VAR} value = 1 days = {SENTINEL_DAYS} }}",
            f"{tab * 3}}}",
            f"{tab * 3}# ③ 哨兵②（门 = `has_modifier`，与真牌同形）：第 {gate_lo}–{gate_hi} 月开窗。",
            f"{tab * 3}if = {{",
            f"{tab * 4}limit = {{",
            f"{tab * 5}NOT = {{ has_variable = {SENTINEL_GATE_LATCH} }}",
            f"{tab * 5}var:{MONTH_VAR} >= {gate_lo}",
            f"{tab * 4}}}",
            f"{tab * 4}set_variable = {{ name = {SENTINEL_GATE_LATCH} value = 1 }}",
            f"{tab * 4}set_variable = {{ name = {SENTINEL_GATE_VAR} value = 1 days = {SENTINEL_DAYS} }}",
            f"{tab * 3}}}",
        ]
    )


def effects_text(target: ProbeTarget, *, mode: str = MODE_NATURAL) -> str:
    """三个效果：武装阶梯、月度走一格、以及（决议用的）重新武装。

    角色仍然不是"装哪个探针"决定的 —— 但也不再是"点哪个决议"：**点一次就够**，
    之后由阶梯自己按月份换臂（这正是"一次点击换整条阶梯的数据"）。

    ⚠️ ``mode=control`` 时**阶梯是空的**（手臂一格都不施加）。这不是省事，是**隔离的前提**：
    t18 阶梯的第 B 格调的是档案的冲击效果，而那个效果会设记忆变量 ⇒ JE 窗口开 ⇒
    档案自己那条 `set_strategy` 直置会跑 —— 那就把"门/权重能不能让牌进池"这件事
    和"直置换路线"搅在一起，B 臂 0/13 正是这么变得不可归因的。控制局的门由月度体
    直接挂压力修正（:func:`control_monthly_lines`），**全程不碰记忆变量**。
    """
    ladder = () if mode == MODE_CONTROL else ladder_for(target)
    selfarm = tuple(
        (step.at_month, step.note, step.effect) for step in ladder[1:] if step.effect is not None
    )
    arms: list[str] = []
    for index, step in enumerate(ladder[1:], start=1):
        arms.append(
            f"{TAB * 2}# 第 {step.at_month} 月起 → {step.note}\n"
            f"{TAB * 2}if = {{\n"
            f"{TAB * 3}limit = {{\n"
            f"{TAB * 4}var:{STAGE_VAR} <= {index}\n"
            f"{TAB * 4}var:{MONTH_VAR} >= {step.at_month}\n"
            f"{TAB * 3}}}\n"
            f"{TAB * 3}set_variable = {{ name = {STAGE_VAR} value = {index + 1} }}\n"
            f'{TAB * 3}debug_log = "ZZPROBE AB;RUN;{step.role}"\n'
            f"{TAB * 3}{step.effect} = yes\n"
            f"{TAB * 2}}}"
        )
    ladder_body = "\n\n".join(arms)
    # 自励阶梯：月度脉冲按 `is_ai` 自动武装 —— 观察者局没有玩家国家，**决议点不了**，
    # 所以「点一次决议」这条入口在观察者局里是死的（阶段 3 的结构性阻断）。
    selfarm_body = "\n\n".join(
        (
            f"{TAB * 2}# 第 {month} 月：{note}\n"
            f"{TAB * 2}if = {{\n"
            f"{TAB * 3}limit = {{\n"
            f"{TAB * 4}var:{SELFARM_VAR} < {index}\n"
            f"{TAB * 4}var:{MONTH_VAR} >= {month}\n"
            f"{TAB * 3}}}\n"
            f"{TAB * 3}set_variable = {{ name = {SELFARM_VAR} value = {index} }}\n"
            f'{TAB * 3}debug_log = "ZZPROBE AB;SELFARM;{month};'
            f'[THIS.GetCountry.GetNameNoFormatting]"\n'
            f"{TAB * 3}{effect} = yes\n"
            f"{TAB * 2}}}"
        )
        for index, (month, note, effect) in enumerate(selfarm, start=1)
    )
    # 控制局的额外说明（只在 control 模式拼进文件头）：阶梯是空的，隔离靠「不设记忆变量」。
    control_note = (
        f"#\n"
        f"# ⚠️ **本局是控制局**（{MODE_ENV}={MODE_CONTROL}）：上面③那条阶梯**是空的** —— 一格都不施加。\n"
        f"#    理由：台阶 B 会调 `{target.shock_effect}` ⇒ 它会设记忆变量 ⇒ 档案 JE 的窗口开 ⇒\n"
        f"#    档案那条 `set_strategy` 直置跟着跑，「门/权重能不能让牌进池」与「直置换路线」就混在一起。\n"
        f"#    控制局的门由月度体直接挂压力修正（幂等），**全程不设记忆变量**：\n"
        f"#    `SHOCK;no` 会逐月写出来，`JE` 也应全程不出现 —— 那是隔离的**读数证据**，不是声明。\n"
        if mode == MODE_CONTROL
        else ""
    )

    return (
        f"{GEN_HEADER}"
        f"# ⚠️ **本文件里只能有裸效果列表**（scripted_effects 的语法）：写成 on_action 那种\n"
        f"#    `effect = {{ … }}` 包装会被引擎读成「调一个叫 effect 的效果」→\n"
        f"#    `Unknown effect effect`，整个定义作废而 on_action 那头只报\n"
        f"#    `No on_action scripted with tag … cannot link`（阶段 2 实测：分组一次没跑、\n"
        f"#    白跑一整局）。钩子/包装在 `zz_probe_ab_on_actions.txt` 里。\n"
        f"#\n"
        f"# ① `zz_probe_ab_arm`：**点一次决议**武装整条阶梯（由决议调用，作用于 {target.subject}）。\n"
        f"#    可重复调用 —— 每点一次就把月份与阶段清零重跑（同一存档里重跑一局的做法）。\n"
        f"# ② `zz_probe_ab_selfarm`：**不点决议**的武装路径（`is_ai = yes` 时按月份自动走）。\n"
        f"#    为什么必须有它：观察者局**没有玩家国家**，决议永远点不到 —— 阶段 3 的臂阶梯\n"
        f"#    一次都没跑起来就是这个原因（`阶段3-结果.md` §六）。它只认 `is_ai`，\n"
        f"#    所以玩家自己掌权时不会抢手（玩家局仍走决议那条路）。\n"
        f"# ③ `zz_probe_ab_ladder`：每月走一格。**幂等**是硬要求：`{STAGE_VAR}` 单调递增，\n"
        f"#    每个效果只施加一次；不拿「有没有那个修正」当判据（会被别的系统碰到）。\n"
        f"# ④ `{target.shock_effect}` / `{target.input_effect}` 在**legacy 档案 mod**里（`v3 modgen` 生成），\n"
        f"#    探针只调用它们 —— 这样实验用的世界状态与档案本身是同一份定义。\n"
        f"{control_note}"
        f"zz_probe_ab_arm = {{\n"
        f'{TAB}debug_log = "ZZPROBE AB;RUN;A"\n'
        f"{TAB}# 这一局盯的是**哪一份档案** —— 分析器靠它认主语（日志里的国名是本地化的，"
        f"不是 tag）。\n"
        f'{TAB}debug_log = "ZZPROBE AB;TARGET;{target.archive_id}"\n'
        f"{TAB}# 标记「决议武装过」—— 自励路径看到它就完全不介入。\n"
        f"{TAB}set_variable = {{ name = {MANUAL_VAR} value = 1 }}\n"
        f"{TAB}# 月份从 0 起数：武装之后的下一次月度脉冲才是第 1 月。\n"
        f"{TAB}set_variable = {{ name = {MONTH_VAR} value = 0 }}\n"
        f"{TAB}set_variable = {{ name = {STAGE_VAR} value = 1 }}\n"
        f"}}\n"
        f"\n"
        f"zz_probe_ab_selfarm = {{\n"
        f"{TAB}# 只对 **AI 国家**生效，且**只在这个国家没被决议武装过时**介入 ——\n"
        f"{TAB}# 玩家自己掌权的那一局由决议作唯一入口，自动路径完全不碰它。\n"
        f"{TAB}if = {{\n"
        f"{TAB * 2}limit = {{\n"
        f"{TAB * 3}is_ai = yes\n"
        f"{TAB * 3}NOT = {{ has_variable = {MANUAL_VAR} }}\n"
        f"{TAB * 2}}}\n"
        f"{TAB * 2}if = {{\n"
        f"{TAB * 3}limit = {{ NOT = {{ has_variable = {SELFARM_VAR} }} }}\n"
        f"{TAB * 3}set_variable = {{ name = {SELFARM_VAR} value = 0 }}\n"
        f"{TAB * 3}set_variable = {{ name = {MONTH_VAR} value = 0 }}\n"
        f"{TAB * 3}set_variable = {{ name = {STAGE_VAR} value = 1 }}\n"
        f"{TAB * 3}# 这一局盯的是哪一份档案 —— **两条武装路径都要写**：观察者局只走这一条\n"
        f"{TAB * 3}# （没有玩家国家 ⇒ 决议点不到），只写在决议那条上等于没写（实测踩过）。\n"
        f'{TAB * 3}debug_log = "ZZPROBE AB;TARGET;{target.archive_id}"\n'
        f"{TAB * 2}}}\n"
        f"{TAB * 2}change_variable = {{ name = {MONTH_VAR} add = 1 }}\n"
        f"\n"
        f"{selfarm_body}\n"
        f"{TAB}}}\n"
        f"}}\n"
        f"\n"
        f"zz_probe_ab_ladder = {{\n"
        f"{TAB}# 没被武装过的国家一行都不动（决议与自励是仅有的两个开关）。\n"
        f"{TAB}if = {{\n"
        f"{TAB * 2}limit = {{ has_variable = {STAGE_VAR} }}\n"
        f"\n"
        f"{TAB * 2}# A 臂（第 {ARM_START['A']}–{ARM_START['B'] - 1} 月）：对照组，什么都不做 —— 没有分支就是它。\n"
        f"\n"
        f"{ladder_body}\n"
        f"{TAB}}}\n"
        f"}}\n"
    )


def _slot_chains(vanilla: list[ai_surface.Card]) -> str:
    """三个槽位的落点链（复用 h1 的自报链，只是换个前缀）。"""
    blocks: list[str] = []
    for slot in SLOTS:
        names = h1_probe.vanilla_chain_cards(vanilla, slot)
        chain = h1_probe.log_chain(SLOT_SHORT[slot], names)
        blocks.append(chain.replace("ZZPROBE H1;", "ZZPROBE AB;"))
    return "\n\n".join(blocks)


def on_actions_text(
    vanilla: list[ai_surface.Card],
    target: ProbeTarget,
    *,
    own: list[str] | None = None,
    mode: str = MODE_NATURAL,
) -> str:
    """开局不挂任何东西；每月先自励、再走一格阶梯，最后**只记主角国家**。

    ``own`` 是**我们自己的政治槽牌名**（缺省从盘上产物现读，见 :func:`own_cards`）。
    测试要造"有我们自己牌"的生成物时显式传一个 —— 否则这条路径只能等真档案先加牌才走得到。

    ``mode`` 见 :data:`MODE_ENV`：``control`` 时多出（①）第 1 月起无条件挂压力修正、
    （②③）两张哨兵的窗口，以及 `SENT` 两行读数。**`natural` 的产物一行都不含这些。**
    """
    tab = "\t"
    laws = "\n".join(
        f"{tab * 3}{keyword} = {{\n"
        f"{tab * 4}limit = {{ has_law = law_type:{law} }}\n"
        f'{tab * 4}debug_log = "ZZPROBE AB;LAW;{law};[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"{tab * 3}}}"
        for keyword, law in zip(["if", *["else_if"] * (len(LAWS) - 1)], LAWS, strict=True)
    )
    # 策略牌读数：`has_strategy` 逐张问一遍（原版就是这么写的，见
    # `ai_strategies/03_political_strategies.txt` 里的 `NOT = { has_strategy = … }`）。
    # 候选集**现读原版**（见 `strategy_candidates` 上那段 B87），并补两条兜底：
    # `default` 与 `none` —— 否则"这张牌不在清单里"会变成日志里的一片沉默。
    #
    # ⚠️ **我们自己的牌必须插在链首**（2026-09-25）：`if / else_if` 是**命中即停**的，
    #    追加在 `default` 之后等于永远读不到它 —— 引擎真选中了我们的牌，前面的分支
    #    也会先命中，日志里看到的仍是那张原版牌。这就是 B87 的同族失真换了个位置。
    #    顺序由 `test_ab_probe.py` 的顺序用例钉住（`code.index(我们的牌) < code.index(default)`）。
    ours = own_cards() if own is None else list(own)
    chain = [*ours, *strategy_candidates(vanilla), "ai_strategy_default"]
    strategies = "\n".join(
        [
            *(
                f"{tab * 3}{'if' if index == 0 else 'else_if'} = {{\n"
                f"{tab * 4}limit = {{ has_strategy = {name} }}\n"
                f'{tab * 4}debug_log = "ZZPROBE AB;STRATEGY;{name};'
                f'[THIS.GetCountry.GetNameNoFormatting]"\n'
                f"{tab * 3}}}"
                for index, name in enumerate(chain)
            ),
            f"{tab * 3}else = {{",
            (
                f'{tab * 4}debug_log = "ZZPROBE AB;STRATEGY;none;'
                f'[THIS.GetCountry.GetNameNoFormatting]"'
            ),
            f"{tab * 3}}}",
        ]
    )
    # ⚠️ **不做整体 re-indent**（2026-09-22 修）：这里以前写成
    # `.replace("\n" + tab * 2, "\n" + tab * 3)`，把三槽自报链的缩进整体右移一格。
    # 结果是嵌套块（`if` 里的 `if`）被移成**双倍缩进**，读起来像语法错误。
    # PDX 脚本对缩进不敏感，所以那不是 bug，但它把生成物变成了"不敢读"的东西。
    # 正确做法：只给**这一层的块定界行**加缩进，块里的内容交给它自己的生成器。
    chains = _slot_chains(vanilla)

    def guarded(body: str) -> str:
        """把一段自报包进「只记主角国家」的守卫里。"""
        return f"{tab * 2}if = {{\n{tab * 3}limit = {{ c:{target.subject} ?= this }}\n{body}\n{tab * 2}}}"

    def state_line(kind: str, trigger: str, yes: str, no: str) -> str:
        """一行"在/不在"诊断（冲击与改革侧输入各一行，形状完全一致）。"""
        return "\n".join(
            [
                f"{tab * 3}if = {{",
                f"{tab * 4}limit = {{ {trigger} }}",
                (
                    f'{tab * 4}debug_log = "ZZPROBE AB;{kind};{yes};'
                    f'[THIS.GetCountry.GetNameNoFormatting]"'
                ),
                f"{tab * 3}}}",
                f"{tab * 3}else = {{",
                (
                    f'{tab * 4}debug_log = "ZZPROBE AB;{kind};{no};'
                    f'[THIS.GetCountry.GetNameNoFormatting]"'
                ),
                f"{tab * 3}}}",
            ]
        )

    control = mode == MODE_CONTROL
    pressure = target.pressure_modifier
    # (a) 门直读（t18 第 10 条）。门名从**数据源**读（`[pressure].name`）；这份档案没有压力
    # 修正时**不写**这一行 —— 写一行永远为 `no` 的读数，与"门真的没开"在日志里长得一样。
    gate_lines = [state_line("GATE", f"has_modifier = {pressure}", "yes", "no")] if pressure else []
    # (b) **每张自建牌一行显式 yes/no**（t18 第 10 条）：不依赖 `STRATEGY` 链那行文本 ——
    # 那条链是"命中即停"的，只能证明"落点是哪一张"，证明不了"引擎到底有没有持有它"。
    # 形状：`HELD;<完整牌名>=yes|no;<国名>`（取值位里带牌名 ⇒ 一张多牌也分得清）。
    held_lines = [
        state_line("HELD", f"has_strategy = {name}", f"{name}=yes", f"{name}=no") for name in ours
    ]
    # 模式与节奏必须**逐月写出来**：读数侧要能把"控制局的读数"与"自然局"分开，
    # 否则一个 0 命中既能读成"进不了池"、也能读成"这局压根没重掷"（t18 B 臂的原病）。
    mode_lines = [
        (f'{tab * 3}debug_log = "ZZPROBE AB;MODE;{mode};[THIS.GetCountry.GetNameNoFormatting]"'),
        (
            f'{tab * 3}debug_log = "ZZPROBE AB;STORM;{"yes" if control else "no"};'
            f'[THIS.GetCountry.GetNameNoFormatting]"'
        ),
    ]
    sentinel_lines: list[str] = []
    if control:
        sentinel_lines = [
            state_line(
                "SENT",
                f"has_strategy = {SENTINEL_OPEN}",
                f"{SENTINEL_OPEN}=yes",
                f"{SENTINEL_OPEN}=no",
            ),
            state_line(
                "SENT",
                f"has_strategy = {SENTINEL_GATE}",
                f"{SENTINEL_GATE}=yes",
                f"{SENTINEL_GATE}=no",
            ),
        ]
    control_body = control_monthly_lines(target, tab=tab) if control else ""

    behaviour = "\n".join(
        [
            guarded(
                "\n".join(
                    [
                        (
                            f'{tab * 3}debug_log = "ZZPROBE AB;ROLE;{target.subject};'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        "",
                        *mode_lines,
                        "",
                        f"{tab * 3}# ① 先自励（**不点决议**：观察者局没有玩家国家，决议点不了）。",
                        f"{tab * 3}#    排在阶梯之前 —— 第 13 月那一格会武装并施加冲击，",
                        f"{tab * 3}#    必须让阶梯看到已经武装好的状态。",
                        f"{tab * 3}zz_probe_ab_selfarm = yes",
                        "",
                        f"{tab * 3}# ② 再走臂阶梯：换臂那一月必须算进**新臂**，",
                        f"{tab * 3}#    所以 RUN 行要排在同月的自报行之前。",
                        f"{tab * 3}zz_probe_ab_ladder = yes",
                        "",
                        *([control_body, ""] if control_body else []),
                        f"{tab * 3}# ③ 两处输入到底有没有落到这个国家身上（自检用）",
                        state_line("SHOCK", f"has_variable = {target.shock_variable}", "yes", "no"),
                        "",
                        state_line("INPUT", f"has_modifier = {target.input_modifier}", "yes", "no"),
                        "",
                        f"{tab * 3}# ③·补 (a) **门直读**（t18 第 10 条）：门开没开要有一行直读，",
                        f"{tab * 3}#    不许再从记忆变量旁证（B 臂 0/13 的归因缺口就是它）。",
                        *gate_lines,
                        "",
                        f"{tab * 3}# （t18 的 test 0 直置与 `GATE0` 自报已按口径撤掉 —— 见文件头那段；",
                        f"{tab * 3}#  结论 = 门不挡直置，递给通道不作承重。）",
                        "",
                        f"{tab * 3}# ④ 当前挂着的政治牌（策略层读数；B53：牌才是闸门）",
                        strategies,
                        "",
                        f"{tab * 3}# ④·补 我们自己的牌**逐月在/不在**（2026-09-25 加；口径见",
                        f"{tab * 3}#    `docs/design/exec/阶段5-新增牌-口径.md` §4）。两个理由：",
                        f"{tab * 3}#    ① 上面那条链只在**命中时**写一行，这一条每月都写（含 `none`）",
                        f"{tab * 3}#       —— 于是「我们的牌没被选中」是**写出来**的，不是从缺席倒推的；",
                        f"{tab * 3}#    ② 它独立于那条链的语义 ⇒ 两条读数不一致就是链被挪动过",
                        f"{tab * 3}#       （顺序用例之外的第二道防线）。",
                        own_card_chain(ours, tab=tab),
                        *(
                            [
                                "",
                                f"{tab * 3}# ④·补② (b) **每张自建牌一行显式 yes/no**（t18 第 10 条）：",
                                f"{tab * 3}#    上面那条 `CARD` 链是「命中即停」的，只能证明「落点是哪一张」；",
                                f"{tab * 3}#    这一族逐张问 `has_strategy`，取值位里带**完整牌名** ⇒",
                                f"{tab * 3}#    「引擎到底有没有持有它」不再依赖任何链的文本。",
                                *held_lines,
                            ]
                            if held_lines
                            else []
                        ),
                        *(
                            [
                                "",
                                f"{tab * 3}# ④·补③ `SENT` 两行：两张**哨兵牌**（只在 control 模式生成）。",
                                f"{tab * 3}#    「没有重掷」、「门形状不成立」、「牌进不了池」三者分不开 ⇒ 不判决。",
                                f"{tab * 3}#    引擎真的在重掷；哨兵②（门 = `has_modifier`，与真牌同形）",
                                f"{tab * 3}#    出现 ⇒ `possible` 里读修正这条外推成立。两条都没出现 ⇒",
                                f"{tab * 3}#    「没有重掷」、「门形状不成立」、「牌进不了池」三者分不开 ⇒ 不判决。",
                                *sentinel_lines,
                            ]
                            if sentinel_lines
                            else []
                        ),
                        "",
                        f"{tab * 3}# ④·补② 难度档位（阶段 6；口径见 `exec/阶段6-国家身份开局-取证口径.md`",
                        f"{tab * 3}#    §3.3 第 1 条）。互斥链回答「是哪一档」，三档各自的",
                        f"{tab * 3}#    yes/no 保证另两档也留痕 —— 承重判据要的是那个**组合**。",
                        difficulty_rule_lines(tab=tab),
                        "",
                        f"{tab * 3}# ⑤ **立法到底开没开**（2026-09-22 新增）—— 这一行是",
                        f"{tab * 3}#    「牌换了法不换」三个候选的分辨器：原版读本 `laws/readme.md:9-10`",
                        f"{tab * 3}#    点名「缺政府/运动支持」与「怕革命」都会让法推不动，而两者",
                        f"{tab * 3}#    在「每月只记法律名」的读数下**长得一模一样**。",
                        f"{tab * 3}#    判据：`is_enacting_law`（引擎触发器）——真在推这条法时为真。",
                        f"{tab * 3}#    ⚠️ **没有「任意法」的通用写法**（exe 检索 5 个候选名全 0 命中），",
                        f"{tab * 3}#    所以只能逐条问 —— 全没推时写 `none`，否则分不清「没记」与「没开」。",
                        f"{tab * 3}if = {{",
                        f"{tab * 4}limit = {{",
                        f"{tab * 5}OR = {{",
                        *(f"{tab * 6}is_enacting_law = law_type:{law}" for law in ENACT_LAWS),
                        f"{tab * 5}}}",
                        f"{tab * 4}}}",
                        f"{tab * 4}# 逐条问「是哪一条」（只给读数用，判据与上面同一个触发器）。",
                        *(
                            (
                                f"{tab * 4}if = {{\n"
                                f"{tab * 5}limit = {{ is_enacting_law = law_type:{law} }}\n"
                                f'{tab * 5}debug_log = "ZZPROBE AB;ENACT;{law};'
                                f'[THIS.GetCountry.GetNameNoFormatting]"\n'
                                f"{tab * 4}}}"
                            )
                            for law in ENACT_LAWS
                        ),
                        f"{tab * 3}}}",
                        f"{tab * 3}else = {{",
                        (
                            f'{tab * 4}debug_log = "ZZPROBE AB;ENACT;none;'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        f"{tab * 3}}}",
                        "",
                        f"{tab * 3}# ⑥ 政府在谁手里（若「缺政府支持」这一支成立，得能看见政府在谁手里）。",
                        f"{tab * 3}#    只记三个与我们这条链直接相关的 IG，不做全量 IG 表。",
                        *(
                            f"{tab * 3}if = {{\n"
                            f"{tab * 4}limit = {{ ig:{name} ?= {{ is_in_government = yes }} }}\n"
                            f'{tab * 4}debug_log = "ZZPROBE AB;GOV;{short};'
                            f'[THIS.GetCountry.GetNameNoFormatting]"\n'
                            f"{tab * 3}}}"
                            for name, short in GOVERNMENT_IGS
                        ),
                        "",
                        f"{tab * 3}# ⑦ **入阁距离**（2026-09-22 新增）：`is_in_government` 只有真/假，",
                        f"{tab * 3}#    看不出改革派离入阁还有多远 ⇒ 用 `ig_clout` 夹逼成五档，",
                        f"{tab * 3}#    把「再加一点压力够不够」从不可回答变成可观测的趋势。",
                        f"{tab * 3}#    档位 0.18 / 0.25 直接对应 `is_powerful` 那条线",
                        f"{tab * 3}#    （defines/00_defines.txt:189 POWERFUL_IG_THRESHOLD = 0.20 / CUTOFF = 0.18）。",
                        *(
                            "\n".join(
                                [
                                    f"{tab * 3}if = {{",
                                    f"{tab * 4}limit = {{ ig:{name} ?= {{ ig_clout >= {band} }} }}",
                                    (
                                        f'{tab * 4}debug_log = "ZZPROBE AB;CLOUT;{short};'
                                        f"{clout_band_name(band)};"
                                        f'[THIS.GetCountry.GetNameNoFormatting]"'
                                    ),
                                    f"{tab * 3}}}",
                                ]
                            )
                            for name, short in CLOUT_IGS
                            for band in CLOUT_BANDS
                        ),
                        "",
                        f"{tab * 3}# 诊断：**合法性数值**（2026-09-24 起记数字，不再只记档位）。",
                        f"{tab * 3}# 原来这里是五档夹逼（b55/b60/b70/b75/b80），理由是「没有已证可用的",
                        f"{tab * 3}# 命令能打印一个数」。那条判断是错的，三条证据：",
                        f"{tab * 3}#   ① 原版提示里就是这么打的 —— `localization/english/alerts_l_english.yml:262`",
                        f"{tab * 3}#      逐字 `[GetPlayer.GetGovernmentLegitimacy|v]`；",
                        f"{tab * 3}#   ② `debug_log` **确实会展开** data function —— 原版自己就在用：",
                        f"{tab * 3}#      `common/on_actions/00_code_on_actions.txt:854` 的",
                        f'{tab * 3}#      `debug_log = "[TimeKeeper.GetCurrentDate.GetString]: … [THIS.GetCountry.Get…"`，',
                        f"{tab * 3}#      与这里**同一条作用域链**（`THIS.GetCountry.…`）；",
                        f"{tab * 3}#   ③ 标识符在 exe 里（`v3 evidence --exe-grep GetGovernmentLegitimacy`）。",
                        f"{tab * 3}# 为什么必须换成数字：夹逼读数**量不出档内的变化**，而 tr_defeat 那一局",
                        f"{tab * 3}# 的归因（backlog B88）问的正是「我们的压力有没有把合法性抬起来一点」——",
                        f"{tab * 3}# 卡在 b55 那一档里，抬 1 分和抬 5 分在旧读数里长得一模一样。",
                        f"{tab * 3}# ⚠️ 记**两条**：`LEGV` 不带格式指令（不依赖 `|v` 被认），",
                        f"{tab * 3}#    `LEGF` 带 `|v`（原版验证过的写法）。分析器优先用能解析出来的那条 ——",
                        f"{tab * 3}#    一次实机是分钟级代价，为「格式指令在 debug_log 里认不认」省两行日志不值得。",
                        (
                            f'{tab * 3}debug_log = "ZZPROBE AB;LEGV;'
                            f"[THIS.GetCountry.GetGovernmentLegitimacy];"
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        (
                            f'{tab * 3}debug_log = "ZZPROBE AB;LEGF;'
                            f"[THIS.GetCountry.GetGovernmentLegitimacy|v];"
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        "",
                        f"{tab * 3}# 同一件事对**各 IG 的政治力量**再来一遍：取 IG 的访问器见",
                        f"{tab * 3}# `cohesion_levels_l_english.yml:39` 的 `GetInterestGroupOfType('ig_…')`，",
                        f"{tab * 3}# 数值写法见 `customized_tooltips_l_english.yml:392` 的 `[InterestGroup.GetClout|%1]`。",
                        f"{tab * 3}# 同样记两条：`CLOUTV` 不带格式（拿到的是原始值，最好解析），",
                        f"{tab * 3}# `CLOUTP` 带 `%1`（原版写法）。旧的 `CLOUT;<档>` 保留：老归档只有它。",
                        *(
                            f'{tab * 3}debug_log = "ZZPROBE AB;CLOUTV;{short};'
                            f"[THIS.GetCountry.GetInterestGroupOfType('{name}').GetClout];"
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                            for name, short in CLOUT_IGS
                        ),
                        *(
                            f'{tab * 3}debug_log = "ZZPROBE AB;CLOUTP;{short};'
                            f"[THIS.GetCountry.GetInterestGroupOfType('{name}').GetClout|%1];"
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                            for name, short in CLOUT_IGS
                        ),
                        "",
                        f"{tab * 3}# 行为层①：改革窗口开没开",
                        f"{tab * 3}if = {{",
                        f"{tab * 4}limit = {{ has_journal_entry = {target.journal_entry} }}",
                        (
                            f'{tab * 4}debug_log = "ZZPROBE AB;JE;active;'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        f"{tab * 3}}}",
                        f"{tab * 3}else = {{",
                        (
                            f'{tab * 4}debug_log = "ZZPROBE AB;JE;inactive;'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        f"{tab * 3}}}",
                        "",
                        f"{tab * 3}# 行为层②：当前生效的改革相关法律",
                        laws,
                        f"{tab * 3}else = {{",
                        (
                            f'{tab * 4}debug_log = "ZZPROBE AB;LAW;none;'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        f"{tab * 3}}}",
                    ]
                )
            )
        ]
    )
    return (
        f"{GEN_HEADER}"
        f"# 触发与自报（**纯新增字段**，不覆盖原版任何字段）。\n"
        f"#\n"
        f"# ⚠️ `on_actions = {{ … }}` 只认 on_action 定义：把 `zz_probe_ab_monthly` 定义到效果文件里\n"
        f"#    会得到 `No on_action scripted with tag … cannot link`，钩子静默失效（阶段 2 踩过）。\n"
        f"# ⚠️ 自报格式：分隔符只能用 `;`（`|` 会被 loc 解析器当控制符刷 Data error），\n"
        f"#    国名只能用 `[THIS.GetCountry.GetNameNoFormatting]`（`[This.GetTag]` 不是合法命令）。\n"
        f"# ⚠️ 开局**不挂任何钩子**：阶梯的起点是「玩家点决议」那一刻 —— 挂 on_game_started 会\n"
        f"#    把大厅/读档阶段也算进 A 臂，A 的 12 个月就不再是 12 个月。\n"
        f"on_monthly_pulse_country = {{\n"
        f"{tab}on_actions = {{ zz_probe_ab_monthly }}\n"
        f"}}\n"
        f"\n"
        f"# root = 国家（每月只记俄罗斯；阶梯也在同一个守卫里走）\n"
        f"zz_probe_ab_monthly = {{\n"
        f"{tab}effect = {{\n"
        f"{tab * 2}# 诊断：这一局玩家是谁 —— 开的国家不对时，开局一分钟就能看出来\n"
        f"{tab * 2}if = {{\n"
        f"{tab * 3}limit = {{ is_player = yes }}\n"
        f'{tab * 3}debug_log = "ZZPROBE AB;PLAYER;yes;[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"{tab * 2}}}\n"
        f"\n"
        f"{behaviour}\n"
        f"\n"
        f"{tab * 2}# 策略层：三槽落点（同一个守卫，不给全世界刷日志）\n"
        f"{guarded(chains)}\n"
        f"{tab}}}\n"
        f"}}\n"
    )


def decisions_text(target: ProbeTarget) -> str:
    """**一个**决议：点一次就把整条阶梯武装起来。

    从前是两个对称的决议（点哪个进哪一组）。改成一个之后，"一次启动"就能拿到
    A→B→B2 三段读数 —— 少开一局，也少一个"两局之间世界已经漂了"的噪声源。
    """
    return (
        f"{GEN_HEADER}"
        f"# 统一起点：**只点一个**。点它 = 武装阶梯（第 1–12 月 A、第 13 月起 B、第 37 月起 B2）。\n"
        f"# 再点一次 = 清零重跑（同一存档里重来一遍，不必退回主菜单）。\n"
        f"zzprobe_ab_apply = {{\n"
        f"\t# 对任何玩家可见：玩家要演**旁观者**，让俄罗斯保持 AI 控制\n"
        f"\tis_shown = {{ always = yes }}\n"
        f"\tpossible = {{ always = yes }}\n"
        f"\twhen_taken = {{ c:{target.subject} ?= {{ zz_probe_ab_arm = yes }} }}\n"
        f"\tai_chance = {{ value = 0 }}\n"
        f"}}\n"
    )


def supported_game_version() -> str:
    """探针声明的游戏版本 —— 与legacy 档案 mod **同源**（`mod/data/*.toml` 的 `game_version`）。

    ⚠️ 这里原来是写死的 `"1.14.3"`（2026-09-23 修）：探针是挂在legacy 档案 mod 旁边一起加载的，
    两边声明的版本不一致时启动器会对**探针**弹一次版本警告，看起来像"探针坏了"；
    而"mod 声明哪个版本"的唯一来源是数据源（`modgen` 强制各档案一致），
    读它才不会在下一次官方更新时又漏掉一处。
    """
    from . import modgen  # noqa: PLC0415  -- 避免 import 期把 modgen 的依赖链拉进来

    archives = modgen.load_all()
    if not archives:
        # P13：读不到就说读不到，不猜一个版本号（猜出来的值会静默写进 metadata）。
        raise RuntimeError(
            "读不到任何档案数据源（mod/data/*.toml）—— 探针的 supported_game_version "
            "与legacy 档案 mod 同源，不能猜"
        )
    return archives[0].game_version


def metadata_text() -> str:
    """探针 mod 的 metadata。"""
    arms = "→".join(step.role for step in LADDER)
    return (
        json.dumps(
            {
                "name": "ZZ Probe AB",
                "id": "",
                "version": "3.0",
                "supported_game_version": supported_game_version(),
                "short_description": (
                    f"阶段 3 A/B 探针：点一次决议武装臂阶梯（{arms}），"
                    f"第 {ARM_START['B']} 月自动施加冲击、第 {ARM_START['B2']} 月自动追加改革侧输入"
                ),
                "tags": [],
                "relationships": [],
                "game_custom_data": {"multiplayer_synchronized": False},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def loc_text() -> str:
    """决议文案（中文）。"""
    return (
        "l_simp_chinese:\n"
        ' zzprobe_ab_apply:0 "【AB 实验】武装臂阶梯（A→B→B2）"\n'
        ' zzprobe_ab_apply_desc:0 "点它之后不要做任何操作，最高速跑 5-6 年。第 1-12 月是对照'
        "（什么都不做）；第 13 月自动施加战败冲击；第 37 月自动追加改革侧输入。跑完由外部脚本"
        '收工与归档。"\n'
    )


def loc_text_en() -> str:
    """决议文案（英文）。"""
    return (
        "l_english:\n"
        ' zzprobe_ab_apply:0 "[AB probe] Arm the ladder (A to B to B2)"\n'
        ' zzprobe_ab_apply_desc:0 "Click once, then do nothing and run 5-6 years at max speed. '
        "Months 1-12 are the control; the defeat shock lands automatically in month 13 and the "
        'reform-side inputs in month 37."\n'
    )


def suite_text(target: ProbeTarget) -> str:
    """引擎侧判定套件：**是否开窗 / 是否换法** 两条判据。

    为什么要有它（除了 `v3 ab`）：`v3 ab` 是**事后**读日志，套件是**引擎每天自己判** ——
    两条路互相独立，判据同源（P9）但实现不共享，任何一条出问题都还有另一条。

    口径（照游戏目录里的 `scripted_tests.md`）：

    * `success` / `fail` 都是**每天检查**的触发器，`success` 先判；两者同日命中时 fail 被忽略；
    * 到了 `last_date` 而两个都没命中 → 判「跳过」（不是失败），
      所以 `fail` 的日期必须**早于** `last_date`，否则"没发生"永远不报；
    * `run_count = 1`：一次实验只判一次。
    """

    if target.reform_law:
        law_changed = (
            f"{TAB}law_changed = {{\n"
            f"{TAB * 2}acceptable_fail_rate = 0.0\n"
            f"{TAB * 2}run_count = 1\n"
            f"{TAB * 2}# 成功 = {target.reform_law} 已经不是现行法律"
            f"（行为层②：真的换了法，不只是开了个窗）。\n"
            f"{TAB * 2}success = {{\n"
            f"{TAB * 3}c:{target.subject} ?= "
            f"{{ NOT = {{ has_law = law_type:{target.reform_law} }} }}\n"
            f"{TAB * 2}}}\n"
            f"{TAB * 2}fail = {{\n"
            f'{TAB * 3}game_date > "1841.1.1"\n'
            f"{TAB * 2}}}\n"
            f"{TAB}}}\n"
        )
    else:
        # **不产出**那条判据（B80）：没有查实的法就不能判 —— 写死 `law_serfdom` 会让
        # "不是农奴制"对奥斯曼/埃及这类国家**立刻为真**，报出一个假的"法律换了"。
        law_changed = (
            f"{TAB}# ⚠️ 本档案**没有**声明 `[probe].reform_law`（没查实该盯哪条法）⇒\n"
            f"{TAB}#    「法律是否换过」这一条**不判**：宁可少一条读数，也不给一条会假的。\n"
            f'{TAB}#    要加它：在该档案的数据源里写 `[probe] reform_law = "law_…"` + why。\n'
        )

    return (
        f"{GEN_HEADER}"
        f"# 阶段 3 的引擎侧判定套件（H2：真实冲击 → AI 行为层差分）。\n"
        f"#\n"
        f"# 结构见游戏目录的 tools/scripted_tests/scripted_tests.md：last_date = 这一套跑多久；\n"
        f"# tests.<名字> = {{ success / fail / run_count }}，两个触发器**每天**检查，success 先判，\n"
        f"# 到 last_date 都没命中则判「跳过」（所以 fail 的日期必须早于 last_date）。\n"
        f"#\n"
        f"# 判据与 `pdx.ab` 同源：主指标 = 改革窗口；次指标 = 法律是否换过（**该档案查实了才判**，见下）。\n"
        f"# 日期口径：阶梯第 {ARM_START['B2']} 月（≈1839.1）才追加改革侧输入，给 2 年余量 →\n"
        f"# fail 定在开局后第 61 个月（1841.1.1），last_date 再多半年。\n"
        f"\n"
        f'last_date = "1841.6.1"\n'
        f"\n"
        f"tests = {{\n"
        f"{TAB}reform_window_opens = {{\n"
        f"{TAB * 2}acceptable_fail_rate = 0.0\n"
        f"{TAB * 2}run_count = 1\n"
        f"{TAB * 2}# 成功 = 改革窗口开过（行为层①）。\n"
        f"{TAB * 2}success = {{\n"
        f"{TAB * 3}c:{target.subject} ?= {{ has_journal_entry = {target.journal_entry} }}\n"
        f"{TAB * 2}}}\n"
        f"{TAB * 2}# 失败 = 到日期仍未开窗（不是「跳过」：跳过会让整件事悄悄过去）。\n"
        f"{TAB * 2}fail = {{\n"
        f'{TAB * 3}game_date > "1841.1.1"\n'
        f"{TAB * 2}}}\n"
        f"{TAB}}}\n"
        f"\n"
        f"{law_changed}"
        f"}}\n"
    )


def converge_text(name: str) -> str:
    """把一个原版套件压成"立即收敛"（否则它会跑到 1870–1900 年）。"""
    return (
        f"{GEN_HEADER}"
        f"# 原版 {name}.txt 的收敛覆盖：把 last_date 拉到开局几天内 + 清空 tests。\n"
        f"# 为什么必须覆盖：引擎会跑 tools/scripted_tests/ 下的**每一份**套件，\n"
        f"# 只要还有一份在跑，-scripted_tests 这一局就不会收工，\n"
        f"# 「跑到第 N 月就杀进程」的自动化会一直被拖住。\n"
        f"# ⚠️ 不改游戏安装目录：mod 提供的套件会被读到（阶段 3 实测，见 exec/阶段3-归档清点.md §三）。\n"
        f"\n"
        f'last_date = "{CONVERGE_DATE}"\n'
        f"\n"
        f"tests = {{\n"
        f"}}\n"
    )


@dataclass(frozen=True, slots=True)
class Built:
    """一次 build 的产物：相对路径 → 文本。"""

    files: dict[str, str]
    #: 这次 build 用的模式（:data:`MODE_NATURAL` / :data:`MODE_CONTROL`）—— 摘要里要看得见。
    mode: str = MODE_NATURAL

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self.files))


#: **只有 `control` 模式才有**的文件（切回 `natural` 时必须删掉）。
#:
#: 为什么单独列出来删：`write()` 只写本次 build 的文件、**不扫目录**，于是上一局留下的
#: defines 覆盖与哨兵牌会**静默**留在盘上、并随下一局一起装进游戏 ——
#: 那意味着"自然局"其实带着每周重抽的节奏，而读数里看不出来（`h1_probe` 的同族用例
#: `test_natural会删掉storm留下的defines` 说的就是这件事）。
MODE_ONLY_FILES: tuple[str, ...] = (
    "common/defines/zz_probe_ab_defines.txt",
    "common/ai_strategies/zz_probe_ab_sentinel_open.txt",
    "common/ai_strategies/zz_probe_ab_sentinel_gate.txt",
)


def build(
    *,
    game: Path | None = None,
    target: ProbeTarget | None = None,
    own: list[str] | None = None,
    mode: str | None = None,
) -> Built:
    """生成探针的全部文件（相对探针根目录）。

    ``target`` 缺省时从**数据源**读（:func:`load_target`）—— 读不到就报错（P13），
    不拿一个猜出来的国家名生成探针。测试要造"别的国家"的探针时显式传一个。
    ``own`` 是我们自己的政治槽牌名（缺省现读盘上产物，见 :func:`own_cards`）。
    ``mode=None`` = 读 :func:`active_mode`（环境变量 `V3_AB_MODE`，默认 `natural`）；
    测试与库调用方可以显式传值，于是**不必**碰进程环境。

    ⚠️ 生成前先过 :func:`require_difficulty_match`：探针写死的三档设置名与legacy 档案 mod 产物对不上
    就是「每月只写 `RULE;none;yes`」的静默失真（t90 那族）⇒ 当场报错，不生成。
    """
    chosen_mode = active_mode() if mode is None else mode
    if chosen_mode not in MODES:
        raise ValueError(f"未知模式：{chosen_mode!r}（可选：{'、'.join(MODES)}）")
    require_difficulty_match()
    chosen = target or load_target()
    if chosen is None:
        raise RuntimeError(
            "读不到任何档案数据源（mod/data/*.toml）—— 探针要盯哪个国家、哪个 JE、"
            "哪个效果，全部来自那里。不能猜一个国家名生成探针。"
        )
    vanilla = ai_surface.read_cards(game)
    files = {
        "common/scripted_effects/zz_probe_ab_effects.txt": effects_text(chosen, mode=chosen_mode),
        "common/on_actions/zz_probe_ab_on_actions.txt": on_actions_text(
            vanilla, chosen, own=own, mode=chosen_mode
        ),
        "common/decisions/zz_probe_ab_decisions.txt": decisions_text(chosen),
        SUITE_REL: suite_text(chosen),
        ".metadata/metadata.json": metadata_text(),
        "localization/simp_chinese/zz_probe_ab_l_simp_chinese.yml": loc_text(),
        "localization/english/zz_probe_ab_l_english.yml": loc_text_en(),
    }
    files.update(
        {f"tools/scripted_tests/{name}.txt": converge_text(name) for name in VANILLA_SUITES}
    )
    if chosen_mode == MODE_CONTROL:
        if not chosen.pressure_modifier:
            raise RuntimeError(
                f"control 模式要求档案 {chosen.archive_id!r} 声明 [pressure].name —— "
                "门名读不到就不生成（否则这份探针的门永远为假、实验会静默变成什么都没测）"
            )
        files.update(sentinel_files(chosen.pressure_modifier))
        files["common/defines/zz_probe_ab_defines.txt"] = defines_text()
    return Built(files=files, mode=chosen_mode)


def write(
    *,
    root: Path | None = None,
    game: Path | None = None,
    archive_id: str | None = None,
    mode: str | None = None,
) -> list[Path]:
    """写入无 BOM 的仓库探针目录；安装由 deploy_tree 添加游戏 BOM。"""
    base = root or PROBE_DIR
    # `archive_id=None` = 数据源里的第一份（`load_target` 的默认口径）。
    built = build(game=game, target=load_target(archive_id), mode=mode)
    for rel in MODE_ONLY_FILES:
        if rel in built.files:
            continue
        stale = base / rel
        if stale.is_file():
            stale.unlink()
    written: list[Path] = []
    for rel, text in sorted(built.files.items()):
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8"  # 仓库无 BOM，deploy_tree 为安装副本添加。
        path.write_text(text, encoding=encoding, newline="\n")
        written.append(path)
    return written


def deploy(
    *,
    root: Path | None = None,
    target: Path | None = None,
    game: Path | None = None,
    archive_id: str | None = None,
    mode: str | None = None,
) -> Path:
    """生成 → 同步进用户 mod 目录 → 连同legacy 档案 mod 一起启用。

    ``archive_id`` 选**盯哪一份档案**（阶段 5 起有多份；不给就是数据源里的第一份）。
    ``mode`` 透传给 :func:`write`（``None`` = 读 :func:`active_mode`）。
    """
    write(root=root, game=game, archive_id=archive_id, mode=mode)
    chosen = load_target(archive_id)
    source = root or PROBE_DIR
    dest_root = target or experiments.TARGET_DIR
    dest = dest_root / PROBE_MOD
    if dest.exists():
        shutil.rmtree(dest)
    deploy_tree(source, dest)
    # legacy 档案 mod 也要装：探针的效果引用档案里的冲击 / 改革侧输入效果，没装就是 Unknown effect。
    # 目录名由**档案 id**拼出来（与 `mod/legacy/.metadata` 的 id 同源，P9）——
    # 从前这里写死 `sitai_ru_defeat`，加第二份档案时就会装错目录。
    product = config.REPO / "mod" / "legacy"
    mod = dest_root / (chosen.dir_name if chosen is not None else MOD_DIR_NAME)
    if product.is_dir():
        if mod.exists():
            shutil.rmtree(mod)
        deploy_tree(product, mod)
    paths = [dest, mod] if mod.is_dir() else [dest]
    experiments.set_enabled_mods(paths)
    return dest


#: 自报行的形状（与 `pdx.ab` 的 `REPORT_RE` 同源）：`ZZPROBE AB;<KIND>;<取值>;<国名>`。
#: kind 只能是大写字母，取值位里可以带牌名（`<完整牌名>=yes`）。
REPORT_RE = re.compile(r"ZZPROBE AB;(?P<kind>[A-Z]+);(?P<value>.*?);(?P<country>[^;]*)\s*$")


@dataclass(frozen=True, slots=True)
class Row:
    """一行自报。"""

    kind: str
    value: str
    country: str


@dataclass(slots=True)
class Sample:
    """一个月（一个 `ROLE` 块）里读数侧要的那几样东西。

    **可变**（不是 frozen）：`samples_of` 是一行一行把读数**填进**去的。
    """

    index: int
    #: 门直读（`GATE`）：`yes` / `no` / 空 = 这一局压根没有门读数（老探针）。
    gate: str
    #: 每张牌被持有的情况（`HELD` / `SENT`）：完整牌名 → `yes` / `no`。
    held: dict[str, str]
    #: 这一局的模式与节奏（`MODE` / `STORM`）：老探针没有这两行 ⇒ 空。
    mode: str
    storm: str


def parse_rows(text: str) -> tuple[Row, ...]:
    """把一份日志/留档文本里的自报行解析出来（**只认形状**，不解释语义）。"""
    rows: list[Row] = []
    for line in text.splitlines():
        match = REPORT_RE.search(line)
        if match is not None:
            rows.append(
                Row(
                    kind=match.group("kind"),
                    value=match.group("value"),
                    country=match.group("country"),
                )
            )
    return tuple(rows)


def samples_of(rows: Sequence[Row]) -> tuple[Sample, ...]:
    """按 `ROLE` 行分月（与生成器的月度块头一致）。第一行 `ROLE` 之前的内容丢掉。"""
    samples: list[Sample] = []
    current: Sample | None = None
    for row in rows:
        if row.kind == "ROLE":
            current = Sample(index=len(samples) + 1, gate="", held={}, mode="", storm="")
            samples.append(current)
            continue
        if current is None:
            continue
        if row.kind == "GATE":
            current.gate = row.value
        elif row.kind in ("HELD", "SENT"):
            name, _, value = row.value.partition("=")
            if name:
                current.held[name] = value
        elif row.kind == "MODE":
            current.mode = row.value
        elif row.kind == "STORM":
            current.storm = row.value
    return tuple(samples)


#: 每条判决的**理由**与**下一步**（判红必须说清"红在哪、下一步查什么"，不许只给一个词）。
_STATUS_NOTES: dict[str, tuple[str, ...]] = {
    "pass_appeared": ("理由：该牌在观测期里至少被持有过一个月。",),
    "pass_absent": ("理由：期望就是「不该出现」，观测期里一次都没出现。",),
    "red_gate_open_no_hits": (
        "理由：门直读为「开」而这张牌一次都没被持有 ⇒ 不是「门没开」，剩下的解释是",
        "「它进不了政治槽」（候选集 / 门的求值 / 产物没被加载）—— 报队长，不许写成「设计失败」。",
    ),
    "red_gate_closed_no_hits": (
        "理由：应出现而 0 次，**且门直读一次都没开** ⇒ 这一局没做成我们要做的实验",
        "（门没开就是没测到），读数不可判 ⇒ 判红，不许当成「牌进不了池」的证据。",
    ),
    "red_no_gate_reading": (
        "理由：这份读数里**没有 `GATE` 行**（老探针，或探针没跑起来）⇒「门开没开」无从知道，",
        "而不知道就等于不能判 ⇒ 判红并要求重跑（t18 B 臂 0/13 不可归因的根因就是它）。",
    ),
    "red_no_card_reading": (
        "理由：这份读数里**没有这张牌的 `HELD`/`SENT` 行** ⇒ 它在生成物里就不存在",
        "（牌名写错，或探针没生成这一族读数）—— 判红，别把「没记」读成「没出现」。",
    ),
    "red_appeared_when_absent": (
        "理由：期望是「不该出现」而它出现了 ⇒ 门 / 权重 / 候选集里至少有一处与声明不符。",
    ),
    "red_mode_mismatch": ("理由：`MODE` 行与调用方要求的模式不一致（或整局没有 `MODE` 行）。",),
    "red_storm_mismatch": ("理由：`STORM` 行与调用方要求的节奏不一致（或整局没有 `STORM` 行）。",),
}


@dataclass(frozen=True, slots=True)
class CardVerdict:
    """一张牌的读数判决（t18 第 15 条：**读数侧必须能判红**，不许静默返回成功）。"""

    status: str
    card: str
    expect: str
    months: int
    gate_yes: int
    gate_no: int
    hits: int
    first_hit_month: int | None

    @property
    def ok(self) -> bool:
        return self.status.startswith("pass")

    def report(self) -> str:
        lines = [
            f"牌：{self.card}",
            f"期望：{self.expect}（appear = 应出现；absent = 不该出现）",
            f"观测月数：{self.months}　门直读：yes {self.gate_yes} 月 / no {self.gate_no} 月",
            f"命中：{self.hits} 月"
            + (f"（首次第 {self.first_hit_month} 月）" if self.first_hit_month else ""),
            f"判决：{self.status}　{'✅ 通过' if self.ok else '❌ 判红'}",
        ]
        return "\n".join([*lines, *_STATUS_NOTES.get(self.status, ())])


def _verdict_from_counts(
    *, expect: str, hits: int, gate_yes: int, gate_no: int, seen_card: bool
) -> str:
    """把四个计数折成判决（拆出来是为了让 `MODE` / `STORM` 的检查读起来不嵌套）。"""
    if not seen_card:
        return "red_no_card_reading"
    if expect == "appear":
        if hits:
            return "pass_appeared"
        if gate_yes == 0 and gate_no == 0:
            return "red_no_gate_reading"
        if gate_yes == 0:
            return "red_gate_closed_no_hits"
        return "red_gate_open_no_hits"
    if expect == "absent":
        return "red_appeared_when_absent" if hits else "pass_absent"
    raise ValueError(f"expect 只能是 appear / absent，收到 {expect!r}")


def card_verdict(
    rows: Sequence[Row],
    *,
    card: str,
    expect: str = "appear",
    expect_mode: str = "",
    expect_storm: str = "",
) -> CardVerdict:
    """对**一张牌**给判决（纯函数：输入是自报行，不碰文件、不碰游戏）。

    判红的四种情况（t18 第 15 条要的就是"必须出声"）：

    * **门直读为开而一次都没命中** ⇒ 那不是"门没开"，而是"进不了池"那一族（要报队长）；
    * **应出现而 0 次、且门一次都没开** ⇒ 这一局没做成实验，**不可判**（不许当证据）；
    * **没有 `GATE` 行 / 没有这张牌的 `HELD` 行** ⇒ "不知道"也算红（静默的反面就是它）；
    * **`MODE` / `STORM` 与要求不符** ⇒ 拿错局的读数说事。

    ``expect="absent"`` 是另一向（A 臂那种"不该出现"）。
    """
    samples = samples_of(rows)
    gate_yes = sum(1 for sample in samples if sample.gate == "yes")
    gate_no = sum(1 for sample in samples if sample.gate == "no")
    hit_months = [sample.index for sample in samples if sample.held.get(card) == "yes"]
    seen_card = any(card in sample.held for sample in samples)
    # ⚠️ **先查模式与节奏，再数命中**：读数来自哪一局比"命中几次"更靠前 ——
    # 拿自然局的读数去说控制局的事，是这一族读数最容易犯、也最难发现的错。
    status = ""
    if expect_mode:
        modes = {sample.mode for sample in samples if sample.mode}
        if not modes or expect_mode not in modes:
            status = "red_mode_mismatch"
    if not status and expect_storm:
        storms = {sample.storm for sample in samples if sample.storm}
        if not storms or expect_storm not in storms:
            status = "red_storm_mismatch"
    if not status:
        status = _verdict_from_counts(
            expect=expect,
            hits=len(hit_months),
            gate_yes=gate_yes,
            gate_no=gate_no,
            seen_card=seen_card,
        )
    return CardVerdict(
        status=status,
        card=card,
        expect=expect,
        months=len(samples),
        gate_yes=gate_yes,
        gate_no=gate_no,
        hits=len(hit_months),
        first_hit_month=hit_months[0] if hit_months else None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """读数入口：`python -m pdx.ab_probe --log <文件> --card <牌名>`（判红即非零退出）。

    为什么要有这个入口（t18 第 15 条）：这一族读数过去**只在人脑子里判** ——
    B 臂 0/13 在日志里躺了一整局，没有任何程序会叫。判红必须是一个**退出码**，
    这样脚本、CI、下一个跑局的人都能直接看见它。
    """
    parser = argparse.ArgumentParser(
        prog="python -m pdx.ab_probe",
        description="读一份探针自报（游戏 logs/debug.log 或留档副本），对一张牌给判决。",
    )
    parser.add_argument("--log", required=True, help="自报文本文件（整份日志即可）")
    parser.add_argument("--card", required=True, help="要判的牌**完整名**（ai_strategy_…）")
    parser.add_argument(
        "--expect",
        choices=("appear", "absent"),
        default="appear",
        help="appear = 应出现（判红的重点）；absent = 不该出现（A 臂那种）",
    )
    parser.add_argument(
        "--expect-mode", default="", help=f"要求的模式（{MODE_ENV} 取值），空 = 不查"
    )
    parser.add_argument(
        "--expect-storm", choices=("", "yes", "no"), default="", help="要求的节奏，空 = 不查"
    )
    args = parser.parse_args(argv)
    text = pathlib.Path(args.log).read_text(encoding="utf-8", errors="replace")
    verdict = card_verdict(
        parse_rows(text),
        card=args.card,
        expect=args.expect,
        expect_mode=args.expect_mode,
        expect_storm=args.expect_storm,
    )
    print(verdict.report())
    return 0 if verdict.ok else 1


def summary(built: Built) -> str:
    """给人看的构建摘要。"""
    arms = " → ".join(
        f"{step.role}（第 {step.at_month} 月起{'' if step.effect else '，什么都不做'}）"
        for step in LADDER
    )
    lines = [
        f"模式：{built.mode}（{MODE_ENV}）"
        + (
            "　⚠️ 控制局：不设记忆变量、门从第 1 月起挂上、含两张哨兵牌与 defines 覆盖"
            if built.mode == MODE_CONTROL
            else ""
        ),
        f"臂阶梯（点一次决议武装）：{arms}",
        f"难度三档（与legacy 档案 mod 产物同串）：{'、'.join(DIFFICULTY_SETTINGS)}",
        f"生成文件 {len(built.files)} 个：",
    ]
    lines += [f"  {rel}" for rel in built.paths]
    return "\n".join(lines)


__all__ = [
    "ARM_START",
    "CONVERGE_DATE",
    "DIFFICULTY_RULE_GLOB",
    "GEN_HEADER",
    "INPUT_EFFECT",
    "INPUT_MODIFIER",
    "LADDER",
    "LAWS",
    "MODES",
    "MODE_CONTROL",
    "MODE_ENV",
    "MODE_NATURAL",
    "MODE_ONLY_FILES",
    "MONTH_VAR",
    "PROBE_DIR",
    "PROBE_MOD",
    "REPORT_RE",
    "ROLES",
    "SENTINEL_GATE",
    "SENTINEL_GATE_MONTHS",
    "SENTINEL_GATE_VAR",
    "SENTINEL_OPEN",
    "SENTINEL_OPEN_MONTHS",
    "SENTINEL_OPEN_VAR",
    "SENTINEL_WEIGHT",
    "SHOCK_EFFECT",
    "SHOCK_VAR",
    "STAGE_VAR",
    "SUBJECT",
    "SUITE_REL",
    "VANILLA_SUITES",
    "ArmStep",
    "Built",
    "CardVerdict",
    "DifficultyCheck",
    "Row",
    "Sample",
    "active_mode",
    "build",
    "card_verdict",
    "converge_text",
    "decisions_text",
    "defines_text",
    "deploy",
    "difficulty_check",
    "effects_text",
    "ladder_for",
    "loc_text",
    "loc_text_en",
    "main",
    "metadata_text",
    "mod_difficulty_settings",
    "on_actions_text",
    "parse_rows",
    "require_difficulty_match",
    "samples_of",
    "sentinel_card_text",
    "sentinel_files",
    "suite_text",
    "summary",
    "write",
]

if __name__ == "__main__":  # pragma: no cover - 手工运行入口（判红靠它的退出码）
    raise SystemExit(main())
