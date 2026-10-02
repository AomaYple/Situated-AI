"""``pdx.modgen`` 的用例：数据源 → 产物的那条编译链。

重点不是"文件写出来了"，而是**那几条会让产物静默失效的性质**：

* 空 `why` 必须当场报错（P10 的机械检查 —— 靠人记得的纪律等于没有）；
* 两次生成逐字节一致（P8：确定性是"生成器优先"的前提，抖动的产物没法进版本控制）；
* 仓库产物 UTF-8 无 BOM、LF，文件名平铺在 `sitai_*` 命名空间（F7）；
  游戏所需 BOM 由部署与打包边界添加，边界测试见 test_repository_upgrade；
* 产物能被**仓库自己的解析器**读懂（拼漏一个 `}` 是最可能的故障模式）。

用例一律不依赖真实游戏：数据源写到 `tmp_path` 再编译。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pdx import modgen
from pdx.model import Assignment, Block
from pdx.parser import parse_text

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: 一份**最小可用**的数据源。各用例用定向替换把它改成"缺东西"的版本 ——
#: 这样"报错"的用例与"通过"的用例只差一处，失败时一眼能看出是哪一处引起的。
MINIMAL = """schema_version = 1

[archive]
id = "t1"
title = "测试档案"
country = "RUS"
game_version = "1.14.3"
why = "测：这份档案修什么毛病"

[tempo]
block = "NAI"
why = "测：为什么要接管节奏"
[[tempo.keys]]
key = "CHANGE_STRATEGY_THRESHOLD"
amount = 40
why = "测：为什么是 40"

[memory]
variable = "sitai_t1_memory"
effect = "sitai_t1_shock"
why = "测：记忆变量做什么用"
[[memory.params]]
key = "days"
amount = 3650
why = "测：为什么是 3650 天"

[pressure]
name = "sitai_t1_pressure"
icon = "gfx/interface/icons/timed_modifier_icons/modifier_statue_negative.dds"
why = "测：压力为什么必须是真的世界状态"
[[pressure.params]]
key = "years"
amount = 10
why = "测：为什么是 10 年"
[[pressure.effects]]
key = "country_legitimacy_base_add"
amount = -20
why = "测：为什么取 -20"

[journal_entry]
name = "je_sitai_t1_window"
group = "je_group_internal_affairs"
icon = "gfx/interface/icons/event_icons/event_portrait.dds"
why = "测：为什么用 JE 而不是牌"
[[journal_entry.fields]]
key = "weight"
amount = 100
why = "测：为什么是 100"
[[journal_entry.conditions]]
gate = "possible"
key = "has_variable"
arg = "sitai_t1_memory"
why = "测：开窗的第一个条件"

[[localization]]
key = "je_sitai_t1_window"
english = "Test Window"
simp_chinese = "测试窗口"
why = "测：文案依据"

[cards]
why = "测：本档案不递牌的理由"

[[references]]
kind = "trigger"
name = "has_variable"
why = "测：这条引用在原版哪里用过"
"""

#: `MINIMAL` 里的 `[tempo]` 段（**逐字**复制）。
#: 阶段 4 起 `[tempo]` 是可选的 **mod 级**表：全仓只允许一份，所以第二份档案
#: 必须能整段不带它 —— 这条常量就是"摘掉它"的那个手术刀。
TEMPO_BLOCK = """[tempo]
block = "NAI"
why = "测：为什么要接管节奏"
[[tempo.keys]]
key = "CHANGE_STRATEGY_THRESHOLD"
amount = 40
why = "测：为什么是 40"

"""

#: 追加到 :data:`MINIMAL` 后面的"第二处理段"（可选表 `[reform_inputs]`）。
#: 单独一份常量：`MINIMAL` 保持"只有一处处理"的形状，两条路径都要有用例。
REFORM_INPUTS = """
[reform_inputs]
name = "sitai_t1_reform_inputs"
effect = "sitai_t1_reform_input"
icon = "gfx/interface/icons/timed_modifier_icons/modifier_lightbulb_positive.dds"
why = "测：改革侧输入为什么单独一份"
[[reform_inputs.params]]
key = "years"
amount = 10
why = "测：为什么是 10 年"
[[reform_inputs.effects]]
key = "country_legitimacy_base_add"
amount = 5
why = "测：为什么取 +5"
"""

#: 追加到 :data:`MINIMAL` 后面的"递牌信号"（可选表 `[journal_entry.signals]`）。
#: 2026-09-22 新增：世界状态只改得了 AI 的**输入**，改不了它已经挂着的那张牌，
#: 而牌才是"动不动手改法"的闸门（backlog B53）⇒ 窗口开时必须 `set_strategy`。
#: 2026-10-01 起：落在**可见块**（`on_complete`）的那条还必须给 `tooltip` —— 引擎会把
#: 那个块渲染成详情面板「如果完成」那一格，而 `set_strategy` 的 effect_localization 只有
#: `global`（可见块要 `first`）⇒ 裸写会显示 `BUG: set_strategy missing perspective …`。
SIGNALS = """
[[localization]]
key = "je_sitai_t1_window_complete_tt"
english = "Test completion line."
simp_chinese = "测试完成行。"
why = "测：可见块那条递牌的文案键（面板『如果完成』那一格）"
[journal_entry.signals]
why = "测：为什么必须递牌（世界状态改不了已挂着的牌）"
[[journal_entry.signals.set_strategy]]
key = "set_strategy"
arg = "ai_strategy_progressive_agenda"
why = "测：窗口一开就换路线"
[[journal_entry.signals.clear_strategy]]
key = "set_strategy"
arg = "ai_strategy_reactionary_agenda"
tooltip = "je_sitai_t1_window_complete_tt"
why = "测：窗口一关递回去（可见块 ⇒ 自带文案键）"
"""


#: 追加到 :data:`MINIMAL` 后面的"面板三行"（可选表 `[panel]`，P11 的三行解释）。
#: 2026-09-22 新增：G3 判的是**试玩者能复述「当前目标 + 主因」**，而揉进 `_reason`
#: 的散文里看不出"缺哪一行" ⇒ 拆成三个键，缺行当场报错。
#:
#: ⚠️ 2026-09-23 起还要求数据源里有 `<JE 名>_reason` 那条 loc：三行要**上屏**就得接进
#: JE 说明（引擎显示的是 `[JournalEntry.GetReason]`），所以这里连带补上它。
PANEL = """
[[localization]]
key = "je_sitai_t1_window_reason"
english = "Test window reason."
simp_chinese = "测试窗口的说明。"
why = "测：JE 说明的依据（三行会接在它后面）"

[panel]
why = "测：为什么这三行要放在一起"
[panel.goal]
english = "Goal line."
simp_chinese = "目标行。"
why = "测：第一行为什么是当前目标"
[panel.pressure]
english = "Pressure line."
simp_chinese = "压力行。"
why = "测：第二行为什么是压力与阻力"
[panel.last_change]
english = "Last change line."
simp_chinese = "上次改主意的原因行。"
why = "测：第三行为什么是上次改主意的原因"
"""


def _write_source(tmp_path: Path, text: str = MINIMAL, name: str = "t1.toml") -> Path:
    base = tmp_path / "data"
    base.mkdir(parents=True, exist_ok=True)
    path = base / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _archive(tmp_path: Path, text: str = MINIMAL) -> modgen.Archive:
    return modgen.load_data(_write_source(tmp_path, text))


def _panel_text(archive: modgen.Archive, slot: str, lang: str) -> str:
    """从**数据源**里取 `[panel.<slot>].<lang>` 的文案（`t97` 起 `goal` 槽不再进 `localization`）。

    为什么必须走数据源、而不是从 `archive.localization` 里按 key 找：`goal` 那一槽的 loc 键
    **已经被引擎判为冗余并停发**（见 `modgen.PANEL_SLOTS_WITH_OWN_LOC`）⇒ 它在 `localization`
    里查不到了，而"文案还在不在"这件事恰恰是这条用例要守的东西 ⇒ 只能回到数据源取期望值。
    """
    raw = modgen.read_source(modgen.DATA_DIR / f"{archive.id}.toml")["panel"]
    assert isinstance(raw, dict), "数据源的 [panel] 应该是表"
    line = raw[slot]
    assert isinstance(line, dict), f"[panel.{slot}] 应该是表"
    value = line[lang]
    assert isinstance(value, str), f"[panel.{slot}].{lang} 应该是字符串"
    return value


def _second_source(
    *,
    tempo: bool = False,
    game_version: str = "1.14.3",
) -> str:
    """第二份档案的数据源：**同一套结构、换一套名字**（G-EXIT-1 的"只加数据行"）。

    默认**不带** `[tempo]` —— 阶段 4 起它是全仓一份的 mod 级表，
    第二份档案不该复制一遍；`tempo=True` 用来造"两份都声明"的失败路径。
    """
    text = MINIMAL if tempo else MINIMAL.replace(TEMPO_BLOCK, "")
    for old, new in (
        ('id = "t1"', 'id = "t2"'),
        ('title = "测试档案"', 'title = "第二档案"'),
        ('country = "RUS"', 'country = "AUS"'),
        ('game_version = "1.14.3"', f'game_version = "{game_version}"'),
        ('name = "RUS"', 'name = "AUS"'),
        ("sitai_t1", "sitai_t2"),
    ):
        text = text.replace(old, new)
    return text


def _two_archives(
    tmp_path: Path,
    *,
    tempo: bool = False,
    game_version: str = "1.14.3",
    second_id: str = "t2",
) -> tuple[modgen.Archive, ...]:
    """写两份数据源并编译成档案（a.toml = MINIMAL，b.toml = 换名的第二份）。"""
    _write_source(tmp_path, MINIMAL, name="a.toml")
    text = _second_source(tempo=tempo, game_version=game_version)
    if second_id != "t2":
        text = text.replace('id = "t2"', f'id = "{second_id}"')
    _write_source(tmp_path, text, name="b.toml")
    return modgen.load_all(tmp_path / "data")


# ── 数据源解析 ──────────────────────────────────────────────
def test_每份真实档案都有三行解释且真的接进JE说明() -> None:
    """阶段 6 的 G3 挂在三行上 —— 所以**每一份**发布出去的档案都必须有它。

    两个判据（都跑在真实 `mod/data` 上，不是夹具）：
    * `[panel]` 三行齐全 —— 缺一行生成器就退 2；
    * 三行**真的进了 JE 说明**（`<JE 名>_reason`）—— 引擎显示的是
      `journal_entry.gui:742` 的 `GetReason`；只写三个独立键等于"没上屏"。

    ⚠️ `goal` 那一槽**不单独发 loc 键**（`t97`）：引擎只为带 goal 度量
    （`goal_add_value`）的 JE 用 `<JE 名>_goal`，没有度量却写了它 ⇒
    `journal_entry_type.cpp:476 Journal entry has redundant loc for …_goal`。
    所以这一槽的**期望文案要从数据源里取**，再断言它确实并进了 `_reason` ——
    这正是「消掉冗余 loc **不许**把玩家可见文案一起删掉」那条判据。
    """
    archives = modgen.load_all()
    assert archives, "一份档案都没有 —— 扫描本身坏了，不是'干净'"
    # 一次构建全部档案：`modgen.build(单份)` 会走 `build_all([一份])`，而 `[tempo]` 是
    # mod 级表（只允许一份）⇒ 单份构建会报"没有任何数据源声明 [tempo]"。
    built = modgen.build_all(archives)
    for archive in archives:
        assert [slot for slot, _key, _why in archive.panel] == [
            "goal",
            "pressure",
            "last_change",
        ], f"{archive.id} 缺 [panel]（三行是 G3 的载体，见 exec/阶段6-可见性与难度.md）"
        name = archive.journal_entry.name
        for lang in sorted(modgen.LANGUAGES):
            loc = built.files[archive.loc_file(lang)]
            reason = next(
                (line for line in loc.splitlines() if f"{name}_reason" in line),
                None,
            )
            assert reason is not None, f"{archive.id} 缺 {name}_reason（三行没处可接）"
            for slot, key, _why in archive.panel:
                if slot in modgen.PANEL_SLOTS_WITH_OWN_LOC:
                    value = next(
                        entry.values[lang] for entry in archive.localization if entry.key == key
                    )
                else:
                    value = _panel_text(archive, slot, lang)
                assert value in reason, f"{archive.id}/{lang}：{slot} 那一行没接进 JE 说明"


def test_解析真实档案的关键条目() -> None:
    """第一份档案（俄罗斯 · 战败求存）必须能被解析出它该有的东西。

    这条同时钉住"设计意图没被改掉"：变量名、修正名、JE 名、两个节奏键、
    第二处理段（B2 的改革侧输入），以及**恰好一张自建牌**（t18 落地的 `ai_strategy_sitai_ru_defeat_agenda`）。
    """
    archive = modgen.load_data(modgen.DATA_DIR / "ru_defeat.toml")
    assert archive.id == "ru_defeat"
    assert archive.country == "RUS"
    assert archive.memory.variable == "sitai_ru_defeat_memory"
    assert archive.memory.effect == "sitai_ru_defeat_shock"
    assert archive.pressure.name == "sitai_ru_defeat_pressure"
    assert archive.journal_entry.name == "je_sitai_ru_reform_window"
    assert archive.journal_entry.group == "je_group_internal_affairs"
    assert archive.tempo is not None, "第一份档案必须声明 [tempo]（它是 mod 级表）"
    assert {p.key for p in archive.tempo.keys} == {
        "CHANGE_STRATEGY_THRESHOLD",
        "CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE",
    }
    # 第二处理段（B2）：与冲击分成两个效果/两个修正，实验才分得出是哪一处起了作用
    assert archive.inputs is not None
    assert archive.inputs.effect == "sitai_ru_reform_input"
    assert archive.inputs.name == "sitai_ru_reform_inputs"
    assert {p.key for p in archive.inputs.effects} == {
        "interest_group_ig_industrialists_pol_str_mult",
        "interest_group_ig_intelligentsia_pol_str_mult",
    }
    # 自建牌：**恰好这一张**（`mod/data/ru_defeat.toml` 的 `[cards]` —— t18 落地，t94 改准）。
    #
    # ⚠️ **为什么断言「恰好一张 + 逐字段」，而不是「≥1 张」或「非空」**：这条用例守的是
    #    「我们递了哪些牌、它们长什么样」这件**事实**。放宽成 `len(cards) >= 1` 或 `cards`
    #    就直接把它废掉了 —— 少一张、换一张、`slot` 写错、`weight` 漂出预算、门换成别的
    #    字段，它都会绿。牌是**处方**（F5 的取舍结果），不是可以随实现漂的自由量。
    cards = archive.cards
    assert len(cards) == 1, (
        f"本档案现在**恰好一张**自建牌，实际 {len(cards)} 张：{[c.name for c in cards]} —— "
        "数量本身是被这条用例守住的事实，放宽成「≥1」等于把断言废掉"
    )
    card = cards[0]
    assert card.name == "ai_strategy_sitai_ru_defeat_agenda"
    assert card.slot == "political"
    assert card.weight == 40  # 政治槽预算 [0.3, 0.6] ⇒ W ≤ 49（闸门 ③ 的价格表）
    assert [(clause.key, clause.fact()) for clause in card.possible] == [
        ("has_modifier", "=sitai_ru_defeat_pressure")
    ], "门 = 本档案的压力修正（处境驱动），不是别的字段"
    # 7 条档案自己的文案（4 条基础 + **2 行面板**）—— `t97` 起 `goal` 那一槽不再单独发键
    # （引擎会为它报 `has redundant loc`，文案并进 `_reason`）⇒ 16 → 15
    # + **2 条投降叠加档的显示名**（B35 的两个叠加档修正各一条；少了它们游戏里显示裸键名）
    # + 难度三档的 7 条（规则名 1 + 三档各自的 名称/说明 6）
    # + 2 条"玩家侧修正名"（只有带 player_effects 的两档才有）
    # + **1 条 `custom_tooltip` 文案**（D37：可见块 `on_complete` 那条递牌的 `text` 键
    #   `je_sitai_ru_reform_window_complete_tt` —— 少了它，那一格显示引擎拼的 `BUG: …`）⇒ 17 → 18
    assert len(archive.localization) == 18
    keys = {item.key for item in archive.localization}
    assert "rule_sitai_difficulty" in keys
    assert archive.difficulty is not None, "真实档案必须声明 [difficulty]（契约 J5）"
    for tier in archive.difficulty.tiers:
        assert tier.setting in keys
        assert f"{tier.setting}_desc" in keys
    assert {tier.id for tier in archive.difficulty.tiers} == set(modgen.DIFFICULTY_TIERS)
    assert [slot for slot, _key, _why in archive.panel] == ["goal", "pressure", "last_change"]
    # `goal` 那一槽**不许**单独发 loc 键（`t97`：引擎只为带 goal 度量的 JE 用它，
    # 没有度量却写了它 ⇒ `journal_entry_type.cpp:476` 报 redundant）；压力与上次改主意照旧发键。
    _goal_slot, goal_key, _goal_why = archive.panel[0]
    assert goal_key not in keys, "goal 槽不该出现在 localization 里（t97：它会被判冗余）"
    assert [key for _slot, key, _why in archive.panel[1:]] == [
        "je_sitai_ru_reform_window_pressure",
        "je_sitai_ru_reform_window_last_change",
    ]


def test_没有reform_inputs的档案照样编译(tmp_path: Path) -> None:
    """`[reform_inputs]` 是可选表：没有第二处理段的档案不该被迫写一张空表。"""
    archive = _archive(tmp_path)
    assert archive.inputs is None
    built = modgen.build(archive)
    assert archive.inputs_file not in built.files
    assert "没有第二处理段" in built.files[archive.doc_file]
    assert modgen.facts(archive) == modgen.readback(built.files)


def test_有reform_inputs时多出效果与修正两条事实(tmp_path: Path) -> None:
    archive = _archive(tmp_path, MINIMAL + REFORM_INPUTS)
    assert archive.inputs is not None
    built = modgen.build(archive)
    facts = dict(modgen.facts(archive))
    assert facts["effects.sitai_t1_reform_input.add_modifier.name"] == "sitai_t1_reform_inputs"
    assert facts["modifier.sitai_t1_reform_inputs.country_legitimacy_base_add"] == "5"
    assert modgen.readback(built.files) == modgen.facts(archive)
    # 效果文件里两个效果并存；第二处修正自己一个文件（清掉一个不影响另一个）
    effect_text = built.files[archive.effect_file]
    assert "sitai_t1_shock = {" in effect_text
    assert "sitai_t1_reform_input = {" in effect_text
    assert "add_modifier = {\n\t\tname = sitai_t1_reform_inputs" in effect_text
    assert built.files[archive.inputs_file].count("sitai_t1_reform_inputs = {") == 1


def test_reform_inputs缺why照样报错(tmp_path: Path) -> None:
    text = (MINIMAL + REFORM_INPUTS).replace('why = "测：改革侧输入为什么单独一份"', "")
    with pytest.raises(modgen.DataError, match="没有 why"):
        _archive(tmp_path, text)


# ── `[probe]`：每份档案显式声明"盯哪条法 / 哪张牌"（B80 / B86）──────────


def _probe_block(*, law: str = "law_serfdom", card: str = "ai_strategy_progressive_agenda") -> str:
    return f'\n[probe]\nwhy = "测：探针盯什么"\nreform_law = "{law}"\nreform_card = "{card}"\n'


def test_probe声明了法与牌就能编译(tmp_path: Path) -> None:
    archive = _archive(tmp_path, MINIMAL + _probe_block())
    assert archive.probe is not None
    assert archive.probe.reform_law == "law_serfdom"
    assert archive.probe.reform_card == "ai_strategy_progressive_agenda"


def test_probe的牌留空是允许的(tmp_path: Path) -> None:
    """留空是**正当结论**（那张牌对该档案没有判别力），不是遗漏 —— 与 `reform_law` 同口径。"""
    archive = _archive(tmp_path, MINIMAL + _probe_block(card=""))
    assert archive.probe is not None
    assert archive.probe.reform_card == ""


def test_probe的牌必须是原版策略键(tmp_path: Path) -> None:
    with pytest.raises(modgen.DataError, match=r"probe\.reform_card"):
        _archive(tmp_path, MINIMAL + _probe_block(card="progressive_agenda"))


def test_probe的法必须是原版法律键(tmp_path: Path) -> None:
    with pytest.raises(modgen.DataError, match=r"probe\.reform_law"):
        _archive(tmp_path, MINIMAL + _probe_block(law="serfdom"))


def test_probe的牌不能写成数字(tmp_path: Path) -> None:
    text = (MINIMAL + _probe_block()).replace(
        'reform_card = "ai_strategy_progressive_agenda"', "reform_card = 1"
    )
    with pytest.raises(modgen.DataError, match="必须是字符串"):
        _archive(tmp_path, text)


def test_真实档案都声明了牌() -> None:
    """八份真实档案都要么声明 `reform_card`、要么在 `why` 里写明为什么不判。

    这条只查**在场**：具体声明的牌**有没有判别力**由
    `test_probe_stage3.py::test_声明的牌不能是该国开局就有的` 拿原版数据核（B86）。
    """
    archives = modgen.load_all()
    assert archives
    for archive in archives:
        assert archive.probe is not None, f"{archive.id} 没有 [probe] 表"
        assert archive.probe.why.strip(), f"{archive.id} 的 [probe] 没有 why"


def test_真实档案的每个数字都有依据() -> None:
    """P10：`v3 modgen --why` 能机械枚举出每个数字 + 它的依据。"""
    archive = modgen.load_data(modgen.DATA_DIR / "ru_defeat.toml")
    report = modgen.why_report(archive)
    assert archive.numbers, "一个数字都没解析出来，说明口径写错了"
    for number in archive.numbers:
        assert number.why.strip(), f"{number.path} 没有依据"
        assert f"`{number.path}`" in report
    assert len(report.splitlines()) == len(archive.numbers) + 2  # 表头 + 分隔线


def test_未知schema版本报错(tmp_path: Path) -> None:
    with pytest.raises(modgen.DataError, match="schema_version"):
        _archive(tmp_path, MINIMAL.replace("schema_version = 1", "schema_version = 99"))


def test_空why报错(tmp_path: Path) -> None:
    """空 `why` 必须当场报错，并指出**是哪一张表**。"""
    text = MINIMAL.replace(
        'key = "country_legitimacy_base_add"\namount = -20\nwhy = "测：为什么取 -20"',
        'key = "country_legitimacy_base_add"\namount = -20\nwhy = "   "',
    )
    with pytest.raises(modgen.DataError, match=r"pressure\.effects\[0\]"):
        _archive(tmp_path, text)


def test_缺why字段也报错(tmp_path: Path) -> None:
    text = MINIMAL.replace('amount = -20\nwhy = "测：为什么取 -20"', "amount = -20")
    with pytest.raises(modgen.DataError, match="没有 why"):
        _archive(tmp_path, text)


def test_缺本地化语言报错(tmp_path: Path) -> None:
    """少一种语言 = 漏一种语言的文案，不能静默生成半份本地化。"""
    text = MINIMAL.replace('simp_chinese = "测试窗口"\n', "")
    with pytest.raises(modgen.DataError, match=" simp_chinese "):
        _archive(tmp_path, text)


def test_本地化文案带裸引号报错(tmp_path: Path) -> None:
    """`.yml` 的值用双引号包裹，裸引号会截断文本 —— 没有转义的实测证据，直接拒绝。

    用 TOML 的**字面**字符串（单引号）才写得进裸引号 —— 这正是这条检查存在的理由：
    基本字符串（双引号）里写不出裸引号，字面字符串里写得进。
    """
    text = MINIMAL.replace('english = "Test Window"', """english = 'Test "Window"'""")
    with pytest.raises(modgen.DataError, match="裸双引号"):
        _archive(tmp_path, text)


def test_未知判据块报错(tmp_path: Path) -> None:
    text = MINIMAL.replace('gate = "possible"', 'gate = "permanent"')
    with pytest.raises(modgen.DataError, match="不认识的判据块"):
        _archive(tmp_path, text)


def test_命名空间越界报错(tmp_path: Path) -> None:
    """F7：变量/效果/修正都不许跑到 `sitai_` 命名空间外面去。"""
    text = MINIMAL.replace('variable = "sitai_t1_memory"', 'variable = "t1_memory"')
    with pytest.raises(modgen.DataError, match="命名空间"):
        _archive(tmp_path, text)


def test_数据源不是TOML时报错(tmp_path: Path) -> None:
    with pytest.raises(modgen.DataError, match="TOML"):
        _archive(tmp_path, "这不是 TOML [[[")


def test_数据源目录为空时报错(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    with pytest.raises(modgen.DataError, match="没有"):
        modgen.load_all(tmp_path / "data")


# ── 确定性 ──────────────────────────────────────────────────
def test_两次构建完全一致(tmp_path: Path) -> None:
    """P8：同样的输入 → 同样的产出（含文件顺序）。"""
    archive = _archive(tmp_path)
    first = modgen.build(archive)
    second = modgen.build(archive)
    assert first.files == second.files
    assert first.paths == second.paths


def test_两次写盘逐字节一致(tmp_path: Path) -> None:
    """写盘也要确定：BOM、换行、文件集合都不能抖。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    modgen.write(built, root_a)
    modgen.write(built, root_b)
    files_a = {
        p.relative_to(root_a).as_posix(): p.read_bytes() for p in root_a.rglob("*") if p.is_file()
    }
    files_b = {
        p.relative_to(root_b).as_posix(): p.read_bytes() for p in root_b.rglob("*") if p.is_file()
    }
    assert files_a == files_b
    assert files_a, "一个文件都没写出来"


def test_两份档案同id时产物路径冲突要报错(tmp_path: Path) -> None:
    """同 id 的两份档案写同一批产物路径 = 谁在起作用变成无解的问题，必须当场红。

    这份输入刻意绕过前面几道检查（名字各不相同、只有一份 tempo），
    为的是让"路径冲突"这条兜底真的被走到 —— 它现在是最后一道防线。
    """
    _write_source(tmp_path, MINIMAL, name="a.toml")
    _write_source(tmp_path, _second_source().replace('id = "t2"', 'id = "t1"'), name="b.toml")
    archives = modgen.load_all(tmp_path / "data")
    assert [archive.id for archive in archives] == ["t1", "t1"]
    with pytest.raises(modgen.DataError, match="同一个产物路径"):
        modgen.build_all(archives)


# ── 编码与命名 ──────────────────────────────────────────────
def test_所有仓库产物无BOM(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root = tmp_path / "mod"
    written = modgen.write(built, root)
    assert written
    for path in written:
        rel = path.relative_to(root).as_posix()
        head = path.read_bytes()[:3]
        assert head != b"\xef\xbb\xbf", f"{rel} 不该带 BOM"


def test_产物平铺在sitai命名空间且两层(tmp_path: Path) -> None:
    """F7：游戏侧文件是「原版目录 + sitai_*.txt/yml」，不自建子目录。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    game_side = [p for p in built.paths if p.endswith(modgen.GAME_SIDE_SUFFIXES)]
    assert game_side
    for rel in game_side:
        parts = rel.split("/")
        assert len(parts) == 3, rel
        assert parts[2].startswith(modgen.FILE_PREFIX), rel


def test_生成物能被自家解析器读懂(tmp_path: Path) -> None:
    """拼漏一个 `}` 是生成器最可能的故障模式，而它在游戏里表现为"整段不生效"。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    top_keys: dict[str, set[str]] = {}
    for rel, text in built.files.items():
        if not rel.endswith(".txt"):
            continue
        parsed = parse_text(text, path=rel)
        assert not parsed.errors, f"{rel}: {parsed.errors}"
        assert parsed.top_assignments, rel
        top_keys[rel.split("/")[1]] = {a.key for a in parsed.top_assignments}
    assert top_keys["scripted_effects"] == {archive.memory.effect}
    assert top_keys["static_modifiers"] == {archive.pressure.name}
    assert top_keys["journal_entries"] == {archive.journal_entry.name}
    assert archive.tempo is not None
    assert top_keys["defines"] == {archive.tempo.block}


def test_JE判据按固定顺序分组(tmp_path: Path) -> None:
    """判据块顺序固定 —— 数据源里换个书写次序不该让产物变样。"""
    text = (
        MINIMAL
        + """
[[journal_entry.conditions]]
gate = "complete"
key = "legitimacy"
op = ">="
amount = 75
why = "测：关窗的门"
"""
    )
    archive = _archive(tmp_path, text)
    body = modgen.build(archive).files[archive.journal_file]
    assert body.index("possible = {") < body.index("complete = {")
    assert "legitimacy >= 75" in body


def test_本地化格式照原版(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    chinese = built.files[archive.loc_file("simp_chinese")]
    assert chinese.splitlines()[0] == "l_simp_chinese:"
    assert f' {archive.journal_entry.name}:0 "测试窗口"' in chinese
    assert modgen.parse_loc_text(chinese) == {archive.journal_entry.name: "测试窗口"}


def test_元数据是合法JSON且不带BOM(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    payload = json.loads(built.files[modgen.METADATA_REL])
    assert payload["id"] == "sitai.t1"
    assert payload["supported_game_version"] == "1.14.3"
    root = tmp_path / "mod"
    modgen.write(built, root)
    assert not (root / modgen.METADATA_REL).read_bytes().startswith(b"\xef\xbb\xbf")


def test_档案文档带产物清单与依据(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    doc = modgen.build(archive).files[archive.doc_file]
    assert modgen.DOC_HEADER in doc
    assert "每个数字与它的依据" in doc
    assert archive.effect_file in doc
    assert "v3 modguard" in doc


# ── 写盘与核对 ──────────────────────────────────────────────
def test_写盘会清掉被取代的旧文件(tmp_path: Path) -> None:
    """数据源删掉一条之后，旧产物必须跟着消失 —— 否则"改了数据源却没变化"。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root = tmp_path / "mod"
    stale = root / "common" / "journal_entries" / "sitai_t1_old.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(modgen.GEN_HEADER + "\n上一版的产物", encoding="utf-8")
    modgen.write(built, root)
    assert not stale.exists()
    assert (root / archive.journal_file).is_file()


def test_check能认出被手改的产物(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root = tmp_path / "mod"
    modgen.write(built, root)
    assert modgen.check(built, root) == []

    target = root / archive.effect_file
    # 无 BOM 改写，单独验证正文差异。
    target.write_text("手改过的内容", encoding="utf-8", newline="\n")
    problems = modgen.check(built, root)
    assert any("不一致" in p for p in problems)

    target.unlink()
    assert any("缺产物" in p for p in modgen.check(built, root))


def test_check能认出意外BOM的产物(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root = tmp_path / "mod"
    modgen.write(built, root)
    target = root / archive.loc_file("english")
    target.write_text(target.read_text(encoding="utf-8"), encoding="utf-8-sig", newline="\n")
    assert any("BOM" in p for p in modgen.check(built, root))


# ── 事实表（闸门 ④ 的两端）──────────────────────────────────
def test_数据源与产物往返一致(tmp_path: Path) -> None:
    """往返净度：数据源的事实表 == 从产物反解出来的事实表。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    assert modgen.facts(archive) == modgen.readback(built.files)


# ── 递牌信号（`[journal_entry.signals]`）：阶段 3 的修正处 ──────────────


def test_缺省不生成递牌块(tmp_path: Path) -> None:
    """没有 `[signals]` 的档案**不生成** `immediate` / `on_complete` 空块。

    空块不是"什么都没有"：`immediate = { }` 在引擎里照样是一次真实的钩子，
    而在数据源里没有任何东西支撑它。缺省应当是**不写**，不是"写个空的"。
    """
    archive = _archive(tmp_path)
    assert archive.journal_entry.signals.empty
    text = modgen.journal_text(archive)
    # 判据看的是**块**（`immediate = {`），不是这个词 —— 注释里解释机制时也会提到它。
    assert "immediate = {" not in text
    assert "on_complete = {" not in text


def test_信号生成两个块且各带一张原版牌(tmp_path: Path) -> None:
    archive = _archive(tmp_path, MINIMAL + SIGNALS)
    text = modgen.journal_text(archive)
    assert "immediate = {" in text
    assert "set_strategy = ai_strategy_progressive_agenda" in text
    assert "on_complete = {" in text
    assert "set_strategy = ai_strategy_reactionary_agenda" in text
    # 顺序：immediate 必须在 on_complete 之前（读起来才是"开 → 关"）
    assert text.index("immediate = {") < text.index("on_complete = {")


def test_递牌信号能往返(tmp_path: Path) -> None:
    """新块也要过闸门 ④ —— 否则加信号就等于绕过往返净度。"""
    archive = _archive(tmp_path, MINIMAL + SIGNALS)
    built = modgen.build(archive)
    assert modgen.facts(archive) == modgen.readback(built.files)


def test_只许递原版已有的牌(tmp_path: Path) -> None:
    """白名单是**机制约束**，不是洁癖：递自建牌要抢政治槽（每国同时只有一张牌在用）。

    这条同时钉住"我们不会不小心把自建牌写进信号" —— 报错信息里要能看出可用集合。
    """
    bad = SIGNALS.replace("ai_strategy_progressive_agenda", "ai_strategy_sitai_own_card")
    with pytest.raises(modgen.DataError, match="不在白名单里"):
        _archive(tmp_path, MINIMAL + bad)


def test_信号必须用_arg_而不是_amount(tmp_path: Path) -> None:
    """递牌递的是**标识符**，写成 `amount = 1.0` 会生成一句没人认的
    `set_strategy = 1` —— 而那正是「每个数字都有依据」（P10）最容易被绕过的地方。"""
    bad = SIGNALS.replace(
        'arg = "ai_strategy_progressive_agenda"',
        "amount = 1.0",
    )
    with pytest.raises(modgen.DataError, match="必须用 `arg` 而不是 `amount`"):
        _archive(tmp_path, MINIMAL + bad)


def test_信号表缺依据要报错(tmp_path: Path) -> None:
    """P10 对**新表**同样生效：表级与条目的 `why` 都不能空。"""
    bad = SIGNALS.replace('why = "测：为什么必须递牌（世界状态改不了已挂着的牌）"\n', "")
    with pytest.raises(modgen.DataError, match="没有 why"):
        _archive(tmp_path, MINIMAL + bad)


# ── 可见块里的递牌：`custom_tooltip` 文案（2026-10-01，D37）────────────
#
# 背景：`on_complete` / `on_fail` / `on_timeout` 三个块会被引擎渲染成详情面板的 tooltip
# （journal_entry.gui:854 `[JournalEntry.GetOnCompleteTooltip]`），而 `set_strategy` 的
# `effect_localization` 只登记了 `global`（00_country_effects_loc.txt:40-42），可见块要的是
# `first` ⇒ 裸写会把 `BUG: set_strategy missing perspective …` 当文案显示给玩家
# （2026-10-01 预检帧 tools/out/t5-frames/t8-je4-detail.png）。


def test_可见块的递牌包上自己的文案(tmp_path: Path) -> None:
    """可见块（`on_complete`）里那条递牌要包一层 `custom_tooltip = { text = <键> … }`。

    判据同时钉四件事：① 那一层真在 `on_complete` 里（不是写在别处、
    也没把 `immediate` 一起包了）；② `set_strategy` **照旧在那个块里执行**（换显示不改行为）；
    ③ 文案键真的进了两份 loc 产物（挂个没定义的键比 BUG 更难看出坏）；
    ④ 产物里不出现 `BUG:` 字样。
    """
    archive = _archive(tmp_path, MINIMAL + SIGNALS)
    text = modgen.journal_text(archive)
    assert text.index("on_complete = {") < text.index("custom_tooltip = {")
    assert text.index("custom_tooltip = {") < text.index(
        "set_strategy = ai_strategy_reactionary_agenda"
    )
    assert "text = je_sitai_t1_window_complete_tt" in text
    # `immediate` 不是 tooltip 的来源（原版 05_grunderzeit.txt:111-119 就在那里裸写）
    immediate = text[text.index("immediate = {") : text.index("on_complete = {")]
    assert "custom_tooltip" not in immediate
    built = modgen.build(archive)
    holders = [
        rel
        for rel, body in built.files.items()
        if "localization/" in rel and "je_sitai_t1_window_complete_tt" in body
    ]
    assert holders == [
        "localization/english/sitai_t1_l_english.yml",
        "localization/simp_chinese/sitai_t1_l_simp_chinese.yml",
    ], f"文案键应当进两份 loc 产物，实际 {holders}"
    # 注释里会**讨论**这个 BUG（说明为什么要包一层）—— 看的是引擎真正读的那些行
    body = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert not any("BUG:" in line for line in body)


def test_可见块的递牌缺文案键要报错(tmp_path: Path) -> None:
    """少写 `tooltip` 会让面板把引擎拼的 `BUG: …` 当文案显示出来 —— 生成时就得拦。"""
    bad = SIGNALS.replace('tooltip = "je_sitai_t1_window_complete_tt"\n', "")
    with pytest.raises(modgen.DataError, match="必须给"):
        _archive(tmp_path, MINIMAL + bad)


def test_文案键必须在本地化里定义(tmp_path: Path) -> None:
    """挂一个没定义的键 ⇒ 面板显示的是键名本身，比 BUG 更难看出坏（离线可判，所以在这儿判）。"""
    bad = SIGNALS.replace(
        'tooltip = "je_sitai_t1_window_complete_tt"',
        'tooltip = "je_sitai_t1_typo_tt"',
    )
    archive = _archive(tmp_path, MINIMAL + bad)
    with pytest.raises(modgen.DataError, match="不在本档案的"):
        modgen.build(archive)


def test_不可见块的递牌不许带文案键(tmp_path: Path) -> None:
    """反向约束：`immediate` 不渲染 tooltip，写了 `tooltip` 也没人看得见 ⇒ 报错。"""
    bad = SIGNALS.replace(
        'arg = "ai_strategy_progressive_agenda"',
        'arg = "ai_strategy_progressive_agenda"\ntooltip = "je_sitai_t1_window_complete_tt"',
    )
    with pytest.raises(modgen.DataError, match="不渲染 tooltip"):
        _archive(tmp_path, MINIMAL + bad)


def test_别处的数据表不许写_tooltip(tmp_path: Path) -> None:
    """`tooltip` 只对 `[journal_entry.signals]` 有意义：写在别处是手滑，不该静默接受。"""
    bad = MINIMAL.replace(
        'why = "测：为什么是 40"',
        'why = "测：为什么是 40"\ntooltip = "je_sitai_t1_window_complete_tt"',
    )
    with pytest.raises(modgen.DataError, match="只有"):
        _archive(tmp_path, bad)


# ── 面板三行（`[panel]`，P11 / G3）──────────────────────────


def test_缺省不生成三行键(tmp_path: Path) -> None:
    """没有 `[panel]` 的档案**不生成**那三个键（缺省 = 不写，不是"写三行空的"）。"""
    archive = _archive(tmp_path)
    assert archive.panel == ()
    built = modgen.build(archive)
    loc = built.files[next(rel for rel in built.files if rel.endswith("_l_english.yml"))]
    for slot, _suffix in modgen.PANEL_LINES:
        assert f"{archive.journal_entry.name}_{slot}" not in loc
    assert "没有** `[panel]`" in built.files[archive.doc_file]


def test_三行必须齐全(tmp_path: Path) -> None:
    """`[panel]` 是**整体**：缺一行就报错 —— 三行解释缺任何一行，G3 都复述不出来。

    这条是这一格存在的理由：把三行拆成三个键，就是为了让"缺哪一行"当场可见
    （揉进 `_reason` 里时，缺行是看不出来的）。
    """
    bad = MINIMAL + PANEL.replace("[panel.last_change]", "[panel.not_a_slot]")
    with pytest.raises(modgen.DataError, match="缺 `last_change`"):
        _archive(tmp_path, bad)


def test_三行键名由JE名派生并写进本地化与文档(tmp_path: Path) -> None:
    """键名由 JE 名派生 —— 但**只有** `PANEL_SLOTS_WITH_OWN_LOC` 那几个槽单独发键。

    `t97` 改前这条断言「三行**都**在 yml 里」，钉的是旧行为：`goal` 那一槽当时照发
    `<JE 名>_goal`，而引擎为它报 `journal_entry_type.cpp:476 Journal entry has redundant
    loc for …_goal`（只有带 goal 度量的 JE 才该有这条 loc）。改后改钉**新行为**：
    压力与上次改主意照发，`goal` **不许**出现在 yml 里；三个槽的依据照旧都要进档案文档。
    """
    archive = _archive(tmp_path, MINIMAL + PANEL)
    built = modgen.build(archive)
    name = archive.journal_entry.name
    loc = built.files[next(rel for rel in built.files if rel.endswith("_l_english.yml"))]
    for slot, suffix in modgen.PANEL_LINES:
        key = f"{name}_{suffix}"
        if slot in modgen.PANEL_SLOTS_WITH_OWN_LOC:
            assert f"{key}:0" in loc, (
                f"{slot} 那一槽该单独发键（它不在 PANEL_SLOTS_WITH_OWN_LOC？）"
            )
        else:
            assert f"{key}:0" not in loc, (
                f"{slot} 那一槽**不许**单独发键 —— 引擎会为它报 `has redundant loc`（t97）"
            )
    doc = built.files[archive.doc_file]
    assert "面板三行" in doc
    for slot, key, why in archive.panel:
        assert key in doc
        assert why in doc, f"{slot} 的依据要进档案文档（P10：人读的那一份要能逐条查）"


def test_三行接进JE说明里上屏(tmp_path: Path) -> None:
    """**三行必须真的上屏**（阶段 6 的 G3）。

    引擎显示的是 `journal_entry.gui:742` 的 `text = "[JournalEntry.GetReason]"` ⇒ 读
    `<JE 名>_reason` 这条 loc；而 `<JE 名>_goal` 那一槽**不单独发键**（`t97`：引擎会报
    `journal_entry_type.cpp:476 … has redundant loc`）。
    所以判据是：三行的文案**都在** `_reason` 里（压力 / 上次改主意另有独立键可单独核对；
    `goal` 那一行的期望值从数据源取 —— 见 :func:`_panel_text`）。
    """
    archive = _archive(tmp_path, MINIMAL + PANEL)
    built = modgen.build(archive)
    loc = built.files[next(rel for rel in built.files if rel.endswith("_l_english.yml"))]
    reason = next(
        line for line in loc.splitlines() if f"{archive.journal_entry.name}_reason" in line
    )
    for slot, key, _why in archive.panel:
        if slot in modgen.PANEL_SLOTS_WITH_OWN_LOC:
            value = next(
                entry.values["english"] for entry in archive.localization if entry.key == key
            )
        else:
            raw = modgen.read_source(_write_source(tmp_path, MINIMAL + PANEL))["panel"]
            assert isinstance(raw, dict)
            line = raw[slot]
            assert isinstance(line, dict)
            value = line["english"]
            assert isinstance(value, str)
        assert value in reason, f"{slot} 那一行没接进 JE 说明"
    # 拼接用的是**字面量** `\n\n`（两个字符）：写成真换行会把 yml 拆成多行、后几行没有 key
    assert reason.count("\\n\\n") >= len(archive.panel)
    assert len(loc.splitlines()) == len(archive.localization) + 2, (
        "每条 loc 一行（语言声明 + 注释头 + N 条）—— 多出来的行说明值里有真换行"
    )


def test_真实档案的目标那行仍在JE说明里() -> None:
    """**防复发判据①**（`t97`）：消掉冗余 loc 之后，目标那一行的文案**不许**跟着消失。

    为什么单开一条：`goal` 槽停发 loc 键之后，最容易犯的错就是"顺手把那行文字也删了" ——
    产物照样能生成、`v3 modgen --check` 照样绿，而 G3（试玩者能复述「当前目标 + 主因」）
    悄悄少了一行。这里逐份 × 逐语言核对「数据源里的目标文案确实在 `_reason` 行里」。
    """
    archives = modgen.load_all()
    built = modgen.build_all(archives)
    for archive in archives:
        name = archive.journal_entry.name
        for lang in sorted(modgen.LANGUAGES):
            loc = built.files[archive.loc_file(lang)]
            reason = next(line for line in loc.splitlines() if f"{name}_reason" in line)
            goal = _panel_text(archive, "goal", lang)
            assert goal in reason, f"{archive.id}/{lang}：目标那行没进 {name}_reason"


def test_产物里没有以goal结尾的本地化键() -> None:
    """**防复发判据②**（`t97`）：全量本地化产物里**没有**任何以 `_goal` 结尾的 loc 键。

    判据来自引擎：`journal_entry_type.cpp:476 Journal entry has redundant loc for {}_goal`
    —— 只有带 goal 度量（`goal_add_value`）的 JE 才该有这条 loc；原版 419 份 JE 里，
    有度量的 90 份中 77 份带它、**没有度量的 329 份里 0 份**带。
    扫**盘上产物**（不是内存里那份）：这条判据要能抓住"有人手改产物"或"生成器回退"两种情形。
    """
    offenders: list[str] = []
    for path in sorted(modgen.PRODUCT_DIR.joinpath("localization").rglob("*.yml")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1
        ):
            key = line.strip().split(":", 1)[0].strip()
            if key.endswith("_goal"):
                offenders.append(
                    f"{path.relative_to(modgen.PRODUCT_DIR).as_posix()}:{number} {key}"
                )
    assert not offenders, f"这些 loc 键会被引擎判冗余（t97）：{offenders}"


def test_三行文案里不许有裸双引号(tmp_path: Path) -> None:
    """`.yml` 的值用双引号包裹，引擎对转义的支持没有实测证据 ⇒ 直接拒绝（P13）。"""
    bad = MINIMAL + PANEL.replace('english = "Goal line."', 'english = "Goal \\"quoted\\" line."')
    with pytest.raises(modgen.DataError, match="裸双引号"):
        _archive(tmp_path, bad)


def test_改一个数字往返就不一致(tmp_path: Path) -> None:
    """反向：产物与数据源只要差一处，比对就必须发现（否则闸门 ④ 是空转）。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    broken = dict(built.files)
    broken[archive.modifier_file] = broken[archive.modifier_file].replace("-20", "-25")
    assert modgen.facts(archive) != modgen.readback(broken)


def test_readback不认坏掉的语法(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    broken = {archive.journal_file: "je_sitai_t1_window = { \n"}
    with pytest.raises(modgen.DataError, match="解析失败"):
        modgen.readback(broken)
    assert built.files  # 基线产物本身是好的


def test_编号格式化不产生浮点噪声() -> None:
    """`-20` 不能写成 `-20.0`，`0.2` 不能写成 `0.20000000000000001`。"""
    assert modgen.num(-20) == "-20"
    assert modgen.num(0.2) == "0.2"
    assert modgen.num(-0.15) == "-0.15"
    assert modgen.num(10.0) == "10"


# ── 多档案第一步：schema v1（`[tempo]` 可选）与 mod 级元数据 ──
def test_第二份档案只加数据行就能编译(tmp_path: Path) -> None:
    """G-EXIT-1 的机械形式：两份数据源 → 一次构建 → 产物齐、mod 级产物只一份。"""
    a, b = _two_archives(tmp_path)
    built = modgen.build_all([a, b])
    assert set(built.archive_ids) == {"t1", "t2"}
    for archive in (a, b):
        for rel in modgen.archive_files(archive):
            assert rel in built.files, f"{archive.id} 少了 {rel}"
    # mod 级产物各一份：defines 由声明 tempo 的那份产出，metadata 由两份合成
    defines = [rel for rel in built.files if rel.startswith("common/defines/")]
    assert defines == [a.defines_file], defines
    assert [rel for rel in built.files if rel == modgen.METADATA_REL] == [modgen.METADATA_REL]
    assert b.tempo is None, "第二份档案不该复制一遍 [tempo]（它是 mod 级表）"


def test_加第二份档案不改第一份的产物(tmp_path: Path) -> None:
    """加档案**只增不改**：既有档案的产物必须逐字节不变（唯一例外是 mod 级元数据）。"""
    a, b = _two_archives(tmp_path)
    one = modgen.build_all([a])
    two = modgen.build_all([a, b])
    for rel, text in one.files.items():
        if rel == modgen.METADATA_REL:
            continue
        assert two.files[rel] == text, f"加第二份档案改动了 {rel}"
    assert set(two.files) == (
        set(modgen.archive_files(a)) | set(modgen.archive_files(b)) | {modgen.METADATA_REL}
    )


def test_单档案的两个入口共用一套组合规则(tmp_path: Path) -> None:
    """`build(a)` 就是 `build_all([a])` —— 免得两条路径悄悄分叉。"""
    a = _archive(tmp_path)
    assert modgen.build(a).files == modgen.build_all([a]).files


def test_mod级元数据汇总两份档案(tmp_path: Path) -> None:
    """一份 mod = 一份元数据：标题、身份、描述都由**全部**档案导出。"""
    a, b = _two_archives(tmp_path)
    payload = json.loads(modgen.build_all([a, b]).files[modgen.METADATA_REL])
    assert payload["id"] == "sitai.t1-t2", "档案 id 按字典序用 `-` 连接"
    assert "测试档案" in payload["name"]
    assert "第二档案" in payload["name"]
    assert payload["short_description"].count("测：这份档案修什么毛病") == 2
    assert payload["supported_game_version"] == "1.14.3"


def test_没有档案声明tempo报错(tmp_path: Path) -> None:
    """`defines` 是全局的：整份 mod 没有节奏段这件事必须显式，不能靠少一个产物表达。"""
    archive = _archive(tmp_path, MINIMAL.replace(TEMPO_BLOCK, ""))
    assert archive.tempo is None
    with pytest.raises(modgen.DataError, match=r"没有任何数据源声明 \[tempo\]"):
        modgen.build_all([archive])


def test_两份档案都声明tempo报错(tmp_path: Path) -> None:
    """两份都写 `[tempo]` → 报错并**点名两个文件**（否则谁生效取决于加载顺序）。"""
    a, b = _two_archives(tmp_path, tempo=True)
    assert a.tempo is not None
    assert b.tempo is not None
    with pytest.raises(modgen.DataError, match="只允许一份") as excinfo:
        modgen.build_all([a, b])
    assert "a.toml" in str(excinfo.value)
    assert "b.toml" in str(excinfo.value)


def test_游戏版本不一致报错(tmp_path: Path) -> None:
    """一份 mod 只有一个 `supported_game_version`：不一致说明数据源在骗人。"""
    a, b = _two_archives(tmp_path, game_version="1.15.3")
    with pytest.raises(modgen.DataError, match="game_version"):
        modgen.build_all([a, b])


# ── 真实触发接线（B35）与投降叠加档 ──────────────────────────────
#: 追加到 :data:`MINIMAL` 后面的"真实触发接线"（可选表 `[trigger]`，backlog B35）。
#: 接线之前记账效果**只有探针一条入口**：什么才算"这次战败"由实验给结论。接线之后
#: 判据落在原版自己写的记号上（见 :data:`ESCALATION`），探针降为**仪器通道**。
TRIGGER = """
[trigger]
why = "测：为什么记账效果必须由原版事件真的调用"

[[trigger.hooks]]
on_action = "on_capitulation"
scope = "this"
why = "测：这条钩子的 root 就是投降国，判据与施加都用 this"

[[trigger.hooks]]
on_action = "on_wargoal_enforced"
scope = "scope:target"
why = "测：这条钩子的 root 是赢的一方，记账只能落在 scope:target 上"
"""

#: 追加到 :data:`MINIMAL` 后面的"投降叠加档"（可选表 `[pressure.escalation]`）。
#: 判据是**原版自己写的记号**（`recent_capitulation`），不是我们的实验设置 ⇒
#: 撤掉探针之后这条线仍然只在真实投降后额外挂上。
ESCALATION = """
[pressure.escalation]
variable = "recent_capitulation"
modifier = "sitai_t1_pressure_capitulation"
why = "测：为什么判据用原版记号而不是我们自己的变量"
[[pressure.escalation.effects]]
key = "country_legitimacy_base_add"
amount = -15
why = "测：为什么叠加档取 -15"
"""

#: 接线 + 叠加档都声明的数据源（真实档案 `ru_defeat` 的形状）。
WIRED = MINIMAL + TRIGGER + ESCALATION


def _block_of(item: Assignment | None) -> Block:
    """把一条赋值当**块**取出来（不是块就当场失败 —— "应该是块"这种事要显式）。"""
    assert item is not None
    assert isinstance(item.value, Block)
    return item.value


def _hook_block(archive: modgen.Archive, on_action: str) -> Block:
    """接线产物里某条**原版钩子**那个块（顶层）。"""
    assert archive.trigger is not None
    parsed = parse_text(modgen.trigger_text(archive), path=archive.trigger_file)
    assert not parsed.errors, parsed.errors
    item = parsed.root.first(on_action)
    assert item is not None, f"接线产物里没有 {on_action}"
    return _block_of(item)


def _wrapper_if(archive: modgen.Archive, on_action: str) -> Block:
    """包装 on_action 里那个 `if` 块（判据与施加都在这）。"""
    assert archive.trigger is not None
    parsed = parse_text(modgen.trigger_text(archive), path=archive.trigger_file)
    assert not parsed.errors, parsed.errors
    wrapper = _block_of(parsed.root.first(archive.hook_wrapper(on_action)))
    effect = _block_of(wrapper.first("effect"))
    return _block_of(effect.first("if"))


def test_没声明trigger就不产出接线产物(tmp_path: Path) -> None:
    """**其余九份档案逐字节不变**的结构性理由：没有 `[trigger]` 就一个字节都不多产。"""
    archive = _archive(tmp_path)
    assert archive.trigger is None
    assert not [
        rel for rel in modgen.archive_files(archive) if rel.startswith("common/on_actions/")
    ]
    built = modgen.build(archive)
    assert not [rel for rel in built.files if rel.startswith("common/on_actions/")]


def test_声明trigger就产出接线且无BOM(tmp_path: Path) -> None:
    """仓库 trigger 接线产物保持无 BOM，安装边界负责游戏编码。"""
    archive = _archive(tmp_path, WIRED)
    assert archive.trigger is not None
    assert archive.trigger_file == "common/on_actions/sitai_t1_on_actions.txt"
    assert archive.trigger_file in modgen.archive_files(archive)
    built = modgen.build(archive)
    root = tmp_path / "mod"
    modgen.write(built, root)
    written = (root / archive.trigger_file).read_bytes()
    assert not written.startswith(b"\xef\xbb\xbf"), "仓库接线产物必须无 BOM"
    assert modgen.check(built, root) == []
    text = built.files[archive.trigger_file]
    parsed = parse_text(text, path=archive.trigger_file)
    assert not parsed.errors, parsed.errors
    assert set(parsed.top_keys) == {
        "on_capitulation",
        "on_wargoal_enforced",
        "sitai_t1_on_capitulation",
        "sitai_t1_on_wargoal_enforced",
    }


def test_接线只给原版钩子追加on_actions字段(tmp_path: Path) -> None:
    """官方文档写明不能给已有 `effect` 的 on_action 再追加 `effect` 块（冲突），

    官方给的写法就是加 `on_actions` 字段 ⇒ 这里钉住"原版字段一字不动"这条性质：
    钩子块里**只有** `on_actions`，没有 `effect` / `events` 这类替换性的键。
    """
    archive = _archive(tmp_path, WIRED)
    for on_action in ("on_capitulation", "on_wargoal_enforced"):
        block = _hook_block(archive, on_action)
        assert [a.full_key for a in block.assignments()] == ["on_actions"]
        inner = _block_of(block.first("on_actions"))
        assert [s.unquoted for s in inner.scalars()] == [archive.hook_wrapper(on_action)]


def test_root钩子的判据是本国(tmp_path: Path) -> None:
    """`on_capitulation` 的 root 就是投降国 ⇒ 判据 `c:RUS ?= this`，就地施加。"""
    archive = _archive(tmp_path, WIRED)
    condition = _wrapper_if(archive, "on_capitulation")
    assert [a.full_key for a in condition.assignments()] == ["limit", archive.memory.effect]
    limit = _block_of(condition.first("limit"))
    assert [a.full_key for a in limit.assignments()] == ["c:RUS"]
    assert "c:RUS ?= this" in modgen.trigger_text(archive)


def test_具名scope的路径拿不到root记账(tmp_path: Path) -> None:
    """`on_wargoal_enforced` 的 root 是**赢的一方**：记账只能落在 `scope:target`。

    这是结构性保证（不是约定）：root 那一层根本没有 `sitai_t1_shock = yes` 这条语句。
    """
    archive = _archive(tmp_path, WIRED)
    condition = _wrapper_if(archive, "on_wargoal_enforced")
    assert [a.full_key for a in condition.assignments()] == ["limit", "scope:target"], (
        "root 层只有判据与 scope 块 —— 记账效果不在这一层"
    )
    scoped = _block_of(condition.first("scope:target"))
    assert [a.full_key for a in scoped.assignments()] == [archive.memory.effect]
    assert "scope:target ?= c:RUS" in modgen.trigger_text(archive)


def test_冲击效果的注释如实写调用方(tmp_path: Path) -> None:
    """注释是产物唯一的说明面：接线之后不能再写"刻意不绑 on_action"。"""
    wired = _archive(tmp_path / "wired", WIRED)
    text = modgen.effects_text(wired)
    assert "调用方：原版事件（on_capitulation、on_wargoal_enforced）" in text
    assert wired.trigger_file in text
    assert "仪器通道" in text
    plain = modgen.effects_text(_archive(tmp_path / "plain"))
    assert "刻意**不绑 on_action**" in plain
    assert "仪器通道" not in plain


def test_叠加档只在原版记号命中时才挂(tmp_path: Path) -> None:
    """叠加档不是"实验设置"，是真实结果 ⇒ 判据必须是原版自己写的记号。"""
    archive = _archive(tmp_path, WIRED)
    escalation = archive.pressure.escalation
    assert escalation is not None
    shock = modgen.effects_text(archive)
    assert "has_variable = recent_capitulation" in shock
    years = next(item for item in archive.pressure.params if item.key == "years")
    assert shock.count(f"years = {modgen.num(years.amount)}") == 2, "基线档 + 叠加档同一段窗口"

    parsed = parse_text(modgen.modifier_text(archive), path=archive.modifier_file)
    assert not parsed.errors, parsed.errors
    assert set(parsed.top_keys) == {archive.pressure.name, escalation.modifier}
    block = _block_of(parsed.root.first(escalation.modifier))
    assert [a.full_key for a in block.assignments()] == [
        "icon",
        *[item.key for item in escalation.effects],
    ]
    icon = block.first("icon")
    assert icon is not None
    assert str(icon.value) == archive.pressure.icon, "同一族修正用同一个图标"


def test_叠加档能过往返(tmp_path: Path) -> None:
    """闸门 ④ 的两端：叠加档的每个字段都必须既能写出、也能反解。"""
    archive = _archive(tmp_path, WIRED)
    built = modgen.build(archive)
    assert modgen.facts(archive) == modgen.readback(built.files)
    facts = dict(modgen.facts(archive))
    escalation = archive.pressure.escalation
    assert escalation is not None
    assert facts[f"modifier.{escalation.modifier}.country_legitimacy_base_add"] == "-15"
    prefix = f"effects.{archive.memory.effect}.if[0]"
    assert facts[f"{prefix}.limit.has_variable"] == escalation.variable
    assert facts[f"{prefix}.add_modifier.name"] == escalation.modifier
    assert facts[f"{prefix}.add_modifier.years"] == modgen.num(
        next(item for item in archive.pressure.params if item.key == "years").amount
    )


def test_真实档案里只有ru_defeat接线() -> None:
    """接线是**按档案**可选的：没声明的档案连目录都不该多出来。"""
    archives = modgen.load_all()
    assert [a.id for a in archives if a.trigger is not None] == ["ru_defeat"]
    built = modgen.build_all(archives)
    assert [rel for rel in built.files if rel.startswith("common/on_actions/")] == [
        "common/on_actions/sitai_ru_defeat_on_actions.txt"
    ]


def test_真实档案的钩子与scope逐条对上() -> None:
    """真实 `ru_defeat`：两条原版路径 + 各自的 scope（改数据源就必须改这里）。"""
    archive = next(a for a in modgen.load_all() if a.id == "ru_defeat")
    assert archive.trigger is not None
    assert [(h.on_action, h.scope) for h in archive.trigger.hooks] == [
        ("on_capitulation", "this"),
        ("on_wargoal_enforced", "scope:target"),
    ]
    assert archive.trigger_file == "common/on_actions/sitai_ru_defeat_on_actions.txt"
    text = modgen.trigger_text(archive)
    assert "c:RUS ?= this" in text
    assert "scope:target ?= c:RUS" in text
    for hook in archive.trigger.hooks:
        block = _hook_block(archive, hook.on_action)
        assert [a.full_key for a in block.assignments()] == ["on_actions"]
        assert _wrapper_if(archive, hook.on_action).first("limit") is not None


def test_真实档案的叠加档排在难度分支之前() -> None:
    """叠加档插在压力基线之后、难度分支之前 ⇒ 难度分支的 `if[index]` 编号要加偏移。

    这条偏移是"事实表"与"反解器"两边各自算一遍的，所以必须钉住（错一位就静默错配）。
    """
    archive = next(a for a in modgen.load_all() if a.id == "ru_defeat")
    escalation = archive.pressure.escalation
    assert escalation is not None
    assert archive.difficulty is not None
    built = modgen.build(archive)
    parsed = parse_text(built.files[archive.effect_file], path=archive.effect_file)
    assert not parsed.errors, parsed.errors
    shock = _block_of(parsed.root.first(archive.memory.effect))
    branches = shock.all("if")
    assert len(branches) == 1 + len(archive.difficulty.tiers_with_player_effects())
    first_limit = _block_of(_block_of(branches[0]).first("limit"))
    second_limit = _block_of(_block_of(branches[1]).first("limit"))
    assert [a.full_key for a in first_limit.assignments()] == ["has_variable"]
    assert first_limit.first("has_variable") is not None
    assert second_limit.first("is_ai") is not None, "第二条起才是难度分支"
    facts = dict(modgen.facts(archive))
    effect = archive.memory.effect
    assert facts[f"effects.{effect}.if[0].limit.has_variable"] == escalation.variable
    assert f"effects.{effect}.if[1].limit.has_game_rule" in facts
    assert modgen.facts(archive) == modgen.readback(built.files)


def test_叠加档缺years当场报错(tmp_path: Path) -> None:
    """叠加档与基线必须是**同一段窗口**：寿命错开是最难查的一类不一致。"""
    text = MINIMAL.replace(
        '[[pressure.params]]\nkey = "years"', '[[pressure.params]]\nkey = "decade_count"'
    )
    with pytest.raises(modgen.DataError, match="years"):
        modgen.build(_archive(tmp_path, text + ESCALATION))


def test_叠加档modifier必须在sitai命名空间(tmp_path: Path) -> None:
    """F7：新加的每一个游戏侧名字都必须落在 `sitai_` 命名空间里。"""
    bad = ESCALATION.replace(
        'modifier = "sitai_t1_pressure_capitulation"', 'modifier = "t1_pressure_capitulation"'
    )
    with pytest.raises(modgen.DataError, match="sitai_"):
        _archive(tmp_path, MINIMAL + bad)


def test_钩子scope只许this或原版具名scope(tmp_path: Path) -> None:
    """scope 写错会安静地判错人（比如把赢的一方当成投降国）⇒ 解析期就报错。"""
    bad = TRIGGER.replace('scope = "scope:target"', 'scope = "root"')
    with pytest.raises(modgen.DataError, match="scope"):
        _archive(tmp_path, MINIMAL + bad)


def test_同一个钩子重复声明当场报错(tmp_path: Path) -> None:
    """同一条钩子两条判据 ⇒ 说不清该按哪个，别让它安静地生成两份接线。"""
    text = """
[trigger]
why = "测：为什么同一条钩子只能声明一次"
[[trigger.hooks]]
on_action = "on_capitulation"
scope = "this"
why = "测：第一次声明"
[[trigger.hooks]]
on_action = "on_capitulation"
scope = "scope:target"
why = "测：第二次声明（判据不同 ⇒ 说不清该按哪个）"
"""
    with pytest.raises(modgen.DataError, match="同一个钩子出现多次"):
        _archive(tmp_path, MINIMAL + text)


def test_trigger没有hooks当场报错(tmp_path: Path) -> None:
    """没有钩子的接线是空产物：声明了这张表就必须真接上。"""
    text = """
[trigger]
why = "测：为什么没有钩子的接线是空产物"
"""
    with pytest.raises(modgen.DataError, match="至少要有一条 hooks"):
        _archive(tmp_path, MINIMAL + text)


def _idempotent_sites(block: Block) -> int:
    """数这一层里的 `add_modifier`，并断言它**前一条兄弟**是 `remove_modifier = 同名`。

    递归进 `if`：叠加档与难度档的 `add_modifier` 就嵌在 `if` 里，那才是挂两次的地方。
    """
    items = list(block.assignments())
    found = 0
    for index, item in enumerate(items):
        value = item.value
        if item.key == "if" and isinstance(value, Block):
            found += _idempotent_sites(value)
            continue
        if item.key != "add_modifier":
            continue
        found += 1
        assert isinstance(value, Block), "add_modifier 必须是块"
        inner = value
        name = inner.first("name")
        assert name is not None, "add_modifier 必须带 name"
        target = str(name.value)
        assert index > 0, f"{target}：这一层的第一个赋值就是 add_modifier ⇒ 不会先删"
        previous = items[index - 1]
        assert previous.key == "remove_modifier", (
            f"{target} 的前一条是 {previous.key}，不是 remove_modifier —— "
            "同一个效果被两条原版钩子调用时会挂两次（修正翻倍）"
        )
        assert str(previous.value) == target, (
            f"删的是 {previous.value}，挂的是 {target} —— 名字不一致等于没删"
        )
    return found


def test_每个add_modifier前面先删同名() -> None:
    """幂等记账：每个 `add_modifier = { name = X … }` 的前一条兄弟必须是 `remove_modifier = X`。

    为什么这条性质必须由生成器保证（1.14.5 实测因果）：`ru_defeat` 的冲击效果挂在
    **两条**原版钩子上（`on_capitulation` + `on_wargoal_enforced`），而原版注释
    （`game/common/on_actions/00_code_on_actions.txt:6280-6284`）写明
    `on_wargoal_enforced` 也涵盖 capitulation ⇒ 投降那一局两条都触发、同一个效果跑两遍。
    不先删就会把同一个修正挂两次：修正页签出现同名同寿命两行、压力翻倍，而阶段 3 的
    A/B 标定是**单次施加**。原版同款写法见
    `game/common/scripted_effects/00_strike_effects.txt:63-78`（无守卫连删同名修正 ——
    删一个不存在的修正是空操作，所以不需要 `has_modifier` 守卫）。
    """
    archives = modgen.load_all()
    checked = 0
    for archive in archives:
        parsed = parse_text(modgen.effects_text(archive), path=archive.effect_file)
        assert not parsed.errors, parsed.errors
        for effect in parsed.root.assignments():
            block = _block_of(effect)
            assert block is not None, f"{effect.key} 必须是块"
            checked += _idempotent_sites(block)
    assert checked >= len(archives) * 2, (
        f"覆盖面太小：只查到 {checked} 处 add_modifier（{len(archives)} 份档案，至少各 2 处）"
    )
