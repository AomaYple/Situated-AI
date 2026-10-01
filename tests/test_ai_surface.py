"""``pdx.ai_surface`` 的用例（阶段 1 的产物生成器）。

分两层：

* **合成样例**（unit）：只喂 ``parse_text`` 造的小脚本，钉住"什么算输入、什么不算"的口径 ——
  这是最容易写错、也最容易悄悄退化的地方；
* **真实文件**（integration）：装了游戏才跑，钉住"原版三槽的牌数就是 7 / 9 / 18"这类可复算事实。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import pdx.ai_surface as surf
import pdx.config
from pdx.model import Block, Scalar
from pdx.parser import parse_text

if TYPE_CHECKING:
    from pdx.model import ParsedFile

pytestmark = pytest.mark.unit

_SAMPLE = """
ai_strategy_default = {
	icon = "gfx/x.dds"
	some_default_field = { value = 1 }
}

ai_strategy_demo = {
	icon = "gfx/y.dds"
	type = political

	possible = { always = yes }

	weight = {
		value = 20
		if = {
			limit = {
				has_journal_entry = je_metternich
				NOT = { is_princely_state = yes }
			}
			add = 10
		}
		if = {
			limit = { ruler = { has_variable = house_orleans } }
			multiply = ai_state_ambition_floor
		}
	}

	pro_interest_groups = { ig_intelligentsia }
	change_law_chance = { value = 0.5 }
}
"""


def _cards() -> list[surf.Card]:
    parsed = parse_text(_SAMPLE, path="<sample>")
    cards = []
    for assignment in parsed.top_assignments:
        assert assignment.key.startswith("ai_strategy_")
        block = assignment.value
        assert isinstance(block, Block)
        cards.append(surf.card_from(assignment.key, block, file="<sample>", line=assignment.line))
    return cards


def test_牌面_槽位字段与权重基准() -> None:
    demo = next(c for c in _cards() if c.name == "ai_strategy_demo")
    assert demo.slot == "political"
    assert demo.weight_base == 20.0
    assert demo.weight_terms == 2
    assert demo.has_possible is True
    # 元数据字段不算行为字段
    assert "icon" not in demo.fields
    assert "type" not in demo.fields
    assert "pro_interest_groups" in demo.fields
    assert "change_law_chance" in demo.fields


def test_默认层被单独标出() -> None:
    default = next(c for c in _cards() if c.name == "ai_strategy_default")
    assert default.slot == "默认层"
    assert default.weight_base is None


def test_权重输入_只收触发器与脚本值引用() -> None:
    demo = next(c for c in _cards() if c.name == "ai_strategy_demo")
    got = set(demo.weight_inputs)
    # 触发器被收录
    assert {"has_journal_entry", "is_princely_state", "ruler", "has_variable"} <= got
    # 脚本值引用被收录
    assert "ai_state_ambition_floor" in got
    # 运算符与逻辑包装键**不算**输入
    assert not ({"value", "add", "multiply", "if", "limit", "NOT"} & got)
    # 触发器的参数值也不算输入（它们是 scope / 字面量）
    assert "je_metternich" not in got


def test_possible_门被单独收集() -> None:
    demo = next(c for c in _cards() if c.name == "ai_strategy_demo")
    assert demo.possible_inputs == ("always",)


def test_汇总_按牌数排序并按名字合并() -> None:
    inputs = surf.collect_inputs(_cards())
    by_name = {i.name: i for i in inputs}
    assert by_name["has_journal_entry"].cards == 1
    assert by_name["has_journal_entry"].kind == "trigger"
    assert by_name["ai_state_ambition_floor"].kind == "script_value"
    assert by_name["always"].kind == "trigger"
    counts = [i.cards for i in inputs]
    assert counts == sorted(counts, reverse=True), "应当按被多少张牌读到降序"


def test_因子判定_命中与未命中() -> None:
    inputs = surf.collect_inputs(_cards())
    hits = {h.factor.name: h for h in surf.factor_report(inputs)}
    assert "✅" in hits["JE/使命"].verdict  # has_journal_entry 命中
    assert "❌" in hits["财政/债务"].verdict  # 样例里没有财政类输入


def test_渲染_含四张表与复算口径() -> None:
    cards = _cards()
    inputs = surf.collect_inputs(cards)
    text = surf.render(
        cards,
        inputs,
        surf.factor_report(inputs),
        surf.DefinesSurface(
            nai_keys=3,
            enabled_switches=("X_ENABLED",),
            ai_keys=("AI_X",),
            notable=("STRATEGY_RANDOM_FACTOR",),
            lines=10,
        ),
        top=5,
    )
    assert "勿手改" in text
    assert "v3 ai-surface --check" in text
    for section in (
        "## 1. 牌面总览",
        "## 2. 原版 AI 读到的输入",
        "## 3. 粒度可行性表",
        "## 4. defines 面",
    ):
        assert section in text
    assert "`ai_strategy_demo`" in text


def test_写盘与核对往返(tmp_path, monkeypatch) -> None:
    # 用合成数据替换真实数据源，测试只管"写 → 核对"这条链路
    # （假 build 收下并回显两个参数：既满足签名，也不触发「未使用参数」的 lint）
    monkeypatch.setattr(surf, "build", lambda game=None, top=60: f"hello/{game}/{top}\n")
    path = surf.write_doc(repo=tmp_path)
    assert path.read_text(encoding="utf-8").startswith("hello/")
    assert surf.check_doc(repo=tmp_path) == ""

    path.write_text("手改过\n", encoding="utf-8")
    drift = surf.check_doc(repo=tmp_path)
    assert drift, "被手改后必须报出来"
    assert "不一致" in drift


def test_核对缺文件时给出提示(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(surf, "build", lambda game=None, top=60: f"hello/{game}/{top}\n")
    msg = surf.check_doc(repo=tmp_path)
    assert "缺少" in msg
    assert "--write" in msg


# ── 真实文件（装了游戏才跑）────────────────────────────────────


@pytest.mark.integration
def test_真实原版_三槽牌数与默认层() -> None:
    if not (pdx.config.GAME / surf.STRATEGY_DIR).is_dir():
        pytest.skip("没有游戏本体：这一条只在装了游戏的机器上判定")
    cards = surf.read_cards()
    slots: dict[str, int] = {}
    for card in cards:
        slots[card.slot] = slots.get(card.slot, 0) + 1
    assert slots.get("默认层") == 1
    assert slots.get("administrative") == 7
    assert slots.get("political") == 9
    assert slots.get("diplomatic") == 18


@pytest.mark.integration
def test_真实原版_保守议程读到梅特涅JE() -> None:
    if not (pdx.config.GAME / surf.STRATEGY_DIR).is_dir():
        pytest.skip("没有游戏本体")
    cards = surf.read_cards()
    conservative = next(c for c in cards if c.name == "ai_strategy_conservative_agenda")
    assert "has_journal_entry" in conservative.weight_inputs


@pytest.mark.integration
def test_真实原版_defines面_有NAI块与开关() -> None:
    if not (pdx.config.GAME / surf.DEFINES_FILE).is_file():
        pytest.skip("没有游戏本体")
    surface = surf.read_defines()
    assert surface.nai_keys > 900
    assert "PRODUCTION_BUILDING_CONSTRUCTION_ENABLED" in surface.enabled_switches
    assert "STRATEGY_RANDOM_FACTOR" in surface.notable


# ── 真实原版：新增牌的字段台账（`阶段5-新增牌-口径.md` §2.1 / §3.1 / §3.3）────
#
# 这一组守的是**行号与计数**。它存在的原因值得写在代码里：那两处台账此前连错两轮，
# 两次错因都不在结论、而在**复算手段本身** ——
#   * 一条只认单个 TAB 缩进的解析漏掉了 `nationalist_agenda`（它的块缩进是两个 TAB）；
#   * 一条要求 `=` 后面有空格的窄正则看不见原版 `:1006` 的 `anti_interest_groups ={`；
#   * 行首正则还看不见同行写法 `limit = { has_modifier = X }`（`00_default_strategy.txt` 里有 5 处）。
# ⇒ 这里的计数一律**在块内递归**做，不对整份文本跑行首正则；行号取解析器的 `line`。

_PS_NAME = "03_political_strategies.txt"

#: `anti_interest_groups` 的 8 处行号（**按块归属**实测；卡序 = 保守/反动/进步/平等/民族/天命/坦志麦特/明治）。
#: ⚠️ `maintain_mandate_of_heaven` 的是 **1006**（原版写作 `anti_interest_groups ={`，等号后没有空格），
#: 坦志麦特的是 **1123** —— 这两个数曾经被写反，别再"顺手修正"。
_ANTI_IG_LINES = {
    "ai_strategy_conservative_agenda": 54,
    "ai_strategy_reactionary_agenda": 220,
    "ai_strategy_progressive_agenda": 424,
    "ai_strategy_egalitarian_agenda": 620,
    "ai_strategy_nationalist_agenda": 804,
    "ai_strategy_maintain_mandate_of_heaven": 1006,
    "ai_strategy_tanzimat_reforms": 1123,
    "ai_strategy_meiji_restoration": 1225,
}

#: 九张政治牌里**唯一**没有 `anti_interest_groups` 的那一张。
#: （`ai_strategy_default` 也有这一块，但它不在这九张政治牌里 —— 见 §2.1 的括注。）
_ANTI_IG_MISSING = "ai_strategy_great_reforms"


def _parsed(name: str) -> ParsedFile:
    """解析 `common/ai_strategies/` 下的一份原版文件（编码口径与原版一致：``utf-8-sig``）。"""
    path = pdx.config.GAME / surf.STRATEGY_DIR / name
    return parse_text(path.read_text(encoding="utf-8-sig"), path=str(path))


def _cards_of(parsed: ParsedFile) -> dict[str, Block]:
    """``ai_strategy_*`` 顶层块 → 它的块体（其余顶层条目一律不看）。"""
    return {
        a.key: a.value
        for a in parsed.top_assignments
        if a.key.startswith("ai_strategy_") and isinstance(a.value, Block)
    }


def _has_modifier_lines(block: Block) -> list[int]:
    """块内**递归**找 `has_modifier` 的行号。

    为什么不是"块内文本 + 行首正则"：同行写法（``limit = { has_modifier = X }``）不会被行首正则
    看见，而漏掉的表现只是"数字变小"—— 没有报错、没有红，正是最坏的那种失真。
    """
    out: list[int] = []
    for sub in block.assignments():
        if sub.key == "has_modifier":
            out.append(sub.line)
        if isinstance(sub.value, Block):
            out.extend(_has_modifier_lines(sub.value))
    return out


@pytest.mark.integration
def test_真实原版_反IG块8处行号与归属() -> None:
    """§2.1 的 `anti_interest_groups` 行：8 处行号 + 卡名归属 + 九张里唯一缺的那一张。"""
    path = pdx.config.GAME / surf.STRATEGY_DIR / _PS_NAME
    if not path.is_file():
        pytest.skip("没有游戏本体")
    cards = _cards_of(_parsed(_PS_NAME))
    got: dict[str, int] = {}
    for name, body in cards.items():
        found = body.first("anti_interest_groups")
        if found is not None:
            got[name] = found.line
    assert got == _ANTI_IG_LINES
    assert _ANTI_IG_MISSING not in got
    # 括注里的另一条事实：`ai_strategy_default`（不在这九列里）也有这一块。
    default = _cards_of(_parsed("00_default_strategy.txt"))["ai_strategy_default"]
    assert default.first("anti_interest_groups") is not None


@pytest.mark.integration
def test_真实原版_牌面门与权重复算() -> None:
    """§3.1 的四个数：带 `possible` **34** 张 / 带 `weight` **35** 张 / possible 内读修正 **0** / weight 内 **4**。

    这四个数出过 32/33 与 33/34 两套错值，全部来自"块边界没算对"。计数口径写死在这里：
    **顶层 `ai_strategy_*` 块 → 块内 `possible`/`weight` → 块内递归找 `has_modifier`**。
    """
    strategy_dir = pdx.config.GAME / surf.STRATEGY_DIR
    if not strategy_dir.is_dir():
        pytest.skip("没有游戏本体")
    total = 0
    with_possible = 0
    with_weight = 0
    missing_possible: list[str] = []
    hm_in_possible: dict[str, list[int]] = {}
    hm_in_weight: dict[str, list[int]] = {}
    for name in sorted(p.name for p in strategy_dir.glob("*.txt")):
        for card_name, body in _cards_of(_parsed(name)).items():
            total += 1
            possible = body.first("possible")
            weight = body.first("weight")
            if possible is None:
                missing_possible.append(card_name)
            else:
                with_possible += 1
                hits = (
                    _has_modifier_lines(possible.value) if isinstance(possible.value, Block) else []
                )
                if hits:
                    hm_in_possible[card_name] = hits
            if weight is not None:
                with_weight += 1
                hits = _has_modifier_lines(weight.value) if isinstance(weight.value, Block) else []
                if hits:
                    hm_in_weight[card_name] = hits
    assert total == 35
    assert with_possible == 34
    assert with_weight == 35
    assert missing_possible == ["ai_strategy_industrial_expansion"]
    assert hm_in_possible == {}
    assert hm_in_weight == {
        "ai_strategy_reactionary_agenda": [355],
        "ai_strategy_progressive_agenda": [548],
        "ai_strategy_egalitarian_agenda": [738],
        "ai_strategy_nationalist_agenda": [927],
    }


@pytest.mark.integration
def test_真实原版_权重为0的牌只有默认牌() -> None:
    """§3.3 的"门外权重 0"先例：全五份文件里 `weight` 基值为 0 的**只有** `ai_strategy_default`。

    它的语义是"默认牌：永不随机分配"—— `possible = { always = no }`（`:9697`）配
    `weight = { value = 0 }`（`:9702`），与本页"门说不 + 权重也说 0"同型。
    """
    strategy_dir = pdx.config.GAME / surf.STRATEGY_DIR
    if not strategy_dir.is_dir():
        pytest.skip("没有游戏本体")
    zeros: list[tuple[str, str, int]] = []
    for name in sorted(p.name for p in strategy_dir.glob("*.txt")):
        cards = _cards_of(_parsed(name))
        for card_name, body in cards.items():
            weight = body.first("weight")
            if weight is None or not isinstance(weight.value, Block):
                continue
            base = weight.value.first("value")
            if base is not None and isinstance(base.value, Scalar) and base.value.unquoted == "0":
                zeros.append((name, card_name, weight.line))
    assert zeros == [("00_default_strategy.txt", "ai_strategy_default", 9702)]
    default = _cards_of(_parsed("00_default_strategy.txt"))["ai_strategy_default"]
    possible = default.first("possible")
    assert possible is not None
    assert possible.line == 9697
    assert isinstance(possible.value, Block)
    always = possible.value.first("always")
    assert always is not None
    assert isinstance(always.value, Scalar)
    assert always.value.unquoted == "no"
