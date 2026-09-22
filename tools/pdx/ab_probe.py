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
`B`     第 13–36 月  调用真 mod 的 `sitai_ru_defeat_shock`（冲击）
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

import json
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import ai_surface, config, experiments, h1_probe
from pdx.h1 import SLOT_SHORT, SLOTS

if TYPE_CHECKING:
    from pathlib import Path

#: 探针 mod 目录名。
PROBE_MOD = "zz_probe_ab"

#: 真 mod 安装到用户 mod 目录时的目录名（与 `mod/.metadata/metadata.json` 的 id 同源）。
MOD_DIR_NAME = "sitai_ru_defeat"

#: 探针源目录（仓库内，可审阅）。
PROBE_DIR = config.REPO / "tools" / "probe" / PROBE_MOD

#: 真 mod 的冲击效果（由 `mod/common/scripted_effects/sitai_ru_defeat_effects.txt` 生成）。
SHOCK_EFFECT = "sitai_ru_defeat_shock"

#: 真 mod 的**改革侧输入**效果与修正（同源文件；闸门 ② 保证它们真实存在）。
INPUT_EFFECT = "sitai_ru_reform_input"
INPUT_MODIFIER = "sitai_ru_reform_inputs"

#: 主角国家（阶段 3：俄罗斯单国）。
SUBJECT = "RUS"

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


#: 臂阶梯（**唯一的定义处**：探针文本、分析器的角色表、文档都从这里派生）。
LADDER: tuple[ArmStep, ...] = (
    ArmStep("A", 1, None, "对照组：什么都不做"),
    ArmStep("B", 13, SHOCK_EFFECT, "处理①：战败冲击（变量 + 压力修正）"),
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

#: 每个月的自报里"冲击在不在"用的判据（真 mod 写的变量）。
SHOCK_VAR = "sitai_ru_defeat_memory"

#: 每个月要记的法律（改革相关；都是原版存在的 law_type）。
LAWS = (
    "law_serfdom",
    "law_autocracy",
    "law_wealth_voting",
    "law_censorship",
    "law_peasant_levies",
    "law_traditionalism",
)

#: 每个月要记的**政治策略牌**（`has_strategy`）—— 阶段 3 重做新增的一格。
#:
#: 为什么必须记它：阶段 3 的负结果（牌换了名、法一条没改）里，"牌到底换成了哪一张"
#: 只是从探针的三槽自报里**推断**出来的，没有一条**逐月**的读数；而 B53（backlog）
#: 指出牌才是"动不动手"的闸门（`change_law_chance`：反动 3.5 / 保守 2.5 / 进步 10）。
#: 所以这次把牌当**行为层的直接读数**记，而不是从别的行反推。
POLITICAL_STRATEGIES = (
    "ai_strategy_progressive_agenda",
    "ai_strategy_conservative_agenda",
    "ai_strategy_reactionary_agenda",
)

#: 自励阶梯：**不点决议**，由月度脉冲按 `is_ai` 自动武装 —— 观察者局没有玩家国家，
#: 决议点不了（阶段 3 的结构性阻断，见 `阶段3-结果.md` §六）。
#:
#: `(月, 说明, 要调的效果名)`。月份与 `LADDER` 的臂起点**对齐**：第 13 月施加冲击（B 臂）、
#: 第 37 月追加改革侧输入（B2 臂）。
#:
#: ⚠️ 这里**刻意不递牌**：递牌是**真 mod 的 JE 自己的事**（`[journal_entry.signals]`，
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

#: 「**立法开没开**」要盯的法（2026-09-22 新增的 `ENACT` 读数）。
#:
#: 为什么必须有这一行：阶段 3 重做的实机结果是"牌换了、法不动"，而三个候选
#: （政府支持不足 / 怕革命 / 权重不够）在"每月只记法律名"的读数下**长得一模一样**。
#: `is_enacting_law` 是引擎触发器（真在推这条法时为真），它把
#: **从未开立法** 与 **开了没成** 分开 —— 前者指向"AI 不肯动手"，后者指向"立法过程"。
#:
#: ⚠️ **没有「任意法」的通用写法**（实测）：`is_enacting_law` 一定要 `law_type:` 操作数。
#: exe 里检索 `is_enacting_any_law` / `has_any_enactment` / `any_enacting_law` /
#: `enactment_progress` / `current_enactment` **全部 0 命中**（`is_enacting_law` 本身 2 命中）。
#: ⇒ 想回答"它到底在推哪条法"，只能**逐条问**。
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
GEN_HEADER = "# ⚠️ 本文件由 `v3 ab-probe` 生成（tools/pdx/ab_probe.py）—— 改这里没用，改生成器。\n"

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


def effects_text() -> str:
    """三个效果：武装阶梯、月度走一格、以及（决议用的）重新武装。

    角色仍然不是"装哪个探针"决定的 —— 但也不再是"点哪个决议"：**点一次就够**，
    之后由阶梯自己按月份换臂（这正是"一次点击换整条阶梯的数据"）。
    """
    arms: list[str] = []
    for index, step in enumerate(LADDER[1:], start=1):
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
        for index, (month, note, effect) in enumerate(SELFARM, start=1)
    )
    return (
        f"{GEN_HEADER}"
        f"# ⚠️ **本文件里只能有裸效果列表**（scripted_effects 的语法）：写成 on_action 那种\n"
        f"#    `effect = {{ … }}` 包装会被引擎读成「调一个叫 effect 的效果」→\n"
        f"#    `Unknown effect effect`，整个定义作废而 on_action 那头只报\n"
        f"#    `No on_action scripted with tag … cannot link`（阶段 2 实测：分组一次没跑、\n"
        f"#    白跑一整局）。钩子/包装在 `zz_probe_ab_on_actions.txt` 里。\n"
        f"#\n"
        f"# ① `zz_probe_ab_arm`：**点一次决议**武装整条阶梯（由决议调用，作用于俄罗斯）。\n"
        f"#    可重复调用 —— 每点一次就把月份与阶段清零重跑（同一存档里重跑一局的做法）。\n"
        f"# ② `zz_probe_ab_selfarm`：**不点决议**的武装路径（`is_ai = yes` 时按月份自动走）。\n"
        f"#    为什么必须有它：观察者局**没有玩家国家**，决议永远点不到 —— 阶段 3 的臂阶梯\n"
        f"#    一次都没跑起来就是这个原因（`阶段3-结果.md` §六）。它只认 `is_ai`，\n"
        f"#    所以玩家自己掌权时不会抢手（玩家局仍走决议那条路）。\n"
        f"# ③ `zz_probe_ab_ladder`：每月走一格。**幂等**是硬要求：`{STAGE_VAR}` 单调递增，\n"
        f"#    每个效果只施加一次；不拿「有没有那个修正」当判据（会被别的系统碰到）。\n"
        f"# ④ `{SHOCK_EFFECT}` / `{INPUT_EFFECT}` 在**真 mod**里（`v3 modgen` 生成），\n"
        f"#    探针只调用它们 —— 这样实验用的世界状态与档案本身是同一份定义。\n"
        f"zz_probe_ab_arm = {{\n"
        f'{TAB}debug_log = "ZZPROBE AB;RUN;A"\n'
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


def on_actions_text(vanilla: list[ai_surface.Card]) -> str:
    """开局不挂任何东西；每月先自励、再走一格阶梯，最后**只记主角国家**。"""
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
    strategies = "\n".join(
        f"{tab * 3}{keyword} = {{\n"
        f"{tab * 4}limit = {{ has_strategy = {name} }}\n"
        f'{tab * 4}debug_log = "ZZPROBE AB;STRATEGY;{name};'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"{tab * 3}}}"
        for keyword, name in zip(
            ["if", *["else_if"] * (len(POLITICAL_STRATEGIES) - 1)],
            POLITICAL_STRATEGIES,
            strict=True,
        )
    )
    # ⚠️ **不做整体 re-indent**（2026-09-22 修）：这里以前写成
    # `.replace("\n" + tab * 2, "\n" + tab * 3)`，把三槽自报链的缩进整体右移一格。
    # 结果是嵌套块（`if` 里的 `if`）被移成**双倍缩进**，读起来像语法错误。
    # PDX 脚本对缩进不敏感，所以那不是 bug，但它把生成物变成了"不敢读"的东西。
    # 正确做法：只给**这一层的块定界行**加缩进，块里的内容交给它自己的生成器。
    chains = _slot_chains(vanilla)

    def guarded(body: str) -> str:
        """把一段自报包进「只记主角国家」的守卫里。"""
        return f"{tab * 2}if = {{\n{tab * 3}limit = {{ c:{SUBJECT} ?= this }}\n{body}\n{tab * 2}}}"

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

    behaviour = "\n".join(
        [
            guarded(
                "\n".join(
                    [
                        (
                            f'{tab * 3}debug_log = "ZZPROBE AB;ROLE;{SUBJECT};'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
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
                        f"{tab * 3}# ③ 两处输入到底有没有落到这个国家身上（自检用）",
                        state_line("SHOCK", f"has_variable = {SHOCK_VAR}", "yes", "no"),
                        "",
                        state_line("INPUT", f"has_modifier = {INPUT_MODIFIER}", "yes", "no"),
                        "",
                        f"{tab * 3}# ④ 当前挂着的政治牌（策略层读数；B53：牌才是闸门）",
                        strategies,
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
                                        f'{clout_band_name(band)};'
                                        f'[THIS.GetCountry.GetNameNoFormatting]"'
                                    ),
                                    f"{tab * 3}}}",
                                ]
                            )
                            for name, short in CLOUT_IGS
                            for band in CLOUT_BANDS
                        ),
                        "",
                        f"{tab * 3}# 诊断：合法性落在哪一档（五档夹逼 b55/b60/b70/b75/b80；",
                        f"{tab * 3}# 不记数字：没有已证可用的 loc 命令能打印一个数）",
                        f"{tab * 3}if = {{",
                        f"{tab * 4}limit = {{ legitimacy <= 55 }}",
                        (
                            f'{tab * 4}debug_log = "ZZPROBE AB;LEG;b55;'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        f"{tab * 3}}}",
                        f"{tab * 3}else_if = {{",
                        f"{tab * 4}limit = {{ legitimacy <= 60 }}",
                        (
                            f'{tab * 4}debug_log = "ZZPROBE AB;LEG;b60;'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        f"{tab * 3}}}",
                        f"{tab * 3}else_if = {{",
                        f"{tab * 4}limit = {{ legitimacy <= 70 }}",
                        (
                            f'{tab * 4}debug_log = "ZZPROBE AB;LEG;b70;'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        f"{tab * 3}}}",
                        f"{tab * 3}else_if = {{",
                        f"{tab * 4}limit = {{ legitimacy <= 75 }}",
                        (
                            f'{tab * 4}debug_log = "ZZPROBE AB;LEG;b75;'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        f"{tab * 3}}}",
                        f"{tab * 3}else = {{",
                        (
                            f'{tab * 4}debug_log = "ZZPROBE AB;LEG;b80;'
                            f'[THIS.GetCountry.GetNameNoFormatting]"'
                        ),
                        f"{tab * 3}}}",
                        "",
                        f"{tab * 3}# 行为层①：改革窗口开没开",
                        f"{tab * 3}if = {{",
                        f"{tab * 4}limit = {{ has_journal_entry = je_sitai_ru_reform_window }}",
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


def decisions_text() -> str:
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
        f"\twhen_taken = {{ c:{SUBJECT} ?= {{ zz_probe_ab_arm = yes }} }}\n"
        f"\tai_chance = {{ value = 0 }}\n"
        f"}}\n"
    )


def metadata_text() -> str:
    """探针 mod 的 metadata。"""
    arms = "→".join(step.role for step in LADDER)
    return (
        json.dumps(
            {
                "name": "ZZ Probe AB",
                "id": "",
                "version": "3.0",
                "supported_game_version": "1.14.3",
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


def suite_text() -> str:
    """引擎侧判定套件：**是否开窗 / 是否换法** 两条判据。

    为什么要有它（除了 `v3 ab`）：`v3 ab` 是**事后**读日志，套件是**引擎每天自己判** ——
    两条路互相独立，判据同源（P9）但实现不共享，任何一条出问题都还有另一条。

    口径（照游戏目录里的 `scripted_tests.md`）：

    * `success` / `fail` 都是**每天检查**的触发器，`success` 先判；两者同日命中时 fail 被忽略；
    * 到了 `last_date` 而两个都没命中 → 判「跳过」（不是失败），
      所以 `fail` 的日期必须**早于** `last_date`，否则"没发生"永远不报；
    * `run_count = 1`：一次实验只判一次。
    """

    return (
        f"{GEN_HEADER}"
        f"# 阶段 3 的引擎侧判定套件（H2：真实冲击 → AI 行为层差分）。\n"
        f"#\n"
        f"# 结构见游戏目录的 tools/scripted_tests/scripted_tests.md：last_date = 这一套跑多久；\n"
        f"# tests.<名字> = {{ success / fail / run_count }}，两个触发器**每天**检查，success 先判，\n"
        f"# 到 last_date 都没命中则判「跳过」（所以 fail 的日期必须早于 last_date）。\n"
        f"#\n"
        f"# 两条判据与 `pdx.ab` 同源：主指标 = 改革窗口；次指标 = 法律是否换过。\n"
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
        f"{TAB * 3}c:{SUBJECT} ?= {{ has_journal_entry = je_sitai_ru_reform_window }}\n"
        f"{TAB * 2}}}\n"
        f"{TAB * 2}# 失败 = 到日期仍未开窗（不是「跳过」：跳过会让整件事悄悄过去）。\n"
        f"{TAB * 2}fail = {{\n"
        f'{TAB * 3}game_date > "1841.1.1"\n'
        f"{TAB * 2}}}\n"
        f"{TAB}}}\n"
        f"\n"
        f"{TAB}law_changed = {{\n"
        f"{TAB * 2}acceptable_fail_rate = 0.0\n"
        f"{TAB * 2}run_count = 1\n"
        f"{TAB * 2}# 成功 = 农奴制已经不是现行法律（行为层②：真的换了法，不只是开了个窗）。\n"
        f"{TAB * 2}success = {{\n"
        f"{TAB * 3}c:{SUBJECT} ?= {{ NOT = {{ has_law = law_type:law_serfdom }} }}\n"
        f"{TAB * 2}}}\n"
        f"{TAB * 2}fail = {{\n"
        f'{TAB * 3}game_date > "1841.1.1"\n'
        f"{TAB * 2}}}\n"
        f"{TAB}}}\n"
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

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self.files))


def build(*, game: Path | None = None) -> Built:
    """生成探针的全部文件（相对探针根目录）。"""
    vanilla = ai_surface.read_cards(game)
    files = {
        "common/scripted_effects/zz_probe_ab_effects.txt": effects_text(),
        "common/on_actions/zz_probe_ab_on_actions.txt": on_actions_text(vanilla),
        "common/decisions/zz_probe_ab_decisions.txt": decisions_text(),
        SUITE_REL: suite_text(),
        ".metadata/metadata.json": metadata_text(),
        "localization/simp_chinese/zz_probe_ab_l_simp_chinese.yml": loc_text(),
        "localization/english/zz_probe_ab_l_english.yml": loc_text_en(),
    }
    files.update(
        {f"tools/scripted_tests/{name}.txt": converge_text(name) for name in VANILLA_SUITES}
    )
    return Built(files=files)


def write(*, root: Path | None = None, game: Path | None = None) -> list[Path]:
    """写进仓库里的探针目录（游戏侧文件带 UTF-8 BOM，loc 与套件都必须带）。

    原版 `tools/scripted_tests/*.txt` 实测带 BOM（含 `scripted_tests.md` 之外的 5 个套件），
    所以这里与 `common/` 一视同仁 —— BOM 是游戏侧文本的默认口径。
    """
    base = root or PROBE_DIR
    built = build(game=game)
    written: list[Path] = []
    for rel, text in sorted(built.files.items()):
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8-sig" if rel.endswith((".txt", ".yml")) else "utf-8"
        path.write_text(text, encoding=encoding, newline="\n")
        written.append(path)
    return written


def deploy(
    *,
    root: Path | None = None,
    target: Path | None = None,
    game: Path | None = None,
) -> Path:
    """生成 → 同步进用户 mod 目录 → 连同真 mod 一起启用。"""
    write(root=root, game=game)
    source = root or PROBE_DIR
    dest_root = target or experiments.TARGET_DIR
    dest = dest_root / PROBE_MOD
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    # 真 mod 也要装：探针的效果引用 `sitai_ru_defeat_shock` / `sitai_ru_reform_input`，
    # 没装就是 Unknown effect
    product = config.REPO / "mod"
    mod = dest_root / MOD_DIR_NAME
    if product.is_dir():
        if mod.exists():
            shutil.rmtree(mod)
        shutil.copytree(product, mod)
    paths = [dest, mod] if mod.is_dir() else [dest]
    experiments.set_enabled_mods(paths)
    return dest


def summary(built: Built) -> str:
    """给人看的构建摘要。"""
    arms = " → ".join(
        f"{step.role}（第 {step.at_month} 月起{'' if step.effect else '，什么都不做'}）"
        for step in LADDER
    )
    lines = [
        f"臂阶梯（点一次决议武装）：{arms}",
        f"生成文件 {len(built.files)} 个：",
    ]
    lines += [f"  {rel}" for rel in built.paths]
    return "\n".join(lines)


__all__ = [
    "ARM_START",
    "CONVERGE_DATE",
    "GEN_HEADER",
    "INPUT_EFFECT",
    "INPUT_MODIFIER",
    "LADDER",
    "LAWS",
    "MONTH_VAR",
    "PROBE_DIR",
    "PROBE_MOD",
    "ROLES",
    "SHOCK_EFFECT",
    "SHOCK_VAR",
    "STAGE_VAR",
    "SUBJECT",
    "SUITE_REL",
    "VANILLA_SUITES",
    "ArmStep",
    "Built",
    "build",
    "converge_text",
    "decisions_text",
    "deploy",
    "effects_text",
    "loc_text",
    "loc_text_en",
    "metadata_text",
    "on_actions_text",
    "suite_text",
    "summary",
    "write",
]
