"""``pdx.ai_surface`` 的用例（阶段 1 的产物生成器）。

分两层：

* **合成样例**（unit）：只喂 ``parse_text`` 造的小脚本，钉住"什么算输入、什么不算"的口径 ——
  这是最容易写错、也最容易悄悄退化的地方；
* **真实文件**（integration）：装了游戏才跑，钉住"原版三槽的牌数就是 7 / 9 / 18"这类可复算事实。
"""

from __future__ import annotations

import pytest

from pdx import ai_surface as surf
from pdx import config
from pdx.model import Block
from pdx.parser import parse_text

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
    if not (config.GAME / surf.STRATEGY_DIR).is_dir():
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
    if not (config.GAME / surf.STRATEGY_DIR).is_dir():
        pytest.skip("没有游戏本体")
    cards = surf.read_cards()
    conservative = next(c for c in cards if c.name == "ai_strategy_conservative_agenda")
    assert "has_journal_entry" in conservative.weight_inputs


@pytest.mark.integration
def test_真实原版_defines面_有NAI块与开关() -> None:
    if not (config.GAME / surf.DEFINES_FILE).is_file():
        pytest.skip("没有游戏本体")
    surface = surf.read_defines()
    assert surface.nai_keys > 900
    assert "PRODUCTION_BUILDING_CONSTRUCTION_ENABLED" in surface.enabled_switches
    assert "STRATEGY_RANDOM_FACTOR" in surface.notable
