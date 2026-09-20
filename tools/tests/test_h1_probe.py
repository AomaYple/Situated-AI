"""``pdx.h1_probe`` 的用例：探针是**生成**的，所以生成物本身要被钉住。

重点不是"文件写出来了"，而是：**日志链覆盖原版全部同槽牌**（漏一张就会把那张牌
永远记成兜底桶，属于静默失真）、**剂量阶梯与分析器同源**、**变体差异只有 defines 一处**。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pdx import ai_surface as surf
from pdx import config, h1, h1_probe
from pdx.parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.unit

_EMPTY_GAME = Path("Z:/不存在的游戏目录")


def _card(name: str, slot: str) -> surf.Card:
    return surf.Card(
        name=name,
        slot=slot,
        file="<test>",
        line=1,
        weight_base=10.0,
        weight_terms=0,
        has_possible=True,
        fields=(),
        weight_inputs=(),
        possible_inputs=(),
        field_inputs=(),
    )


def _db() -> list[surf.Card]:
    return [
        _card("ai_strategy_conservative_agenda", "political"),
        _card("ai_strategy_progressive_agenda", "political"),
        _card("ai_strategy_agricultural_expansion", "administrative"),
        _card("ai_strategy_maintain_power_balance", "diplomatic"),
    ]


def test_natural变体不含defines而storm含() -> None:
    natural = h1_probe.build(variant="natural", game=_EMPTY_GAME)
    storm = h1_probe.build(variant="storm", game=_EMPTY_GAME)
    key = "common/defines/zz_probe_h1_defines.txt"
    assert key not in natural.files
    assert key in storm.files
    assert set(natural.files) | {key} == set(storm.files)


def test_未知变体报错() -> None:
    with pytest.raises(ValueError, match="未知变体"):
        h1_probe.build(variant="nope", game=_EMPTY_GAME)


def test_政治牌的剂量阶梯与分析器同源() -> None:
    text = h1_probe.slot_card_text("political")
    base = h1.DOSE_WEIGHT[h1.DOSE_ORDER[0]]
    assert f"value = {base}" in text
    for dose in h1.DOSE_ORDER[1:]:
        assert f"has_variable = {h1_probe.DOSE_VAR_PREFIX}{dose.lower()}" in text
        assert f"add = {h1.DOSE_WEIGHT[dose] - base}" in text


def test_三个槽位各一张牌且type正确() -> None:
    for slot, (name, filename, icon) in h1_probe.SLOT_CARDS.items():
        text = h1_probe.slot_card_text(slot)
        assert f"{name} = {{" in text
        assert f"type = {slot}" in text
        assert icon in text
        assert filename.endswith(".txt")
    assert len({value[0] for value in h1_probe.SLOT_CARDS.values()}) == len(h1.SLOTS)


def test_日志链覆盖原版同槽全部牌() -> None:
    text = h1_probe.on_actions_text(_db())
    for card in _db():
        assert f"has_strategy = {card.name}" in text, card.name
    # 我们的牌排在最前（自报行好读），且三槽都有一行
    for slot in h1.SLOTS:
        assert f"ZZPROBE H1;{h1.SLOT_SHORT[slot]};" in text
    assert "ZZPROBE H1;DOSE;" in text
    assert "ZZPROBE H1;FOURTH;active;" in text
    assert "ai_strategy_default" in text


def test_日志链按槽位分组_不串槽() -> None:
    db = _db()
    assert h1_probe.chain_cards(db, "administrative") == [
        "ai_strategy_sitai_probe_admin",
        "ai_strategy_agricultural_expansion",
    ]
    assert h1_probe.chain_cards(db, "diplomatic") == [
        "ai_strategy_sitai_probe_diplo",
        "ai_strategy_maintain_power_balance",
    ]
    # 政治链上还挂着两张对照组牌（无 loc 牌 + 第四槽候选），且原版按名字排序
    assert h1_probe.chain_cards(db, "political") == [
        "ai_strategy_sitai_probe_reform",
        "ai_strategy_sitai_probe_noloc",
        "ai_strategy_sitai_probe_fourth",
        "ai_strategy_conservative_agenda",
        "ai_strategy_progressive_agenda",
    ]


def test_分组效果含四路随机与开局标记() -> None:
    text = h1_probe.effects_text("storm")
    assert text.count("25 = {") == 4
    for dose in h1.DOSE_ORDER[1:]:
        assert f"{h1_probe.DOSE_VAR_PREFIX}{dose.lower()} value = 1" in text
    assert "ZZPROBE H1;RUN;storm" in text
    # H3 已结案：add_ai_strategy 不是脚本效果，探针的**代码**里不该再留这个测试
    # （注释里会提它 —— 那是在记录结论，所以按行去掉注释再查）
    code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    assert "add_ai_strategy" not in code
    assert "add_ai_strategy" in h1_probe.H3_RESULT


def test_defines只写NAI与两个键() -> None:
    text = h1_probe.defines_text()
    assert "NAI = {" in text
    for key, value in h1_probe.STORM_DEFINES["NAI"].items():
        assert f"{key} = {value}" in text
    # 不整文件复制：原版别的键一个都不抄
    assert "DEFAULT_STRATEGY_STRING" not in text
    assert "TICKS_FOR_FULL_SPENDING_VARIABLES_UPDATE" not in text


def test_写盘会清掉被取代的旧文件(tmp_path: Path) -> None:
    stale = tmp_path / "common" / "ai_strategies" / "zz_probe_h1_reform.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("旧的", encoding="utf-8")
    h1_probe.write(variant="natural", root=tmp_path, game=_EMPTY_GAME)
    assert not stale.exists()
    assert (tmp_path / "common" / "ai_strategies" / "zz_probe_h1_pol.txt").is_file()


def test_natural会删掉storm留下的defines(tmp_path: Path) -> None:
    h1_probe.write(variant="storm", root=tmp_path, game=_EMPTY_GAME)
    defines = tmp_path / "common" / "defines" / "zz_probe_h1_defines.txt"
    assert defines.is_file()
    h1_probe.write(variant="natural", root=tmp_path, game=_EMPTY_GAME)
    assert not defines.exists()


def test_部署会同步目录并只启用这一个mod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_set(mod_paths: Iterable[Path | str], **_kwargs: object) -> None:
        seen.append([str(p) for p in mod_paths])

    monkeypatch.setattr(h1_probe.experiments, "set_enabled_mods", fake_set)
    source = tmp_path / "src"
    target = tmp_path / "mod"
    dest = h1_probe.deploy(variant="storm", root=source, target=target, game=_EMPTY_GAME)
    assert dest == target / h1_probe.PROBE_MOD
    assert (dest / "common" / "defines" / "zz_probe_h1_defines.txt").is_file()
    # 第二次部署要覆盖，不叠加
    h1_probe.deploy(variant="natural", root=source, target=target, game=_EMPTY_GAME)
    assert not (dest / "common" / "defines" / "zz_probe_h1_defines.txt").exists()
    assert seen[-1] == [str(dest)]


def test_归档日志把文件挪走(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "USERDIR", tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "debug.log").write_text("x", encoding="utf-8")
    (logs / "error.log").write_text("y", encoding="utf-8")
    dest, moved, skipped = h1_probe.archive_logs("run-1", log_dir=logs)
    assert (moved, skipped) == (2, 0)
    assert dest.is_dir()
    assert len(list(dest.glob("*.log"))) == 2
    assert list(logs.glob("*.log")) == []


def test_归档日志跳过被占用的文件(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """游戏还开着时日志被独占 —— 不能抛异常，但要如实报出挪不动几个。"""
    monkeypatch.setattr(config, "USERDIR", tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "debug.log").write_text("x", encoding="utf-8")

    def fake_move(src: str, dst: str) -> None:
        raise PermissionError(32, "另一个程序正在使用此文件")

    monkeypatch.setattr(h1_probe.shutil, "move", fake_move)
    _dest, moved, skipped = h1_probe.archive_logs("run-2", log_dir=logs)
    assert (moved, skipped) == (0, 1)


def test_metadata是合法JSON() -> None:
    data = json.loads(h1_probe.metadata_text())
    assert data["supported_game_version"] == "1.14.3"
    assert data["game_custom_data"]["multiplayer_synchronized"] is False


def test_摘要列出变体与文件() -> None:
    text = h1_probe.summary(h1_probe.build(variant="storm", game=_EMPTY_GAME))
    assert "storm" in text
    assert "zz_probe_h1_pol.txt" in text


def test_生成的文件能被本仓库的解析器读懂(tmp_path: Path) -> None:
    """用仓库自己的 PDX 解析器过一遍生成物：括号/引号不平衡会被当场抓住。

    这是生成器最可能的故障模式（拼字符串拼漏一个 `}`），而它在游戏里表现为
    "探针整段不生效"，不去翻日志根本看不出来 —— 所以要在单元测试里挡住。
    """
    h1_probe.write(variant="storm", root=tmp_path, game=_EMPTY_GAME)
    cards: set[str] = set()
    effects: set[str] = set()
    files = sorted(tmp_path.rglob("*.txt"))
    assert files
    for path in files:
        assert path.read_bytes().startswith(b"\xef\xbb\xbf"), f"{path.name} 少了 UTF-8 BOM"
        parsed = parse_text(path.read_text(encoding="utf-8-sig"), path=str(path))
        assert parsed.top_assignments, path.name
        if path.parent.name == "ai_strategies":
            cards |= {a.key for a in parsed.top_assignments}
        if path.parent.name == "scripted_effects":
            effects |= {a.key for a in parsed.top_assignments}
    assert cards == {
        "ai_strategy_sitai_probe_reform",
        "ai_strategy_sitai_probe_admin",
        "ai_strategy_sitai_probe_diplo",
        "ai_strategy_sitai_probe_noloc",
        "ai_strategy_sitai_probe_fourth",
    }
    assert effects == {"zz_probe_h1_assign", "zz_probe_h1_boot"}


def test_效果文件里不能出现on_action包装() -> None:
    """`scripted_effects` 里只能有**裸效果列表**。

    写成 on_action 那种 `effect = { … }` 包装，引擎会去调一个叫 `effect` 的效果 →
    `Unknown effect effect`，整个定义作废，而 on_action 那头只会报
    `No on_action scripted with tag … cannot link`。实测后果：分组一次都没跑，
    DOSE 行全是 CTRL，整局白跑 —— 所以这条必须在单元测试里挡住。
    """
    for variant in h1_probe.VARIANTS:
        lines = [
            line.strip()
            for line in h1_probe.effects_text(variant).splitlines()
            if not line.strip().startswith("#")
        ]
        assert "effect = {" not in lines, variant
    # 效果文件里定义的是效果，on_action 的包装在另一个文件里
    parsed = parse_text(h1_probe.effects_text("natural"), path="effects")
    assert {a.key for a in parsed.top_assignments} == {"zz_probe_h1_assign", "zz_probe_h1_boot"}


def test_on_actions引用的tag都在同一文件里定义() -> None:
    """`on_actions = { … }` 只认 **on_action 定义**，不认 scripted_effects 里的效果名。

    引擎对此的报错是 `No on_action scripted with tag … cannot link`，而且只写进
    error.log，脚本侧毫无感觉 —— 钩子静默失效。这条把「引用 ⊆ 定义」钉住。
    """
    text = h1_probe.on_actions_text(_db())
    # 注释里也写着 `on_actions = { … }`（就是解释这条规则的那段），先按行去掉注释
    code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    defined = set(re.findall(r"(?m)^(\w+) = \{", code))
    referenced: set[str] = set()
    for match in re.finditer(r"on_actions = \{([^}]*)\}", code):
        referenced |= set(match.group(1).split())
    assert referenced, "一个钩子都没挂上，测的是空跑"
    assert referenced <= defined, f"没定义的 tag：{sorted(referenced - defined)}"
    # 包装必须调效果文件里真实存在的效果
    assert "zz_probe_h1_boot = yes" in text
    effects = {
        a.key for a in parse_text(h1_probe.effects_text("natural"), path="e").top_assignments
    }
    assert "zz_probe_h1_boot" in effects


def test_牌名词干只有一处定义() -> None:
    """P9：分析器认的标签与生成器写的牌名必须来自同一个词干表。

    分两处写过的后果很具体：改一处忘一处 → 自报链认不出自己的牌，
    整局数据变成"我们的牌从没被抽中"。
    """
    for slot, (name, _file, _icon) in h1_probe.SLOT_CARDS.items():
        assert name == "ai_strategy_" + h1.PROBE_CARDS[slot]
    assert h1_probe.NOLOC_CARD == "ai_strategy_" + h1.NOLOC_CARD
    assert h1_probe.FOURTH_CARD == "ai_strategy_" + h1.FOURTH_CARD
    # 生成物里出现的也必须是这一份
    text = h1_probe.build(variant="storm", game=_EMPTY_GAME).files
    assert h1.PROBE_CARD in text["common/on_actions/zz_probe_h1_on_actions.txt"]


def test_监视器按版本快照日志(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """P3：跟着游戏跑的快照器是**命令**，不是临时脚本（日志轮转会删掉早期月份）。"""
    monkeypatch.setattr(config, "USERDIR", tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    log = logs / "debug.log"
    log.write_text("第一版\n", encoding="utf-8")
    state = {"rounds": 0}

    def fake_running() -> bool:
        state["rounds"] += 1
        if state["rounds"] == 2:  # 第二轮之前日志变了 → 应该有第二份快照
            log.write_text("第一版\n第二版\n", encoding="utf-8")
        return state["rounds"] <= 3

    dest, rounds, copied, skipped = h1_probe.watch(
        "watch-1", log_dir=logs, interval=0.0, sleep=lambda _s: None, running=fake_running
    )
    assert rounds == 3
    assert copied == 2, "变化过的文件才该再复制一份"
    assert skipped == 0
    names = sorted(p.name for p in dest.iterdir())
    assert names == ["s0001-debug.log", "s0002-debug.log"]


def test_监视器在游戏退出后收工(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "USERDIR", tmp_path)
    (tmp_path / "logs").mkdir()
    dest, rounds, copied, _skipped = h1_probe.watch(
        "watch-2", log_dir=tmp_path / "logs", sleep=lambda _s: None, running=lambda: False
    )
    assert (rounds, copied) == (0, 0)
    assert dest.is_dir()


def test_监视器跳过被占用的文件(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "USERDIR", tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "debug.log").write_text("x", encoding="utf-8")

    def fake_copy(_src: object, _dst: object) -> None:
        raise PermissionError(32, "另一个程序正在使用此文件")

    monkeypatch.setattr(h1_probe.shutil, "copy2", fake_copy)
    _dest, _rounds, copied, skipped = h1_probe.watch(
        "watch-3", log_dir=logs, interval=0.0, sleep=lambda _s: None, running=lambda: True
    )
    assert (copied, skipped) == (0, 1)


def test_无loc牌与第四槽牌不带本地化引用() -> None:
    assert "icon =" not in h1_probe.noloc_card_text()
    assert f"type = {h1_probe.FOURTH_TYPE}" in h1_probe.fourth_card_text()
