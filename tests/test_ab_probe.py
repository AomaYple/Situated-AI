"""``pdx.ab_probe`` 的用例：臂阶梯探针是**生成**的，生成物本身要被钉住。

重点不是"文件写出来了"，而是五件事：

* **阶梯只有一处定义**（`LADDER`）：探针文本、分析器的角色表、文档都从它派生；
* **换臂是幂等的**：`stage` 单调递增，每个效果只施加一次（重复脉冲、读档、重点决议
  都不能把同一处输入叠两遍）；
* **两处输入分开施加**：B 段只调冲击、B2 段才调改革侧输入 —— 合在一起就分不出
  是哪一处起了作用；
* **0 张牌**（F5：能改世界就不占槽）；
* **生成物能被仓库自己的解析器读懂**，且引用的效果名与**数据源**同源（P9）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pdx import ab_probe, ai_surface, config, modgen
from pdx.parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.unit

_EMPTY_GAME = Path("Z:/不存在的游戏目录")

_EFFECTS = "common/scripted_effects/zz_probe_ab_effects.txt"
_ON_ACTIONS = "common/on_actions/zz_probe_ab_on_actions.txt"
_DECISIONS = "common/decisions/zz_probe_ab_decisions.txt"


def _files() -> dict[str, str]:
    return ab_probe.build(game=_EMPTY_GAME).files


def _target() -> ab_probe.ProbeTarget:
    """当前探针实际盯的那份档案（**从数据源读**）—— 断言一律对着它，不写死国家名。"""
    target = ab_probe.load_target()
    assert target is not None, "读不到 mod/data 里的档案"
    return target


def _code(text: str) -> str:
    """去掉注释行后的**代码**（注释里会解释规则，不该被当成实现来断言）。"""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def _block(code: str, name: str) -> str:
    """取一个顶层定义的**全文**（从 `name = {` 到行首那个收尾的 `}`）。

    不能用 `split("}")[0]`：块里还有嵌套的 `{ … }`（`set_variable` 之类），
    切在第一个 `}` 上会把定义截掉一半。
    """
    start = code.index(f"{name} = {{")
    end = code.index("\n}", start)
    return code[start:end]


def _date(text: str) -> tuple[int, int, int]:
    """`"1841.6.1"` → `(1841, 6, 1)`（比字符串比大小可靠：'1836.10.1' < '1836.6.1'）。"""
    year, month, day = (int(part) for part in text.strip('"').split("."))
    return (year, month, day)


# ── 阶梯的定义（唯一一处）────────────────────────────────────


def test_阶梯是三臂且起始月单调() -> None:
    """A → B → B2 的起始月必须递增，且只有第一臂没有效果（对照组什么都不做）。"""
    assert ab_probe.ROLES == ("A", "B", "B2")
    assert ab_probe.ARM_START == {"A": 1, "B": 13, "B2": 37}
    starts = [step.at_month for step in ab_probe.LADDER]
    assert starts == sorted(starts)
    assert ab_probe.LADDER[0].effect is None
    assert [step.effect for step in ab_probe.LADDER[1:]] == [
        ab_probe.SHOCK_EFFECT,
        ab_probe.INPUT_EFFECT,
    ]


def test_探针引用的效果与数据源同源() -> None:
    """P9：探针调用的效果名/修正名必须与 `mod/data/*.toml` 生成出来的完全一致。

    写错一个字母的表现是 `Unknown effect`（引擎只在 error.log 里说一句），
    而那正是开局自检要抓的东西 —— 不如在这里就钉住。
    """
    archive = modgen.load_data(modgen.DATA_DIR / "ru_defeat.toml")
    assert archive.memory.effect == ab_probe.SHOCK_EFFECT
    assert archive.memory.variable == ab_probe.SHOCK_VAR
    assert archive.inputs is not None, "数据源里必须有第二处理段（B2 靠它）"
    assert archive.inputs.effect == ab_probe.INPUT_EFFECT
    assert archive.inputs.name == ab_probe.INPUT_MODIFIER


# ── 效果文件：武装 + 阶梯（幂等）──────────────────────────────


def test_效果文件里不能出现on_action包装() -> None:
    """阶段 2 的挂载点事故：效果文件里的 `effect = {` 会让定义整段作废、脚本侧毫无报错。"""
    assert "effect = {" not in _code(_files()[_EFFECTS])


def test_武装效果写A段标记并把计数器清零() -> None:
    code = _code(_files()[_EFFECTS])
    arm = _block(code, "zz_probe_ab_arm")
    assert "ZZPROBE AB;RUN;A" in arm
    assert f"set_variable = {{ name = {ab_probe.MONTH_VAR} value = 0 }}" in arm
    assert f"set_variable = {{ name = {ab_probe.STAGE_VAR} value = 1 }}" in arm


def test_阶梯按月推进且带阶段守卫生效一次() -> None:
    """幂等是硬要求：`stage <= N` 的守卫保证每个效果**只施加一次**。"""
    text = _files()[_EFFECTS]
    code = _code(text)
    ladder = code.split("zz_probe_ab_ladder = {")[1]
    assert f"has_variable = {ab_probe.STAGE_VAR}" in ladder  # 没被武装就不动
    target = _target()
    for index, step in enumerate(ab_probe.ladder_for(target)[1:], start=1):
        assert f"var:{ab_probe.STAGE_VAR} <= {index}" in ladder
        assert f"var:{ab_probe.MONTH_VAR} >= {step.at_month}" in ladder
        assert f"ZZPROBE AB;RUN;{step.role}" in ladder
        # 换臂那一月：先把 stage 推进，再施加效果（否则下一月会再施加一次）
        assert ladder.index(f"value = {index + 1}") < ladder.index(f"{step.effect} = yes")


def test_月份计数器只由自励与决议推进() -> None:
    """⚠️ **月份 `+1` 只能有一处**（2026-09-22 改）：从前它在阶梯里，而阶梯要靠决议武装 ——
    观察者局里决议点不了 ⇒ 月份永远不动 ⇒ 整条臂阶梯一次都不走（阶段 3 的结构性阻断）。
    现在推进挪进 `zz_probe_ab_selfarm`，阶梯只读月份。两处都自增会让月份走两倍快。
    """
    code = _code(_files()[_EFFECTS])
    bump = f"change_variable = {{ name = {ab_probe.MONTH_VAR} add = 1 }}"
    assert code.count(bump) == 1, "月份自增必须只有一处"
    selfarm = code.split("zz_probe_ab_selfarm = {")[1].split("zz_probe_ab_ladder = {")[0]
    assert bump in selfarm
    assert bump not in code.split("zz_probe_ab_ladder = {")[1]


def test_自励只对AI生效且让决议优先() -> None:
    """自励是**观察者局**的入口；玩家自己掌权时它必须完全不介入（决议是唯一入口）。"""
    selfarm = _code(_files()[_EFFECTS]).split("zz_probe_ab_selfarm = {")[1]
    assert "is_ai = yes" in selfarm
    assert f"NOT = {{ has_variable = {ab_probe.MANUAL_VAR} }}" in selfarm
    # 决议那边要写下"我武装过"的标记，否则自励会盖掉玩家那一路
    arm = _code(_files()[_EFFECTS]).split("zz_probe_ab_arm = {")[1].split("zz_probe_ab_selfarm")[0]
    assert f"set_variable = {{ name = {ab_probe.MANUAL_VAR} value = 1 }}" in arm


def test_自励的每一格都幂等且按月份排序() -> None:
    selfarm = _code(_files()[_EFFECTS]).split("zz_probe_ab_selfarm = {")[1]
    target = _target()
    steps = [step for step in ab_probe.ladder_for(target)[1:] if step.effect]
    months = [step.at_month for step in steps]
    assert months == sorted(months), "自励的月份必须单调，否则顺序写反就读不懂"
    for index, step in enumerate(steps, start=1):
        month, effect = step.at_month, step.effect
        assert f"var:{ab_probe.SELFARM_VAR} < {index}" in selfarm
        assert f"var:{ab_probe.MONTH_VAR} >= {month}" in selfarm
        assert f"{effect} = yes" in selfarm


@pytest.mark.skipif(not config.GAME.is_dir(), reason="游戏目录不可用")
def test_每月都记当前政治牌() -> None:
    """B53：牌才是"动不动手"的闸门 ⇒ 牌必须是**逐月的行为层读数**，不许从别处反推。

    ⚠️ 这条测试**以前只问手写清单里的三张牌**，于是清单漏掉
    `ai_strategy_egalitarian_agenda` 时它照样绿（B87）。现在两个方向都问：
    ① 原版政治槽**每一张**牌都得被问到（候选集现读，不是手写）；
    ② 兜底那两条也在 —— 否则"这张牌不在清单里"会变成日志里的**沉默**，
    而沉默与"没有牌"长得一模一样。

    必须用**真游戏**生成（空目录读不到牌表，那是另一条路径），
    所以这条是集成用例而不是纯单元用例。
    """
    vanilla = ai_surface.read_cards(config.GAME)
    assert vanilla, "读不到原版 AI 面 —— 这条测试的前提没了"
    code = _code(ab_probe.build(game=config.GAME).files[_ON_ACTIONS])
    cards = ab_probe.strategy_candidates(vanilla)
    assert cards, "原版政治槽一张牌都没有？候选集是现读的，空了说明读法坏了"
    assert "ai_strategy_egalitarian_agenda" in cards, (
        "白名单里递得出去的牌必须在读数链里 —— 它曾经漏掉，表现是这个月一行都不记"
    )
    for name in cards:
        assert f"has_strategy = {name}" in code, name
        assert f"ZZPROBE AB;STRATEGY;{name};" in code, name
    assert "ZZPROBE AB;STRATEGY;ai_strategy_default;" in code
    assert "ZZPROBE AB;STRATEGY;none;" in code, "兜底那行没了 ⇒ 分不清'没记'与'没有牌'"


def test_我们自己的牌插在自报链链首且逐月留痕() -> None:
    """我们自己的牌必须排 `ai_strategy_default` **之前**（`if / else_if` 命中即停）。

    这条顺序是"能不能看见命中"的**充要条件**，而它原先**没有任何用例守着**：
    把插入位置挪到末尾，引擎真选中我们的牌时日志里出现的仍是那张原版牌
    （前面的分支先命中）⇒ 读出来正好是"牌没被选中"这种最难查的假象。
    同时钉住 ④·补 那条诊断：两个分支都要写（含 `none`），否则分不清"没被选中"与"没记"。
    """
    our = "ai_strategy_sitai_probe_order_test"
    # 用**真的** `ai_surface.Card`（不是假对象）：`on_actions_text` 的形参标着
    # `list[ai_surface.Card]`，而 mypy 开着 —— 假牌会多出一条 `arg-type`
    # （本仓 `warn_unused_ignores = true`，所以拿 `# type: ignore` 糊更差）。
    vanilla = [
        ai_surface.Card(
            name="ai_strategy_conservative_agenda",
            slot="political",
            file="<test>",
            line=1,
            weight_base=20.0,
            weight_terms=0,
            has_possible=True,
            fields=(),
            weight_inputs=(),
            possible_inputs=(),
            field_inputs=(),
        )
    ]
    code = _code(ab_probe.on_actions_text(vanilla, _target(), own=[our]))
    assert "has_strategy = ai_strategy_conservative_agenda" in code, "假牌没进生成物？"
    assert f"has_strategy = {our}" in code
    assert code.index(f"has_strategy = {our}") < code.index("has_strategy = ai_strategy_default"), (
        "我们的牌排到了 default 之后 —— 命中即停 ⇒ 永远读不到它（B87 同族）"
    )
    assert f"ZZPROBE AB;{ab_probe.CARD_KIND};{our.removeprefix('ai_strategy_')};" in code
    assert f"ZZPROBE AB;{ab_probe.CARD_KIND};none;" in code, (
        "没有 none 分支 ⇒ 分不清'我们的牌没被选中'与'这一格没记'"
    )


def test_自己的牌为零时只写一行none而不是悬空else() -> None:
    """0 张牌那条路径（**今天就是它**：九份档案都是 0 张，F5 的结果）也要留痕。

    没有配对的 `if` 就不能有 `else` —— 引擎会报错。所以空集走**裸行**；这条用例
    把那条路径钉住，免得将来有人图省事改成"空集就不写"，把可观测性悄悄丢掉。
    """
    empty = ab_probe.own_card_chain([])
    assert f"ZZPROBE AB;{ab_probe.CARD_KIND};none;" in empty
    assert "if = {" not in empty, "空集不许写悬空 else"
    assert "else" not in empty, "空集不许写悬空 else"

    one = ab_probe.own_card_chain(["ai_strategy_sitai_one"])
    assert "if = {" in one
    assert "else_if = {" not in one
    assert "else = {" in one

    two = ab_probe.own_card_chain(["ai_strategy_sitai_a", "ai_strategy_sitai_b"])
    assert "if = {" in two
    assert "else_if = {" in two
    assert "else = {" in two
    assert f"{ab_probe.CARD_KIND};none;" in two, "多张时也要有兜底那行"


@pytest.mark.skipif(not config.GAME.is_dir(), reason="游戏目录不可用")
def test_递牌白名单的牌都在原版政治槽里() -> None:
    """我们自己递牌的**白名单**必须是原版真有的政治牌（B87 的根因那一半）。

    这条把两个来源钉在一起：`modgen.SET_STRATEGY_WHITELIST`（我们能递什么）
    与 `common/ai_strategies/*.txt`（原版有什么）。任一边悄悄变了都会红 ——
    白名单里多一张不存在的牌 = 生成物写了一辈子也不会生效的 `set_strategy`；
    少一张真牌 = 那条路线根本递不出去（而读数链也读不到它）。
    """
    whitelist = set(modgen.SET_STRATEGY_WHITELIST)
    political = set(ab_probe.strategy_candidates(ai_surface.read_cards(config.GAME)))
    missing = sorted(whitelist - political)
    assert not missing, (
        f"白名单里的牌不在原版政治槽：{missing}\n原版政治槽实际有：{sorted(political)}"
    )


def test_每月都记立法开没开() -> None:
    """「牌换了法不换」的三个候选（缺政府支持 / 怕革命 / 权重不够）在
    「每月只记法律名」的读数下**长得一模一样** ⇒ 必须直接记 `is_enacting_law`。

    它把「从未开立法」与「开了没成」分开，是三选一的分辨器。
    ⚠️ 而**没有「任意法」的通用写法**（exe 检索 5 个候选名全 0 命中）⇒ 只能逐条问，
    所以这里钉住"每条候选法都要问一遍"，以及"全没推时也要留一行 `none`"。
    """
    code = _code(_files()[_ON_ACTIONS])
    assert ab_probe.ENACT_LAWS, "候选法清单不能空 —— 空了这条读数就没意义"
    for law in ab_probe.ENACT_LAWS:
        assert f"is_enacting_law = law_type:{law}" in code, law
    assert "ZZPROBE AB;ENACT;none;" in code, "全没推时也要留一行（否则分不清'没记'与'没开'）"
    # 两条土地法是这条链的正主，必须在候选表里
    assert "law_tenant_farmers" in ab_probe.ENACT_LAWS
    assert "law_commercialized_agriculture" in ab_probe.ENACT_LAWS


def test_每月都记政府在谁手里() -> None:
    """若「缺政府支持」那一支成立，就得能看见政府在谁手里。"""
    code = _code(_files()[_ON_ACTIONS])
    for name, short in ab_probe.GOVERNMENT_IGS:
        assert f"ig:{name} ?= {{ is_in_government = yes }}" in code, name
        assert f"ZZPROBE AB;GOV;{short};" in code, short


def test_clout_档位名是两位百分数() -> None:
    assert ab_probe.clout_band_name(0.03) == "b03"
    assert ab_probe.clout_band_name(0.18) == "b18"
    assert ab_probe.clout_band_name(0.25) == "b25"
    assert [ab_probe.clout_band_name(b) for b in ab_probe.CLOUT_BANDS] == [
        "b03",
        "b08",
        "b12",
        "b18",
        "b25",
    ]


def test_每月都记入阁距离() -> None:
    """`is_in_government` 只有真/假，**看不出离入阁有多远** ⇒ 用 `ig_clout` 夹逼成档。

    没有这一格，"再加一点压力够不够"这个问题在二元读数下无法回答
    （阶段 3 重做的结论正卡在这里）。
    """
    code = _code(_files()[_ON_ACTIONS])
    # 写成 "相等" 而不是 `sorted(...) == CLOUT_BANDS`：这里要断言的就是**顺序**，
    # 反转过来会让失败信息难读（SIM300 的默认建议对"对称比较"是过度约束）。
    assert ab_probe.CLOUT_BANDS == tuple(sorted(ab_probe.CLOUT_BANDS)), "档位必须升序"  # noqa: SIM300
    for name, short in ab_probe.CLOUT_IGS:
        for band in ab_probe.CLOUT_BANDS:
            label = ab_probe.clout_band_name(band)
            assert f"ig:{name} ?= {{ ig_clout >= {band} }}" in code, (name, band)
            assert f"ZZPROBE AB;CLOUT;{short};{label};" in code, (name, label)
    # 改革派两个 IG 必须在表里（地主留作对照）
    shorts = {short for _name, short in ab_probe.CLOUT_IGS}
    assert {"intelligentsia", "industrialists", "landowners"} <= shorts


def test_生成物的大括号是配平的() -> None:
    """CLOUT 那一格是**成对生成**的（`if = {` + `}`）—— 用 f-string 拼多行时最容易漏掉收尾。

    实测踩过（2026-09-22）：把 `if` 与 `}` 写在同一个 f-string 里再靠 `\\n` 拼，
    生成出来的 `}` 会落到错误的位置，整个 on_action 的块结构就散了。
    """
    for rel in (_ON_ACTIONS, _EFFECTS):
        text = _files()[rel]
        assert text.count("{") == text.count("}"), f"{rel} 的大括号不配平"


def test_自报里不做整体缩进重排() -> None:
    """PDX 脚本对缩进不敏感，但**嵌套块被整体右移**会生成"双倍缩进"，读起来像语法错误。

    实测（2026-09-22）：三槽自报链以前被 `.replace("\\n" + tab*2, "\\n" + tab*3)` 整体
    右移 → `if` 里的 `if` 变成两层缩进叠在一起。

    判据形状：**每一层缩进都必须真的对应一层块**。这里用"三槽自报链里不许出现三层以上缩进"
    来钉 —— 那条链最深就是 `guarded(if)` 里一层 `if`，所以 4 个 tab 是它的上限
    （`ENACT` 那一段有个 `OR` 会到 6 个 tab，那是**真的**四层嵌套，不在本判据范围内）。
    """
    text = _files()[_ON_ACTIONS]
    start = text.index("# ② 再走臂阶梯")
    end = text.index("# ④ 当前挂着的政治牌")
    chain_section = text[start:end]
    assert "\t\t\t\t\t" not in chain_section, "三槽自报链里出现 5 层缩进 ⇒ 多半又整体重排了"


def test_两处输入各调各的效果() -> None:
    """B 段只调冲击、B2 段才调改革侧输入 —— 分开才能把差分归因到某一处。"""
    target = _target()
    ladder = _code(_files()[_EFFECTS]).split("zz_probe_ab_ladder = {")[1]
    b_block = ladder.split('RUN;B"')[1].split('RUN;B2"')[0]
    b2_block = ladder.split('RUN;B2"')[1]
    assert f"{target.shock_effect} = yes" in b_block
    assert f"{target.input_effect} = yes" not in b_block
    assert f"{target.input_effect} = yes" in b2_block
    assert f"{target.shock_effect} = yes" not in b2_block


# ── 决议：一个就够 ───────────────────────────────────────────


def test_只有一个决议且远程作用于主角国家() -> None:
    code = _code(_files()[_DECISIONS])
    defined = re.findall(r"(?m)^(\w+) = \{", code)
    assert defined == ["zzprobe_ab_apply"], "只该有一个决议（点一次武装整条阶梯）"
    assert "is_shown = { always = yes }" in code  # 对任何玩家可见（玩家演旁观者）
    assert f"c:{_target().subject} ?= {{" in code  # 效果**远程**作用于主角国家
    assert "ai_chance = { value = 0 }" in code
    assert "zz_probe_ab_arm = yes" in code


def test_探针不定义任何牌() -> None:
    """F5：牌写在**真档案**的数据源里（`[cards]`），探针一个都不许**定义**。

    ⚠️ 判据的**形态**在 2026-09-25（t18）改过一次，如实写在案：原来是「任何探针文件里
    都不许出现 `ai_strategy_sitai_` 这个**子串**」—— 那时本 mod 的政治槽是空的，子串检查
    恰好等价。t18 落了第一张真牌（`ai_strategy_sitai_ru_defeat_agenda`）之后，探针**会照
    设计去读它**（`own_cards()` 从产物现读、`chain` 把它排在链首）⇒ 子串必然出现。
    判据因此改成「不许出现 `ai_strategy_*` 的**定义块**」：**读**是设计，**定义**才是越界。
    （t18 的 test 0 专测牌曾短暂破例，已按 t15 §1.4「用完即撤」撤掉。）
    """
    for rel, text in _files().items():
        defined = set(re.findall(r"(?m)^(\w+) = \{", text))
        offenders = sorted(name for name in defined if name.startswith("ai_strategy_"))
        assert not offenders, (rel, offenders)


def test_真牌被读进自报链且排在兜底之前() -> None:
    """t18：真牌落进数据源之后，探针的读数**必须看得到它**（不是只在合成臂里成立）。

    与 `test_我们自己的牌插在自报链链首且逐月留痕` 的分工：那条用**合成的**牌验证链的
    顺序语义；这条用**真产物**（`own_cards()` 现读 `mod/common/ai_strategies/`）验证
    「数据源 → 产物 → 探针读数」这条端到端链路真的接通了 —— 它是本卡验收第 6 条
    （自报链路两条都给）的机器钉子。
    """
    code = _code(_files()[_ON_ACTIONS])
    ours = ab_probe.own_cards()
    assert ours, "真档案里一张政治槽牌都没有 —— 要么数据源没落，要么 own_cards 读法坏了"
    for name in ours:
        assert f"has_strategy = {name}" in code, f"{name} 没被读进自报链"
    first = f"has_strategy = {ours[0]}"
    assert code.index(first) < code.index("has_strategy = ai_strategy_default"), (
        "我们的牌排在兜底之后 —— 命中即停的链会把它盖住"
    )


# ── 月度自报：只记俄罗斯，且换臂在自报之前 ───────────────────


def test_on_actions引用的tag都在同一文件里定义() -> None:
    code = _code(_files()[_ON_ACTIONS])
    defined = set(re.findall(r"(?m)^(\w+) = \{", code))
    referenced: set[str] = set()
    for match in re.finditer(r"on_actions = \{([^}]*)\}", code):
        referenced |= set(match.group(1).split())
    assert referenced, "一个钩子都没挂上"
    assert referenced <= defined, sorted(referenced - defined)
    # 起点是"玩家点决议"，**不在开局自动挂**（否则大厅/读档阶段也会算进 A 臂）
    assert "on_game_started" not in code


def test_阶梯排在自报之前() -> None:
    """换臂那一月必须算进新臂 —— RUN 行要排在同月的 SHOCK/JE/LAW 之前。"""
    text = _files()[_ON_ACTIONS]
    assert text.index("zz_probe_ab_ladder = yes") < text.index("ZZPROBE AB;SHOCK;")
    assert text.index("zz_probe_ab_ladder = yes") < text.index("ZZPROBE AB;JE;")
    assert text.index("zz_probe_ab_ladder = yes") < text.index("ZZPROBE AB;POLI;")


def test_行为层与策略层都记了且都只在主角国家() -> None:
    target = _target()
    text = _files()[_ON_ACTIONS]
    assert f"has_journal_entry = {target.journal_entry}" in text  # 行为层①
    for law in ab_probe.LAWS:  # 行为层②
        assert f"has_law = law_type:{law}" in text
    for short in ("POLI", "ADMI", "DIPL"):  # 策略层
        assert f"ZZPROBE AB;{short};" in text
    # 策略层也要在守卫内（否则全世界每月刷 3 行日志）
    assert text.index(f"c:{target.subject} ?= this") < text.index("ZZPROBE AB;POLI;")
    # 玩家是谁必须能被诊断出来（开错国家时开局一分钟就知道）
    assert "ZZPROBE AB;PLAYER;yes;" in text
    # 两处输入各一行"在/不在"自检（B2 段少了它，第③节的无差分会被误读）
    assert f"has_variable = {target.shock_variable}" in text
    assert f"has_modifier = {target.input_modifier}" in text
    for kind in ("SHOCK", "INPUT"):
        assert f"ZZPROBE AB;{kind};yes;" in text
        assert f"ZZPROBE AB;{kind};no;" in text
    # 诊断行：**合法性数值**（2026-09-24 起不再只记五档夹逼）
    assert "ZZPROBE AB;LEGV;" in text
    assert "[THIS.GetCountry.GetGovernmentLegitimacy|v]" in text, (
        "读数值靠的是原版自己的 data function —— 原版提示就是这么打的"
        "（alerts_l_english.yml 的 [GetPlayer.GetGovernmentLegitimacy|v]）"
    )
    # 各 IG 的政治力量同样读数值（旧的 CLOUT 档位保留，老归档还要能读）
    for name, short in ab_probe.CLOUT_IGS:
        assert f"GetInterestGroupOfType('{name}').GetClout|%1" in text, name
        assert f"ZZPROBE AB;CLOUTV;{short};" in text, name
        assert f"ZZPROBE AB;CLOUT;{short};" in text, name


def test_数值读数用的是原版验证过的调用形状() -> None:
    """**形状**必须照抄原版，不能自己编：编错的 data function 会静默变成字面量。

    `[InterestGroup.GetClout|%1]`（customized_tooltips）、
    `GetCountry.GetInterestGroupOfType('ig_…')`（cohesion_levels）都是原版逐字用过的，
    所以这三个片段必须同时出现在生成物里。
    """
    text = _files()[_ON_ACTIONS]
    assert "GetGovernmentLegitimacy|v" in text
    assert "GetClout|%1" in text
    assert "GetInterestGroupOfType('" in text


# ── scripted_tests 套件（引擎侧判定）────────────────────────


def test_套件判据贴合我们的两条判据() -> None:
    """success = 开窗 / 换法；fail = 到日期仍未发生（不是"跳过"）。"""
    target = _target()
    text = _files()[ab_probe.SUITE_REL]
    assert f"has_journal_entry = {target.journal_entry}" in text
    assert f"NOT = {{ has_law = law_type:{target.reform_law} }}" in text, (
        "行为层②必须按**本档案声明的**那条法判（B80）—— 写死 `law_serfdom` 时，"
        "对没有农奴制的国家它立刻为真，会报出假的「法律换了」"
    )
    assert f"c:{target.subject} ?= {{" in text
    assert text.count("run_count = 1") == 2
    assert text.count("acceptable_fail_rate = 0.0") == 2
    assert text.count("game_date >") == 2


def test_没声明盯哪条法就不产出那条判据() -> None:
    """**没查实就不判**（B80）：奥斯曼/埃及的历史文件里没有土地法那一组（实测）⇒
    套件里干脆不出现 `law_changed`，而不是写一条会对它们立刻为真的判据。
    """
    import dataclasses

    plain = dataclasses.replace(_target(), reform_law="")
    built = ab_probe.build(game=_EMPTY_GAME, target=plain)
    suite = built.files[ab_probe.SUITE_REL]
    assert "law_changed" not in suite
    assert "没有" in suite, "要留一句注释说明为什么没有它"
    assert "reform_law" in suite, "注释里要点名要加什么"
    assert suite.count("run_count = 1") == 1, "只该剩开窗那一条"


def test_探针把盯的档案写进日志() -> None:
    """分析器靠 `ZZPROBE AB;TARGET;<档案 id>` 认主语（B80）。

    为什么不能靠国名：自报行的最后一格是**本地化国名**（实测是「波斯」），不是 tag；
    而 `[This.GetTag]` 不是合法的 loc 命令。探针本来就是为某一份档案生成的，
    所以让它直接写那个常量。
    """
    target = _target()
    effects = _files()[_EFFECTS]
    assert f"ZZPROBE AB;TARGET;{target.archive_id}" in effects
    other = ab_probe.load_target("cn_intervention")
    assert other is not None
    rebuilt = ab_probe.build(game=_EMPTY_GAME, target=other)
    assert f"ZZPROBE AB;TARGET;{other.archive_id}" in rebuilt.files[_EFFECTS]


def test_套件的fail日期早于last_date() -> None:
    """到 last_date 两个触发器都没命中 → 判「跳过」：fail 的日期必须更早。

    否则"没发生"永远不会被报成失败 —— 而那正是我们要判的那件事。
    """
    text = _files()[ab_probe.SUITE_REL]
    last = _date(re.search(r'last_date = ("[^"]+")', text).group(1))  # type: ignore[union-attr]
    fails = [_date(value) for value in re.findall(r'game_date > ("[^"]+")', text)]
    assert fails, "一条 fail 判据都没有"
    assert all(moment < last for moment in fails), (fails, last)


def test_原版套件都被收敛覆盖() -> None:
    """引擎会跑 tools/scripted_tests/ 下的**每一份**套件：原版那几套跑到 1870–1900 年。"""
    files = _files()
    for name in ab_probe.VANILLA_SUITES:
        rel = f"tools/scripted_tests/{name}.txt"
        assert rel in files
        text = files[rel]
        last = _date(re.search(r'last_date = ("[^"]+")', text).group(1))  # type: ignore[union-attr]
        assert last <= _date('"1836.2.1"'), f"{name} 的 last_date 还是太晚：{last}"
        assert "tests = {\n}\n" in text, f"{name} 的 tests 该清空"


# ── 写盘、部署、摘要 ─────────────────────────────────────────


def test_写盘无BOM且能被解析器读懂(tmp_path: Path) -> None:
    ab_probe.write(root=tmp_path, game=_EMPTY_GAME)
    seen = 0
    for path in sorted(tmp_path.rglob("*")):
        if not path.is_file():
            continue
        seen += 1
        if path.suffix in {".txt", ".yml"}:
            assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), path.name
            if path.suffix == ".txt":
                parsed = parse_text(path.read_text(encoding="utf-8-sig"), path=str(path))
                assert parsed.top_assignments, path.name
        elif path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
    assert seen == len(_files())


def test_部署会连同真mod一起启用(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """真 mod 的**目录名由档案 id 拼出来**（P9）—— 从前写死 `sitai_ru_defeat`，
    加第二份档案时就会装错目录，而"装错目录"的表现是"探针报 Unknown effect"，
    看起来像效果名写错了。
    """
    seen: list[list[str]] = []
    target = ab_probe.load_target()
    assert target is not None, "仓库里必须能读到档案数据源"

    def fake_set(paths: Iterable[Path | str], **_kw: object) -> None:
        seen.append([str(p) for p in paths])

    monkeypatch.setattr(ab_probe.experiments, "set_enabled_mods", fake_set)
    root = tmp_path / "mod"
    (root / target.dir_name).mkdir(parents=True)  # 假装真 mod 已装
    dest = ab_probe.deploy(root=tmp_path / "src", target=root, game=_EMPTY_GAME)
    assert dest == root / ab_probe.PROBE_MOD
    assert (dest / "common" / "on_actions" / "zz_probe_ab_on_actions.txt").is_file()
    assert (dest / "tools" / "scripted_tests" / "sitai_ab.txt").is_file()
    assert seen[-1] == [str(dest), str(root / target.dir_name)]


def test_摘要写清整条阶梯() -> None:
    text = ab_probe.summary(ab_probe.build(game=_EMPTY_GAME))
    for role in ab_probe.ROLES:
        assert role in text
    assert "第 13 月起" in text
    assert "第 37 月起" in text


# ── 探针盯谁：从**数据源**读，不手抄（P9）─────────────────────


def test_目标从数据源读出来() -> None:
    """探针原来硬编码 `SUBJECT = "RUS"` / JE 名 / 效果名 —— 加第二份档案时会漂。

    现在全部由 `modgen` 从 `mod/data/*.toml` 编译出来，这条用例钉住"读得到、且与档案一致"。
    """
    from pdx import modgen

    target = ab_probe.load_target()
    assert target is not None
    archives = modgen.load_all()
    first = archives[0]
    assert target.subject == first.country, "默认目标 = 数据源里的第一份档案"
    assert target.journal_entry == first.journal_entry.name
    assert target.shock_effect == first.memory.effect
    assert target.shock_variable == first.memory.variable
    assert first.inputs is not None
    assert target.input_effect == first.inputs.effect
    assert target.dir_name == "-".join(archive.id for archive in archives)


def test_可以点名要哪一份档案() -> None:
    """阶段 5 起 `mod/data/` 里有多份档案 ⇒ 探针必须能**显式选一份**。

    点名了却没有就**报错**，不许"回落到第一份" —— 那会让人以为探针盯的是 A、实际盯的是 B。
    """
    from pdx import modgen

    wanted = modgen.load_all()[0].id
    picked = ab_probe.load_target(archive_id=wanted)
    assert picked is not None
    assert picked.archive_id == wanted
    with pytest.raises(KeyError, match="没有档案"):
        ab_probe.load_target(archive_id="zzz_不存在")


def test_生成的探针里不含写死的国家名() -> None:
    """判据是**反面**：产物里出现别的国家的 tag 就说明有一条路没走 target。"""
    target = _target()
    files = ab_probe.build(game=_EMPTY_GAME).files
    on_actions = files[_ON_ACTIONS]
    assert f"c:{target.subject}" in on_actions  # 守卫就是这一份档案的国家
    assert f"has_journal_entry = {target.journal_entry}" in on_actions
    # 自报用的判据必须是**数据源里的那一份**（变量名 / 修正名）
    assert f"has_variable = {target.shock_variable}" in on_actions
    assert f"has_modifier = {target.input_modifier}" in on_actions
    # 要调的那两个效果名出现在阶梯里（`on_actions` 只负责挂钩与自报）
    effects = files[_EFFECTS]
    assert f"{target.shock_effect} = yes" in effects
    assert f"{target.input_effect} = yes" in effects


def test_造别的国家的探针只需换一个_target() -> None:
    """G-EXIT-1 的口径：加一处境 = 加数据行，**Python 侧 0 行改动**。

    这里用一个合成的 target 证明"换国家"确实只是换一个值（不需要改生成器）。
    """
    custom = ab_probe.ProbeTarget(
        dir_name="t9",
        subject="AUS",
        journal_entry="je_sitai_t9_window",
        shock_effect="sitai_t9_shock",
        shock_variable="sitai_t9_memory",
        input_effect="sitai_t9_reform_input",
        input_modifier="sitai_t9_reform_inputs",
        archive_id="t9",
    )
    files = ab_probe.build(game=_EMPTY_GAME, target=custom).files
    assert "c:AUS" in files[_ON_ACTIONS]
    assert "c:RUS" not in files[_ON_ACTIONS]
    assert "je_sitai_t9_window" in files[_ON_ACTIONS]
    assert "has_variable = sitai_t9_memory" in files[_ON_ACTIONS], "冲击自检要问**这份档案**的变量"
    assert "has_variable = sitai_ru_defeat_memory" not in files[_ON_ACTIONS]
    assert "c:AUS" in files[ab_probe.SUITE_REL]
    assert "c:AUS" in files["common/decisions/zz_probe_ab_decisions.txt"]


def test_读不到数据源时不猜一个国家名(monkeypatch: pytest.MonkeyPatch) -> None:
    """P13：读不到就报错 —— 拿猜出来的国家名生成探针，会让"它在盯谁"变成看不出来的错。"""
    monkeypatch.setattr(ab_probe, "load_target", lambda: None)
    with pytest.raises(RuntimeError, match="不能猜一个国家名"):
        ab_probe.build(game=_EMPTY_GAME)


def test_元数据是合法JSON() -> None:
    data = json.loads(ab_probe.metadata_text())
    assert "A→B→B2" in data["short_description"]
    # 探针与真 mod 一起加载 ⇒ 声明的游戏版本必须同源（曾经写死 1.14.3，mod 升到 1.14.4 后
    # 启动器会对探针弹版本警告，看起来像探针坏了）。
    declared = [archive.game_version for archive in modgen.load_all()]
    assert declared, "读不到数据源"
    assert data["supported_game_version"] == declared[0]
    assert len(set(declared)) == 1, "各档案声明的 game_version 必须一致（modgen 会强制）"


def test_探针源目录在仓库内() -> None:
    assert ab_probe.PROBE_DIR == config.REPO / "tools" / "probe" / ab_probe.PROBE_MOD


def test_难度档位的逐月读数两族行都在() -> None:
    """阶段 6 口径 §3.3 第 1 条：`RULE` 互斥链 + 三档各自的 yes/no，两族都要有。

    缺任何一族都是**静默失真**：
    * 只有三档各自的行 ⇒ 读不出"这一局到底挂在哪一档"；
    * 只有互斥链 ⇒ 另两档**一个月都不出现**，而"没记"与"没有"分不开（B87 同族）——
      承重判据要的正是「harsh;yes **且**另两档 no」这个**组合**。

    还要钉住 kind 的划分：三档各自的读数**不能**都叫 `RULE`（`pdx.ab` 里
    `rows[key][kind] = parts[0]` 会让同 kind 的三行互相覆盖，只剩最后一行）。
    """
    code = _code(ab_probe.difficulty_rule_lines())
    for setting in ab_probe.DIFFICULTY_SETTINGS:
        assert f"has_game_rule = {setting}" in code, setting
    else_if_count = len(ab_probe.DIFFICULTY_SETTINGS) - 1
    assert code.count("else_if = {") == else_if_count, "互斥链必须是 if / else_if… / else 一条链"
    assert "else = {" in code, "没有 else 兜底 ⇒「一档都没命中」会变成一行都不记"
    for short, _setting in zip(ab_probe.RULE_SHORTS, ab_probe.DIFFICULTY_SETTINGS, strict=True):
        kind = ab_probe.RULE_KINDS[short]
        assert kind != "RULE", "三档各自的读数必须各有 kind（同 kind 会互相覆盖）"
        assert f"ZZPROBE AB;{kind};yes;" in code, kind
        assert f"ZZPROBE AB;{kind};no;" in code, f"{kind} 缺 no 分支"
    # 🔧 2026-09-25 随字面量同步（t88 之后设置名不再带 `setting_` 前缀）：
    #    这条断言原来写的是 `RULE;setting_sitai_difficulty_harsh;yes;`，而 t88 的目标量是
    #    **不带前缀**的 `sitai_difficulty_harsh` ⇒ 断言与生成物必须同时改，否则红的是"用例
    #    记着旧名"而不是"代码坏了"（今天这一族已经栽过：把字面量的毛病记到被测对象头上）。
    assert "ZZPROBE AB;RULE;sitai_difficulty_harsh;yes;" in code, (
        "互斥链命中那一档要写**设置名**（口径 §3.3 要逐字摘录这一行）"
    )
    assert "ZZPROBE AB;RULE;setting_sitai_difficulty_harsh;yes;" not in code, (
        "带 `setting_` 前缀的旧设置名不许再出现（t88 之后会静默判错、走 else 兜底）"
    )
    assert "ZZPROBE AB;RULE;none;yes;" in code


# ── t90：探针字面量 ↔ 真 mod 产物（**外部参照**，不是自参照）──────────────────
#
# 上面那条用例的参照物是 `DIFFICULTY_SETTINGS` **自己** —— 数据源改名而探针没跟时它照样
# 是绿的。这一组把参照物换成**产物**（`mod/common/game_rules/*_difficulty.txt`，`v3 modgen`
# 落盘、闸门 ⑤ 保证与数据源逐字节一致）。t90 的形状：两侧都有串、一条都对不上 ⇒ 引擎里三个
# `if has_game_rule` 全不命中、走 `else` 写一行 `RULE;none;yes`：看起来「有读数」，
# 实际什么都没证（B87「没记与没得分不开」/ B85「没看到被当成没有」同族）。
#
# ⚠️ 两种失败**不是一回事**，用例也分开（2026-09-29 队长口径）：
# * **「一行都没有」** = 产物侧压根读不到设置名（没生成 / 这份 mod 没有难度表）；
# * **「命中 0 条」** = 两侧都有串、一条都对不上（且实机仍会写 `RULE;none;yes`）。


def _difficulty_root(base: Path, names: Iterable[str]) -> Path:
    """造一份只含难度规则的**产物根**（`common/game_rules/*_difficulty.txt`）。

    形状照真产物（`mod/common/game_rules/sitai_ru_defeat_difficulty.txt:9-21`）：
    顶层规则块 + 每档一个设置块、块名与 `flag` 同串。
    """
    tiers = list(names)
    blocks = "\n".join(f"\t{name} = {{\n\t\tflag = {name}\n\t}}" for name in tiers)
    path = base / "common" / "game_rules" / "sitai_x_difficulty.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"sitai_difficulty = {{\n\tdefault = {tiers[0]}\n\n{blocks}\n}}\n", encoding="utf-8"
    )
    return base


def test_难度档位字面量与真mod产物同串() -> None:
    """探针写死的三档设置名与产物 `flag` 必须**逐字同串、顺序也一致**。

    顺序也要钉：短名靠 `zip(RULE_SHORTS, DIFFICULTY_SETTINGS, strict=True)` 对上 kind，
    顺序错位会让「是哪一档」记到另一档头上（读数还在，只是记错了人）。
    """
    names = ab_probe.mod_difficulty_settings()
    assert names, "产物里读不到难度设置名 —— 先跑 `v3 modgen --write`"
    assert names == ab_probe.DIFFICULTY_SETTINGS, (
        f"探针字面量 {ab_probe.DIFFICULTY_SETTINGS} ≠ 产物 flag {names}"
        " ⇒ 实机只会写 RULE;none;yes（看起来有读数，实际什么都没证）"
    )
    check = ab_probe.difficulty_check()
    assert check.ok, check.text()
    assert check.missing == (), check.text()
    assert check.extra == (), check.text()


def test_互斥链里的每一条都是产物里的设置名() -> None:
    """参照物换成产物：产物改名而探针文本没跟 ⇒ 这条红（自参照那条不会红）。"""
    code = _code(ab_probe.difficulty_rule_lines())
    chain = code.split("else = {")[0]  # 互斥链那一族（到 else 兜底之前）
    for name in ab_probe.mod_difficulty_settings():
        assert f"has_game_rule = {name}" in chain, f"{name} 不在互斥链里"
    assert chain.count("has_game_rule = ") == 3, "互斥链就是三档各一条"


def test_档位名错一个字符就判红_阴性对照(tmp_path, monkeypatch) -> None:
    """**阴性对照**：三条方向都必须真红、且红的时候点名是哪一串。"""
    # ① 产物侧错一个字符（模拟数据源改名后 `v3 modgen --write` 过）
    root = _difficulty_root(
        tmp_path / "mod",
        ("sitai_difficulty_history_friendly", "sitai_difficulty_uniform", "sitai_difficulty_harsH"),
    )
    check = ab_probe.difficulty_check(root)
    assert not check.ok, "产物改名了还判绿 ⇒ 这条防线是假的"
    assert check.missing == ("sitai_difficulty_harsh",), check.text()
    assert check.extra == ("sitai_difficulty_harsH",), check.text()
    assert "sitai_difficulty_harsH" in check.text()
    assert "对不上" in check.text()
    assert "命中 0 条" not in check.text(), "只错一档 ≠ 一条都对不上"

    # ② 探针侧错一个字符（对**真产物**改字面量 —— 改了数据源却忘了改探针的那一半）
    monkeypatch.setattr(
        ab_probe,
        "DIFFICULTY_SETTINGS",
        (*ab_probe.DIFFICULTY_SETTINGS[:2], "sitai_difficulty_harsH"),
    )
    check = ab_probe.difficulty_check()
    assert not check.ok
    assert check.missing == ("sitai_difficulty_harsH",), check.text()
    assert check.extra == ("sitai_difficulty_harsh",), check.text()
    with pytest.raises(RuntimeError, match="对不上"):
        ab_probe.build(game=_EMPTY_GAME)

    # ③ 旧 `setting_` 前缀（t88 之前那套名字）⇒ **命中 0 条**，文案与「一行都没有」分开
    monkeypatch.setattr(
        ab_probe,
        "DIFFICULTY_SETTINGS",
        (
            "setting_sitai_difficulty_history_friendly",
            "setting_sitai_difficulty_uniform",
            "setting_sitai_difficulty_harsh",
        ),
    )
    check = ab_probe.difficulty_check()
    assert check.hits == (), "旧前缀与真产物一条都对不上"
    text = check.text()
    assert "命中 0 条" in text
    assert "RULE;none;yes" in text
    assert "一行都没有" not in text, "两种失败模式不许共用文案"
    assert "setting_sitai_difficulty_harsh" in text, "报错要点名探针那一侧的串"
    assert "sitai_difficulty_harsh" in text, "报错要点名产物那一侧的串"
    with pytest.raises(RuntimeError, match="命中 0 条"):
        ab_probe.build(game=_EMPTY_GAME)


def test_产物里一行都没有时与命中0条分开说(tmp_path, monkeypatch) -> None:
    """「一行都没有」≠「命中 0 条」：前者是产物侧压根读不到设置名。

    这一支不许写成「对不上」（那会把「没生成产物 / 这份 mod 没有难度表」两件事都记到
    「名字写错」头上 —— 与把工具的毛病记到被测对象头上同族）。这一支同样在生成期拦住。
    """
    empty = tmp_path / "没有产物"
    check = ab_probe.difficulty_check(empty)
    assert check.mod == ()
    assert not check.ok
    text = check.text()
    assert "一行都没有" in text
    assert "命中 0 条" not in text, "两种失败模式不许共用文案"
    assert "v3 modgen --write" in text, "要给出可照做的下一步"

    monkeypatch.setattr(ab_probe, "MOD_ROOT", empty)
    with pytest.raises(RuntimeError, match="一行都没有"):
        ab_probe.build(game=_EMPTY_GAME)


# ── 判别性实验模式（t18 第 10 条）与读数判决（t18 第 15 条）──────────────────
#
# 这一族用例存在的原因：B 臂 0/13 当时**没有任何程序会叫**（读数只在人脑子里判），
# 而"门到底开没开"连一行自报都没有 ⇒ 一个 0 命中可以被读成三种完全不同的东西。
# 下面的用例把两件事钉死：① 控制局的产物里必须有那几行、且**不许**设记忆变量；
# ② 判决函数在"门开而 0 命中 / 应出现而 0 次 / 没有读数 / 模式不符"四种情况下都要判红。


def _control_files() -> dict[str, str]:
    return ab_probe.build(game=_EMPTY_GAME, mode=ab_probe.MODE_CONTROL).files


def test_控制模式的效果文件也不许调冲击效果() -> None:
    target = _target()
    control = _control_files()
    assert f"{target.shock_effect} = yes" not in _code(control[_EFFECTS]), (
        "控制局的阶梯必须是空的：台阶 B 会设记忆变量 ⇒ JE 窗口开 ⇒ 档案的直置会跑 ⇒ 隔离失效"
    )
    assert f"{target.shock_effect} = yes" in _code(_files()[_EFFECTS]), "自然模式的阶梯要留着"
    assert "本局是控制局" in control[_EFFECTS]
    assert "本局是控制局" not in _files()[_EFFECTS], "自然模式的文件头不许写控制局那一段"


def test_控制模式才生成defines与两张哨兵牌() -> None:
    natural = _files()
    control = _control_files()
    for rel in ab_probe.MODE_ONLY_FILES:
        assert rel not in natural, f"natural 模式不该生成 {rel}"
        assert rel in control, f"control 模式必须生成 {rel}"


def test_风暴覆盖只动那两个键且值写死() -> None:
    text = _control_files()["common/defines/zz_probe_ab_defines.txt"]
    assert text.count("NAI = {") == 1, "按「块 + 参数」覆盖：只许一个 NAI 块，不复制原版 00_ai.txt"
    code = _code(text)
    assert "CHANGE_STRATEGY_THRESHOLD = 1" in code
    assert "CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE = 100" in code
    assert "CHANGE_STRATEGY_THRESHOLD = 100" not in code, (
        "原版值只许出现在注释里（用来说明为什么改）"
    )


def test_哨兵窗口不重叠且先变量门后修正门() -> None:
    assert ab_probe.SENTINEL_OPEN_MONTHS[1] < ab_probe.SENTINEL_GATE_MONTHS[0], (
        "两个 10000 权重的哨兵同时在池里时谁赢是随机的 ⇒ 窗口必须不重叠，否则两件事说不清"
    )
    open_card = _control_files()["common/ai_strategies/zz_probe_ab_sentinel_open.txt"]
    gate_card = _control_files()["common/ai_strategies/zz_probe_ab_sentinel_gate.txt"]
    assert f"has_variable = {ab_probe.SENTINEL_OPEN_VAR}" in open_card
    assert "has_modifier" not in open_card, "哨兵①只测「有没有重掷」，不要混进门的形状"
    assert f"has_modifier = {_target().pressure_modifier}" in gate_card, (
        "哨兵②的门必须**逐字**是真牌那一行（否则测的不是同一件事）"
    )


def test_控制模式只挂压力修正而不设记忆变量() -> None:
    target = _target()
    code = _code(_control_files()[_ON_ACTIONS])
    assert f"add_modifier = {{ name = {target.pressure_modifier} years = 10 }}" in code
    assert f"{target.shock_effect} = yes" not in code, (
        "控制局不许调冲击效果：它会设记忆变量 ⇒ JE 窗口开 ⇒ 档案那条 set_strategy 直置会跑，"
        "直置与重掷就再也分不开（这正是 B 臂 0/13 不可归因的原因之一）"
    )
    assert f"has_variable = {target.shock_variable}" in code, (
        "变量读那一行要留着（用来证明确实没设）"
    )


def test_两种模式都有门直读与逐牌yesno行() -> None:
    target = _target()
    for files in (_files(), _control_files()):
        code = _code(files[_ON_ACTIONS])
        assert f"has_modifier = {target.pressure_modifier}" in code, "门直读（第 10 条 (a)）"
        assert "ZZPROBE AB;GATE;yes;" in code
        assert "ZZPROBE AB;GATE;no;" in code, "两向都要写"
        for name in ab_probe.own_cards():
            assert f"ZZPROBE AB;HELD;{name}=yes;" in code, f"{name} 缺显式 yes（第 10 条 (b)）"
            assert f"ZZPROBE AB;HELD;{name}=no;" in code, f"{name} 缺显式 no"


def test_模式与节奏逐月自报() -> None:
    for files, mode, storm in (
        (_files(), "natural", "no"),
        (_control_files(), "control", "yes"),
    ):
        code = _code(files[_ON_ACTIONS])
        assert f"ZZPROBE AB;MODE;{mode};" in code
        assert f"ZZPROBE AB;STORM;{storm};" in code


def test_未知模式就地报错() -> None:
    with pytest.raises(ValueError, match="不是合法模式"):
        ab_probe.active_mode({"V3_AB_MODE": "nope"})
    with pytest.raises(ValueError, match="未知模式"):
        ab_probe.build(game=_EMPTY_GAME, mode="nope")


def test_没有压力修正的档案不许生成控制模式() -> None:
    import dataclasses

    bare = dataclasses.replace(_target(), pressure_modifier="")
    with pytest.raises(RuntimeError, match="pressure"):
        ab_probe.build(game=_EMPTY_GAME, target=bare, mode=ab_probe.MODE_CONTROL)


def test_切回自然模式会清掉控制模式留下的文件(tmp_path: Path) -> None:
    ab_probe.write(root=tmp_path, game=_EMPTY_GAME, mode=ab_probe.MODE_CONTROL)
    left = [rel for rel in ab_probe.MODE_ONLY_FILES if (tmp_path / rel).is_file()]
    assert left == list(ab_probe.MODE_ONLY_FILES), "控制模式的产物应当落盘"
    ab_probe.write(root=tmp_path, game=_EMPTY_GAME, mode=ab_probe.MODE_NATURAL)
    assert [rel for rel in ab_probe.MODE_ONLY_FILES if (tmp_path / rel).is_file()] == [], (
        "切回 natural 必须把 defines 与哨兵牌删掉 —— 否则下一局会静默带着每周重抽的节奏"
    )


def test_控制模式的产物过探针形状体检() -> None:
    from pdx import probe_lint

    if not config.GAME.is_dir():  # pragma: no cover - 没有游戏树的机器只能跳过
        pytest.skip("这台机器没有游戏树，形状体检交给 preflight")
    assert probe_lint.failures(probe_lint.lint(_control_files(), game=config.GAME)) == []


# ── 读数判决（第 15 条：必须能判红，且"不知道"也算红）─────────────────────

_CARD = "ai_strategy_sitai_ru_defeat_agenda"


def _line(kind: str, value: str) -> str:
    return f"[09:00:00][jomini_effect_impl.cpp:454]: ZZPROBE AB;{kind};{value};俄罗斯"


def _month_rows(
    *,
    gate: str,
    hit: bool = False,
    card: str = _CARD,
    mode: str = "control",
    storm: str = "yes",
    sentinels: tuple[tuple[str, str], ...] = (),
) -> list[str]:
    rows = [
        _line("ROLE", "RUS"),
        _line("GATE", gate),
        _line("MODE", mode),
        _line("STORM", storm),
        _line("HELD", f"{card}={'yes' if hit else 'no'}"),
    ]
    rows += [_line("SENT", f"{name}={value}") for name, value in sentinels]
    return rows


def _report(months: int, *, gate: str = "yes", hit_from: int = 0) -> str:
    rows: list[str] = []
    for index in range(1, months + 1):
        rows += _month_rows(gate=gate, hit=bool(hit_from) and index >= hit_from)
    return "\n".join(rows)


def test_门开而命中0必须判红() -> None:
    verdict = ab_probe.card_verdict(
        ab_probe.parse_rows(_report(13)), card=_CARD, expect="appear", expect_mode="control"
    )
    assert verdict.status == "red_gate_open_no_hits"
    assert not verdict.ok
    assert (verdict.months, verdict.gate_yes, verdict.gate_no, verdict.hits) == (13, 13, 0, 0)
    assert "进不了政治槽" in verdict.report(), "判红的理由要能直接读懂下一步查什么"


def test_门开而命中就是通过() -> None:
    verdict = ab_probe.card_verdict(
        ab_probe.parse_rows(_report(13, hit_from=5)),
        card=_CARD,
        expect="appear",
        expect_mode="control",
    )
    assert verdict.status == "pass_appeared"
    assert verdict.ok
    assert verdict.first_hit_month == 5


def test_应出现而0次且门一次都没开也判红() -> None:
    verdict = ab_probe.card_verdict(ab_probe.parse_rows(_report(12, gate="no")), card=_CARD)
    assert verdict.status == "red_gate_closed_no_hits"
    assert not verdict.ok


def test_没有门读数或没有这张牌的读数都算红() -> None:
    rows_without_gate: list[str] = []
    for _index in range(1, 4):
        rows_without_gate += [row for row in _month_rows(gate="yes") if "GATE" not in row]
    verdict = ab_probe.card_verdict(ab_probe.parse_rows("\n".join(rows_without_gate)), card=_CARD)
    assert verdict.status == "red_no_gate_reading", "老探针的读数不许被当成「牌没被选中」"
    stranger = ab_probe.card_verdict(ab_probe.parse_rows(_report(3)), card="ai_strategy_不存在的牌")
    assert stranger.status == "red_no_card_reading"
    assert not stranger.ok


def test_模式或节奏对不上就判红() -> None:
    rows = ab_probe.parse_rows(_report(4, hit_from=1))
    assert ab_probe.card_verdict(rows, card=_CARD, expect_mode="natural").status == (
        "red_mode_mismatch"
    )
    assert ab_probe.card_verdict(rows, card=_CARD, expect_storm="no").status == "red_storm_mismatch"


def test_期望缺席时出现也判红() -> None:
    rows = ab_probe.parse_rows(_report(4, hit_from=3))
    verdict = ab_probe.card_verdict(rows, card=_CARD, expect="absent")
    assert verdict.status == "red_appeared_when_absent"
    assert not verdict.ok
    assert ab_probe.card_verdict(
        ab_probe.parse_rows(_report(4)), card=_CARD, expect="absent"
    ).status == ("pass_absent")


def test_哨兵与真牌分开判() -> None:
    rows: list[str] = []
    for index in range(1, 5):
        sentinels = (
            (ab_probe.SENTINEL_OPEN, "yes" if index <= 2 else "no"),
            (ab_probe.SENTINEL_GATE, "yes" if index >= 3 else "no"),
        )
        rows += _month_rows(gate="yes", hit=False, sentinels=sentinels)
    parsed = ab_probe.parse_rows("\n".join(rows))
    assert ab_probe.card_verdict(parsed, card=ab_probe.SENTINEL_OPEN).status == "pass_appeared"
    assert ab_probe.card_verdict(parsed, card=ab_probe.SENTINEL_GATE).status == "pass_appeared"
    assert ab_probe.card_verdict(parsed, card=_CARD).status == "red_gate_open_no_hits", (
        "哨兵能进池而我们那张进不去 ⇒ 这才是可执行的那条结论（t18 第 10 条的判决条件）"
    )


def test_命令行入口真的接上了() -> None:
    """`python -m pdx.ab_probe` 必须**真的跑** `main` —— 光有 `main()` 不算入口。

    这条是现场抓出来的：入口函数写好了却没接 `__main__`，于是
    `python -m pdx.ab_probe --log …` **什么都不打印、还 exit 0** ——
    「判红入口自己静默返回成功」正是第 15 条要杀的那件事。
    """
    source = Path(ab_probe.__file__).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source
    assert "raise SystemExit(main())" in source


def test_读数入口判红时给非零退出码(tmp_path: Path) -> None:
    bad = tmp_path / "red.log"
    bad.write_text(_report(6), encoding="utf-8", newline="\n")
    assert ab_probe.main(["--log", str(bad), "--card", _CARD, "--expect-mode", "control"]) == 1
    good = tmp_path / "pass.log"
    good.write_text(_report(6, hit_from=3), encoding="utf-8", newline="\n")
    assert ab_probe.main(["--log", str(good), "--card", _CARD]) == 0
