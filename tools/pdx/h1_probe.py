"""H1 探针的**生成器**（阶段 2）。

为什么探针要生成而不是手写（P3 Python 化 / P9 单一事实源）：

* **日志链**必须按 `type` 枚举原版**全部**牌（administrative / political / diplomatic
  三槽共 34 张）。手写会随游戏版本漂移，而漂移的表现是"某个槽位永远落进兜底桶" ——
  这是**静默失真**：统计照跑，结论照出，只是错的。生成器从游戏文件现读，漂移会直接
  反映到探针内容里。
* **剂量 → 权重**的阶梯同时出现在探针牌文件和分析器里，只能有一个来源 ——
  所以牌文件由 :data:`pdx.h1.DOSE_WEIGHT` 生成。
* 每次实验只改**一个变量**：变体（自然 / 重抽风暴）。生成器保证其余部分逐字相同。

产出就是 :data:`PROBE_DIR` 下的探针 mod 目录树；:func:`deploy` 再把它同步进用户
mod 目录，并把 `content_load.json` 只留这一个 mod（原列表有备份，用完还原）。

两个变体：

``natural``
    引擎的真实重抽节奏（政治槽实测 ≈0.37%/国家·月）。回答"原版节奏有多快"。
``storm``
    用独立小文件覆盖 `NAI` 的两个键（KB 05 §1.7 证明可按「块+参数」覆盖，不必整文件替换）：
    ``CHANGE_STRATEGY_THRESHOLD = 1`` + ``CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE = 100``
    → 每周都可能重抽。回答两件事：**权重能不能推动落点**（大样本剂量反应），
    以及**mod 能不能接管重抽节奏**（这是"让 AI 在战役尺度上重新推导最优解"的杠杆）。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import ai_surface, config, experiments
from pdx.h1 import DOSE_ORDER, DOSE_WEIGHT, SLOT_SHORT, SLOTS

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

#: 探针 mod 目录名（`zz_` 前缀 → 排在原版之后；`_h1` → 实验编号）。
PROBE_MOD = "zz_probe_h1"

#: 探针源目录（仓库内，可审阅）。
PROBE_DIR = config.REPO / "tools" / "probe" / PROBE_MOD

#: 生成的探针牌：槽位 → (牌名, 文件名, 图标)。
SLOT_CARDS: dict[str, tuple[str, str, str]] = {
    "political": (
        "ai_strategy_sitai_probe_reform",
        "zz_probe_h1_pol.txt",
        "progressive_agenda.dds",
    ),
    "administrative": (
        "ai_strategy_sitai_probe_admin",
        "zz_probe_h1_adm.txt",
        "agricultural_expansion.dds",
    ),
    "diplomatic": (
        "ai_strategy_sitai_probe_diplo",
        "zz_probe_h1_dip.txt",
        "maintain_power_balance.dds",
    ),
}

#: 各槽位牌的**差异字段**（只写与原版不同的部分；其余走默认层）。
SLOT_FIELDS: dict[str, str] = {
    "political": (
        "\tpro_interest_groups = { ig_intelligentsia }\n"
        "\tchange_law_chance = { value = 0.5 }\n"
        "\tmax_progressiveness = { value = 0.8 }"
    ),
    "administrative": "\tbuilding_group_weights = { bg_manufacturing = 1.0 }",
    "diplomatic": "\tunacceptable_infamy_level = { value = 50 }",
}

#: 无本地化 / 无图标牌（B10）：权重 1，远低于原版中位数 10。
NOLOC_CARD = "ai_strategy_sitai_probe_noloc"

#: 第四槽候选（B7）：`type` 用原版不存在的值。
FOURTH_CARD = "ai_strategy_sitai_probe_fourth"

#: 第四槽候选的 `type` 值。
FOURTH_TYPE = "sitai_fourth"

#: 剂量变量前缀（`sitai_probe_dose_low` …）。
DOSE_VAR_PREFIX = "sitai_probe_dose_"

#: `add_ai_strategy` 语法测试（H3）已在 2026-09-20 的 storm 局里**结案**：
#: `add_ai_strategy = { type = … id = … }` 与 `add_ai_strategy = <牌名>` 两种写法
#: 引擎都报 `Unknown effect add_ai_strategy` —— exe 里有这个标识符（控制台/内部名），
#: 但它**不是脚本效果**。"直接指定 AI 策略"这条路封死，只剩权重 / `possible` / 节奏三根杠杆。
#: 结论记在 `docs/design/exec/阶段2-结果.md` 与 `docs/design/backlog.md`。
H3_RESULT = "add_ai_strategy 不是脚本效果（两种语法都是 Unknown effect）"

#: storm 变体覆盖的 defines（块名 → {键: 值}）。
STORM_DEFINES: dict[str, dict[str, object]] = {
    "NAI": {"CHANGE_STRATEGY_THRESHOLD": 1, "CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE": 100}
}

VARIANTS = ("natural", "storm")

#: 生成文件的开头（提醒"改这里没用"）。
GEN_HEADER = "# ⚠️ 本文件由 `v3 h1-probe` 生成（tools/pdx/h1_probe.py）—— 改这里没用，改生成器。\n"

#: 缩进符（探针文件用 Tab 缩进，与原版一致）。
TAB = "\t"


def _dose_chain(indent: str = "\t") -> str:
    """`weight` 块里的剂量阶梯（低/中/高各自 add 多少，由 :data:`DOSE_WEIGHT` 推出来）。"""
    base = DOSE_WEIGHT[DOSE_ORDER[0]]
    out: list[str] = []
    for dose in DOSE_ORDER[1:]:
        var = DOSE_VAR_PREFIX + dose.lower()
        add = DOSE_WEIGHT[dose] - base
        out.append(
            f"{indent}if = {{\n"
            f"{indent}\tlimit = {{ has_variable = {var} }}\n"
            f"{indent}\tadd = {add}\n"
            f"{indent}}}"
        )
    return "\n".join(out)


def slot_card_text(slot: str) -> str:
    """一张剂量加权牌（三个槽位各一张，除 `type` 与字段外逐字相同）。"""
    name, _file, icon = SLOT_CARDS[slot]
    base = DOSE_WEIGHT[DOSE_ORDER[0]]
    ladder = "、".join(f"{d} {DOSE_WEIGHT[d]}" for d in DOSE_ORDER)
    return (
        f"{GEN_HEADER}"
        f"# 剂量加权牌（{slot} 槽）。四个随机分组唯一的差异就是这个 `weight`：{ladder}。\n"
        f"# 分组变量不被任何其它系统读取，所以组间差异只可能来自权重。\n"
        f"{name} = {{\n"
        f'\ticon = "gfx/interface/icons/ai_strategy_icons/{icon}"\n'
        f"\ttype = {slot}\n"
        f"\tpossible = {{ always = yes }}\n"
        f"\n"
        f"\tweight = {{\n"
        f"\t\tvalue = {base}\n"
        f"{_dose_chain(TAB * 2)}\n"
        f"\t}}\n"
        f"\n"
        f"{SLOT_FIELDS[slot]}\n"
        f"}}\n"
    )


def noloc_card_text() -> str:
    """B10：故意不带 loc / icon 的牌（权重 1）。单独一个文件，引擎拒它也不牵连主牌。"""
    return (
        f"{GEN_HEADER}"
        f"# B10：故意**不带 loc / icon** 的牌，用来观察引擎的抱怨方式（或是否安静接受）。\n"
        f"# 权重 1（远低于原版中位数 10）→ 即使被抽中也几乎不影响世界。\n"
        f"{NOLOC_CARD} = {{\n"
        f"\ttype = political\n"
        f"\tpossible = {{ always = yes }}\n"
        f"\n"
        f"\tweight = {{ value = 1 }}\n"
        f"\n"
        f"\tpro_interest_groups = {{ ig_intelligentsia }}\n"
        f"}}\n"
    )


def fourth_card_text() -> str:
    """B7：第四槽候选 —— `type` 用一个原版不存在的值。"""
    return (
        f"{GEN_HEADER}"
        f"# B7：第四槽候选 —— `type` 用一个原版不存在的值。\n"
        f"# 预期：报错或整条被忽略（槽位是引擎侧固定的三个）；万一行，我们就白得一个槽。\n"
        f"# 权重 1000：若引擎真把它当第四槽且会抽，它会被大量抽中 —— 一眼可见。\n"
        f"{FOURTH_CARD} = {{\n"
        f'\ticon = "gfx/interface/icons/ai_strategy_icons/placate_population.dds"\n'
        f"\ttype = {FOURTH_TYPE}\n"
        f"\tpossible = {{ always = yes }}\n"
        f"\n"
        f"\tweight = {{ value = 1000 }}\n"
        f"\n"
        f"\tpro_interest_groups = {{ ig_intelligentsia }}\n"
        f"}}\n"
    )


def effects_text(variant: str) -> str:
    """随机分组（RCT 的分配）+ 开局 RUN 标记。"""
    assign_lines: list[str] = []
    for dose in DOSE_ORDER[1:]:
        var = DOSE_VAR_PREFIX + dose.lower()
        assign_lines.append(f"\t\t\t\t25 = {{ set_variable = {{ name = {var} value = 1 }} }}")
    assign_lines.append("\t\t\t\t25 = { }")
    assignments = "\n".join(assign_lines)

    return (
        f"{GEN_HEADER}"
        f"# ⚠️ **本文件里只能有裸效果列表**（scripted_effects 的语法）：写成 on_action 那种\n"
        f"#    `effect = {{ … }}` 包装会被引擎读成「调一个叫 effect 的效果」→\n"
        f"#    `Unknown effect effect`，整个定义作废，而 on_action 那头只会报\n"
        f"#    `No on_action scripted with tag … cannot link`（实测踩过：分组一次都没跑，\n"
        f"#    DOSE 行全是 CTRL）。钩子/包装在 `zz_probe_h1_on_actions.txt` 里。\n"
        f"#\n"
        f"# ① `zz_probe_h1_assign`：随机分组，`random_list` 25/25/25/25 → 四组。\n"
        f"#    组间**唯一**差异是探针牌的权重。幂等（`{DOSE_VAR_PREFIX}assigned` 标记）：\n"
        f"#    两个 on_game_started 钩子都会调它，重复调用是常态。\n"
        f"# ② `zz_probe_h1_boot`：开局写一行 RUN 标记 —— 分析器靠它切分「哪次启动的数据」\n"
        f"#    （日志轮转会把多次启动的行混在同一个目录里）。\n"
        f"#\n"
        f"# H3（`add_ai_strategy` 语法）已结案并从探针里移除：{H3_RESULT}。\n"
        f"zz_probe_h1_assign = {{\n"
        f"\tevery_country = {{\n"
        f"\t\tif = {{\n"
        f"\t\t\tlimit = {{ NOT = {{ has_variable = {DOSE_VAR_PREFIX}assigned }} }}\n"
        f"\t\t\tset_variable = {{ name = {DOSE_VAR_PREFIX}assigned value = 1 }}\n"
        f"\t\t\trandom_list = {{\n"
        f"{assignments}\n"
        f"\t\t\t}}\n"
        f"\t\t}}\n"
        f"\t}}\n"
        f"}}\n"
        f"\n"
        f"zz_probe_h1_boot = {{\n"
        f"\tzz_probe_h1_assign = yes\n"
        f'\tdebug_log = "ZZPROBE H1;RUN;{variant}"\n'
        f"}}\n"
    )


def _log_chain(short: str, names: Iterable[str]) -> str:
    """一个槽位的自报链：我们的牌 → 原版该槽全部牌 → 默认牌 → 兜底 `none`。"""
    lines: list[str] = []
    for index, name in enumerate(names):
        keyword = "if" if index == 0 else "else_if"
        label = name.removeprefix("ai_strategy_")
        lines.append(
            f"\t\t{keyword} = {{\n"
            f"\t\t\tlimit = {{ has_strategy = {name} }}\n"
            f'\t\t\tdebug_log = "ZZPROBE H1;{short};{label};'
            f'[THIS.GetCountry.GetNameNoFormatting]"\n'
            f"\t\t}}"
        )
    lines.append(
        f"\t\telse_if = {{\n"
        f"\t\t\tlimit = {{ has_strategy = ai_strategy_default }}\n"
        f'\t\t\tdebug_log = "ZZPROBE H1;{short};default;'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"\t\t}}"
    )
    lines.append(
        f"\t\telse = {{\n"
        f'\t\t\tdebug_log = "ZZPROBE H1;{short};none;'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"\t\t}}"
    )
    return "\n".join(lines)


def chain_cards(vanilla: Iterable[ai_surface.Card], slot: str) -> list[str]:
    """某槽位自报链上的牌：我们的牌在前，原版同槽的牌按名字排序跟在后面。"""
    names: list[str] = []
    for card in vanilla:
        if card.slot == slot and card.name not in names:
            names.append(card.name)
    names.sort()
    ours = [SLOT_CARDS[slot][0]]
    if slot == "political":
        ours += [NOLOC_CARD, FOURTH_CARD]
    return [*ours, *names]


def on_actions_text(vanilla: Iterable[ai_surface.Card]) -> str:
    """触发 + 每月自报（三槽各一行）。自报链按 `type` 从游戏文件现读。"""
    cards = list(vanilla)
    dose_lines: list[str] = []
    for index, dose in enumerate(DOSE_ORDER[1:]):
        keyword = "if" if index == 0 else "else_if"
        var = DOSE_VAR_PREFIX + dose.lower()
        dose_lines.append(
            f"\t\t{keyword} = {{\n"
            f"\t\t\tlimit = {{ has_variable = {var} }}\n"
            f'\t\t\tdebug_log = "ZZPROBE H1;DOSE;{dose};'
            f'[THIS.GetCountry.GetNameNoFormatting]"\n'
            f"\t\t}}"
        )
    dose_lines.append(
        f"\t\telse = {{\n"
        f'\t\t\tdebug_log = "ZZPROBE H1;DOSE;{DOSE_ORDER[0]};'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"\t\t}}"
    )
    doses = "\n".join(dose_lines)

    chains = [_log_chain(SLOT_SHORT[slot], chain_cards(cards, slot)) for slot in SLOTS]

    return (
        f"{GEN_HEADER}"
        f"# H1 的触发与自报（**纯新增字段**，不覆盖原版任何字段）。\n"
        f"#\n"
        f"# ① 分组：`on_game_started` / `on_game_started_after_lobby` 的原版字段是 `effect`，\n"
        f"#    我们只加原版没有的 `on_actions` 字段 → 按字段合并，原版行为一字不动。\n"
        f"# ② 月度自报：`on_monthly_pulse_country` 的原版字段是 `events` + `effect`，没有\n"
        f"#    `on_actions` → 纯追加；这个钩子**天然是国别作用域**（root = 国家），\n"
        f"#    不需要 `every_country`。\n"
        f"#\n"
        f"# ⚠️ **本文件里的每个 tag 都必须在这里定义**（`on_actions = {{ … }}` 只认 on_action\n"
        f"#    定义，不认 scripted_effects 里的效果名）：把 `zz_probe_h1_start` 定义到效果文件里\n"
        f"#    的后果是 `No on_action scripted with tag … cannot link`，钩子静默失效（实测踩过）。\n"
        f"#    所以：逻辑写在 `zz_probe_h1_effects.txt`（裸效果），包装写在这里。\n"
        f"#\n"
        f"# ⚠️ 自报格式的两条实测教训：\n"
        f"#   1. 取值只能用原版证明可用的 loc 命令：`[THIS.GetCountry.GetNameNoFormatting]`\n"
        f"#      （`[This.GetTag]` 不是合法命令，引擎会替换成 `ERROR:[This.GetTag]`）；\n"
        f"#   2. 分隔符**不能用 `|`**：会被 loc 解析器当控制符，每条日志附带一条\n"
        f"#      `Data error in loc string`（刷屏 + 加速日志轮转）。用 `;`。\n"
        f"on_game_started = {{\n"
        f"\ton_actions = {{ zz_probe_h1_start }}\n"
        f"}}\n"
        f"\n"
        f"on_game_started_after_lobby = {{\n"
        f"\ton_actions = {{ zz_probe_h1_start }}\n"
        f"}}\n"
        f"\n"
        f"on_monthly_pulse_country = {{\n"
        f"\ton_actions = {{ zz_probe_h1_monthly }}\n"
        f"}}\n"
        f"\n"
        f"# 开局钩子的**包装**：on_action 必须定义在 on_actions 文件里，效果体在效果文件里。\n"
        f"zz_probe_h1_start = {{\n"
        f"\teffect = {{ zz_probe_h1_boot = yes }}\n"
        f"}}\n"
        f"\n"
        f"# root = 国家\n"
        f"zz_probe_h1_monthly = {{\n"
        f"\teffect = {{\n"
        f"{doses}\n"
        f"\n"
        f"{chains[0]}\n"
        f"\n"
        f"{chains[1]}\n"
        f"\n"
        f"{chains[2]}\n"
        f"\n"
        f"\t\t# 第四槽（B7）：只有真被抽中才会打这一行。\n"
        f"\t\tif = {{\n"
        f"\t\t\tlimit = {{ has_strategy = {FOURTH_CARD} }}\n"
        f'\t\t\tdebug_log = "ZZPROBE H1;FOURTH;active;'
        f'[THIS.GetCountry.GetNameNoFormatting]"\n'
        f"\t\t}}\n"
        f"\t}}\n"
        f"}}\n"
    )


def defines_text() -> str:
    """storm 变体：用独立小文件按「块 + 参数」覆盖 `NAI` 的两个键。"""
    body: list[str] = []
    for block, keys in STORM_DEFINES.items():
        body.append(f"{block} = {{")
        for key, value in keys.items():
            body.append(f"\t{key} = {value}")
        body.append("}")
    return (
        f"{GEN_HEADER}"
        f"# 只覆盖两个键，不复制原版 00_ai.txt（KB 05 §1.7：按「块 + 参数」覆盖；\n"
        f"# Kuromi 的 kai_ai.txt 也只写了一个 NAI 块）。\n"
        f"#\n"
        f"# 原版值：CHANGE_STRATEGY_THRESHOLD = 100、INCREASE_WEEKLY_CHANCE = 20（1 = 1%）。\n"
        f"# 原版语义 → 攒够 100 个「变更点」才重抽一次；每周只有 20% 概率 +1 点，\n"
        f"# 所以单靠周通道要 ≈9.6 年才重抽一次（这正是政治槽实测 0.37%/月 的原因）。\n"
        f"# 本变体把门槛压到 1、周概率拉满 → 每周都重抽：大样本剂量反应 + 验证\n"
        f"# 「mod 能不能接管重抽节奏」。\n" + "\n".join(body) + "\n"
    )


@dataclass(frozen=True, slots=True)
class Built:
    """一次 build 的产物：相对路径 → 文本。"""

    variant: str
    files: dict[str, str]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self.files))


def build(*, variant: str = "natural", game: Path | None = None) -> Built:
    """生成探针的全部**生成文件**（相对探针根目录）。"""
    if variant not in VARIANTS:
        raise ValueError(f"未知变体：{variant}（可选 {', '.join(VARIANTS)}）")
    files: dict[str, str] = {}
    for slot, (_name, filename, _icon) in SLOT_CARDS.items():
        files[f"common/ai_strategies/{filename}"] = slot_card_text(slot)
    files["common/ai_strategies/zz_probe_h1_noloc.txt"] = noloc_card_text()
    files["common/ai_strategies/zz_probe_h1_fourth.txt"] = fourth_card_text()
    files["common/scripted_effects/zz_probe_h1_effects.txt"] = effects_text(variant)
    files["common/on_actions/zz_probe_h1_on_actions.txt"] = on_actions_text(
        ai_surface.read_cards(game)
    )
    if variant == "storm":
        files["common/defines/zz_probe_h1_defines.txt"] = defines_text()
    return Built(variant=variant, files=files)


def write(
    *, variant: str = "natural", root: Path | None = None, game: Path | None = None
) -> list[Path]:
    """把生成文件写进仓库里的探针目录，并清掉被取代的旧文件。"""
    base = root or PROBE_DIR
    built = build(variant=variant, game=game)
    written: list[Path] = []
    for rel, text in sorted(built.files.items()):
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # utf-8-sig：**探针文件必须带 BOM**（引擎口径，仓库里有专门的用例钉着）。
        # 不带 BOM 时中文注释会被引擎按另一套编码读，表现为"这份文件像没生效"。
        path.write_text(text, encoding="utf-8-sig", newline="\n")
        written.append(path)
    stale = base / "common" / "ai_strategies" / "zz_probe_h1_reform.txt"
    if stale.is_file():
        stale.unlink()
    defines = base / "common" / "defines" / "zz_probe_h1_defines.txt"
    if variant != "storm" and defines.is_file():
        defines.unlink()
    return written


def deploy(
    *,
    variant: str = "natural",
    root: Path | None = None,
    target: Path | None = None,
    game: Path | None = None,
) -> Path:
    """生成 → 同步进用户 mod 目录 → 只启用这一个 mod（原列表已备份）。"""
    write(variant=variant, root=root, game=game)
    source = root or PROBE_DIR
    dest_root = target or experiments.TARGET_DIR
    dest = dest_root / PROBE_MOD
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    experiments.set_enabled_mods([dest])
    return dest


def archive_logs(tag: str, *, log_dir: Path | None = None) -> tuple[Path, int, int]:
    """把当前日志整体挪进归档目录，返回 (归档路径, 挪走数, 被占用数)。

    **每次启动前都要做**：日志轮转会把多次启动的行留在同一个目录里，
    混在一起统计等于把两次实验的样本池倒在一起。

    游戏还开着时日志被独占，挪不动 —— 那种文件计入"被占用"而不是抛异常：
    先退出游戏再归档，是这个函数唯一的正确用法。
    """
    base = log_dir or config.USERDIR / "logs"
    dest = config.USERDIR / "v3probe-logs-archive" / tag
    dest.mkdir(parents=True, exist_ok=True)
    moved = 0
    skipped = 0
    for path in sorted(base.glob("*.log")) if base.is_dir() else []:
        if not path.is_file():
            continue
        try:
            shutil.move(str(path), str(dest / path.name))
        except OSError:
            skipped += 1
        else:
            moved += 1
    return dest, moved, skipped


def summary(built: Built) -> str:
    """给人看的构建摘要。"""
    lines = [f"变体：{built.variant}", f"生成文件 {len(built.files)} 个："]
    lines += [f"  {rel}" for rel in built.paths]
    return "\n".join(lines)


def metadata_text() -> str:
    """探针 mod 的 `.metadata/metadata.json`（游戏用）。"""
    return (
        json.dumps(
            {
                "name": "ZZ Probe H1",
                "id": "",
                "version": "2.0",
                "supported_game_version": "1.14.3",
                "short_description": (
                    "H1：随机分组 + 剂量反应，验证「改权重能否推动 AI 策略落点」；"
                    "storm 变体额外验证「mod 能否接管重抽节奏」"
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


__all__ = [
    "DOSE_VAR_PREFIX",
    "FOURTH_CARD",
    "FOURTH_TYPE",
    "GEN_HEADER",
    "H3_RESULT",
    "NOLOC_CARD",
    "PROBE_DIR",
    "PROBE_MOD",
    "SLOT_CARDS",
    "STORM_DEFINES",
    "VARIANTS",
    "Built",
    "archive_logs",
    "build",
    "chain_cards",
    "defines_text",
    "deploy",
    "effects_text",
    "fourth_card_text",
    "metadata_text",
    "noloc_card_text",
    "on_actions_text",
    "slot_card_text",
    "summary",
    "write",
]
