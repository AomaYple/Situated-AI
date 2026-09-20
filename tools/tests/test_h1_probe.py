"""``pdx.h1_probe`` 的用例：探针是**生成**的，所以生成物本身要被钉住。

重点不是"文件写出来了"，而是：**日志链覆盖原版全部同槽牌**（漏一张就会把那张牌
永远记成兜底桶，属于静默失真）、**剂量阶梯与分析器同源**、**变体差异只有 defines 一处**。
"""

from __future__ import annotations

import json
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


def test_分组效果含四路随机与H3两种语法() -> None:
    text = h1_probe.effects_text("storm")
    assert text.count("25 = {") == 4
    for dose in h1.DOSE_ORDER[1:]:
        assert f"{h1_probe.DOSE_VAR_PREFIX}{dose.lower()} value = 1" in text
    assert "add_ai_strategy = { type = political id = ai_strategy_egalitarian_agenda }" in text
    assert "ai_strategy_egalitarian_agenda\n" in text
    assert "ZZPROBE H1;RUN;storm" in text
    assert "ZZPROBE H3;TRY;block;" in text
    assert "ZZPROBE H3;DONE;bare;" in text


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
    assert effects == {"zz_probe_h1_assign", "zz_probe_h1_start"}


def test_无loc牌与第四槽牌不带本地化引用() -> None:
    assert "icon =" not in h1_probe.noloc_card_text()
    assert f"type = {h1_probe.FOURTH_TYPE}" in h1_probe.fourth_card_text()
