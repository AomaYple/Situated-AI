"""``modguard`` 的**离线通道**用例（G-EXIT-2 / 阶段 4）。

为什么单列一个文件：离线通道给 `modguard.py` 加了 ~357 行（闸门 ①② 的原版真值改走
`pdx.vanilla_index`：快照源、未覆盖项的报法、缺域即"前置条件缺失"），而
`pytest -n 4` + `v3 cov` 实测它把这些新分支留在未覆盖状态（`modguard.py` 88.0% < 96% 下限）。
**处置是补用例，不是下调 `covgate.FLOORS`**（P6 只许上调）。

口径（照 `pdx.vanilla_index` 的模块文档，别在用例里重新发明）：
* ``None`` = **离线未覆盖**（"没查"）≠ 空集（"原版没有"）；
* 快照缺域 ⇒ 闸门报未覆盖并**退出 2**，绝不静默通过；
* 快照源与游戏源给出的**集合必须相同** —— 否则会出现"离线绿、在线红"的假绿。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from pdx import config, modguard, vanilla_index

pytestmark = pytest.mark.unit


def test_离线通道用快照跑通五道闸门() -> None:
    """`--offline` 的正路：原版真值只认入库快照，五道闸门照常全过。"""
    ctx = modguard.context(offline=True)
    report = modguard.run(ctx)
    assert report.ok, modguard.format_report(report)
    text = modguard.format_report(report)
    assert "快照" in text, "明细里必须写明真值来自快照，别让人以为是现读游戏"


def test_离线通道在本机有游戏时也走快照() -> None:
    """本机装了游戏也得走快照 —— 否则这条通道在本机从没被测过。"""
    index = vanilla_index.load(offline=True, game=config.GAME)
    assert index is not None, "入库快照缺域了？先跑 `v3 snapshot create --compact`"
    assert index.offline, "`offline=True` 必须落在快照源上（而不是回落游戏）"
    assert "快照" in index.describe()


def test_离线但快照缺域时报前置条件缺失而不是静默通过(monkeypatch: pytest.MonkeyPatch) -> None:
    """P13 的背面：两条真值来源都没有时，①② 必须报"前置条件缺失"，不许当成通过。"""
    monkeypatch.setattr(vanilla_index, "load", lambda **_kw: None)
    ctx = modguard.context(offline=True)
    report = modguard.run(ctx)
    assert not report.ok
    headlines = " ".join(f.headline for f in report.findings)
    assert "前置条件缺失" in headlines

    # ③④⑤ 本来就不读游戏 ⇒ 它们不该被这条缺失带红
    offline_gates = [
        f for f in report.findings if f.gate in {"dilution", "roundtrip", "determinism"}
    ]
    assert offline_gates, "③④⑤ 应该还在报告里"
    assert all(f.ok for f in offline_gates), "③④⑤ 不读游戏，不该被这条缺失带红"


def test_快照源与游戏源的键池一致() -> None:
    """同一批真值两个来源必须给出同一个集合（防"离线池窄于在线池"的假绿）。"""
    snap = vanilla_index.snapshot_index()
    assert snap is not None, "仓库里没有精简快照"
    game = vanilla_index.game_index(config.GAME)
    assert game is not None, "本机没有游戏本体"
    for rel in vanilla_index.KEY_DIRS:
        a = snap.keys(rel)
        b = game.keys(rel)
        assert a is not None, f"{rel}：快照里没有这个域"
        assert b is not None, f"{rel}：游戏源读不到这个域"
        assert a == b, f"{rel}：快照池与游戏池不一致（离线会误判）"


def test_未覆盖返回_None_而不是空集() -> None:
    """`None`（没查）与空集（原版没有）必须是两种不同结果 —— 否则"没查"会变成红或绿。"""
    empty = vanilla_index.VanillaIndex(source="snapshot", game=config.GAME, sections={})
    assert empty.offline, "`source == 'snapshot'` 就是离线源"
    assert empty.keys("common/defines") is None
    assert empty.vocabulary() is None
    assert empty.modifier_fields() is None
    assert empty.path_exists("common/defines/00_ai.txt") is None
    assert empty.missing_sections(vanilla_index.SECTIONS), "缺了哪些域要说出来"


def _partial_index(**drops: str) -> vanilla_index.VanillaIndex:
    """拿真实快照的域，**挖掉指定的一个子项** —— 模拟"域在、但这项没记"。

    与"整个域都没有"（`sections={}`）是两回事：后者走"前置条件缺失"的早退分支，
    前者才走闸门里**逐项列未覆盖**的那条路（也正是新代码里最容易没被测到的分支）。
    """
    real = vanilla_index.snapshot_index()
    assert real is not None, "仓库里没有精简快照"
    sections = {name: dict(body) for name, body in real.sections.items()}
    for section, item in drops.items():
        key = {"keys": vanilla_index.SECTION_KEYS, "vocabulary": vanilla_index.SECTION_VOCABULARY}[
            section
        ]
        body = dict(sections[key])
        body.pop(item, None)
        sections[key] = body
    return vanilla_index.VanillaIndex(
        source="snapshot",
        game=config.GAME,
        version=real.version,
        origin=real.origin,
        sections=sections,
    )


def test_快照只缺一个目录时逐条列出未覆盖项而不是判红() -> None:
    """域在、但少记了一个目录 ⇒ 闸门 ① 必须**说出是哪一项没查**，且不当成"原版没有"。"""
    ctx = replace(
        modguard.context(offline=True), vanilla=_partial_index(keys="common/scripted_effects")
    )
    report = modguard.run(ctx)
    text = modguard.format_report(report)
    assert "未覆盖" in text
    assert "scripted_effects" in text, "要点名是哪一项没覆盖"
    assert report.ok, "没查到不等于查到冲突 —— 不该把未覆盖判成红"


def test_闸门二的词汇表域缺一个目录时也逐条列出() -> None:
    """同一口径的闸门 ②：词汇表缺一个目录 ⇒ 列未覆盖，不静默通过也不误判。"""
    ctx = replace(
        modguard.context(offline=True),
        vanilla=_partial_index(vocabulary="common/scripted_effects"),
    )
    report = modguard.run(ctx)
    text = modguard.format_report(report)
    assert "未覆盖" in text
    assert report.ok


def _index(keep: tuple[str, ...], drop: dict[str, str] | None = None) -> vanilla_index.VanillaIndex:
    """按"保留哪些域 / 域内挖掉哪一项"造一个快照源 —— 用来逐条打未覆盖分支。"""
    real = vanilla_index.snapshot_index()
    assert real is not None, "仓库里没有精简快照"
    sections = {name: dict(body) for name, body in real.sections.items() if name in keep}
    for section, item in (drop or {}).items():
        body = dict(sections[section])
        body.pop(item, None)
        sections[section] = body
    return vanilla_index.VanillaIndex(
        source="snapshot",
        game=config.GAME,
        version=real.version,
        origin=real.origin,
        sections=sections,
    )


def test_薄包装在游戏源下仍然现算() -> None:
    """`modguard.vanilla_keys` / `_vanilla_vocabulary` 是给用例与旧调用点留的薄包装，别让它烂掉。"""
    keys = modguard.vanilla_keys(config.GAME / "common" / "defines")
    assert keys, "游戏源下读不到 defines 顶层键"
    vocab = modguard._vanilla_vocabulary(config.GAME)
    assert vocab, "游戏源下读不到词汇表"


def test_快照整个域都没有时报前置条件缺失并点名缺哪个域() -> None:
    """`index` 在但缺一整个域 ⇒ 仍然报"前置条件缺失"，且要说清缺的是哪个域。"""
    ctx = replace(
        modguard.context(offline=True),
        vanilla=_index(keep=(vanilla_index.SECTION_KEYS,)),
    )
    report = modguard.run(ctx)
    assert not report.ok
    text = modguard.format_report(report)
    assert "前置条件缺失" in text
    assert "域" in text, "要点名缺的是哪个域"


def test_闸门一在快照没记某个路径时逐条列未覆盖() -> None:
    """路径池在、但少记了一个目录 ⇒ 闸门 ① 逐条列未覆盖（而不是判成"原版没有"）。"""
    path_section = next(name for name in vanilla_index.SECTIONS if "path" in name)
    ctx = replace(
        modguard.context(offline=True),
        vanilla=_index(keep=tuple(vanilla_index.SECTIONS), drop={path_section: "common/defines"}),
    )
    report = modguard.run(ctx)
    # 缺一个目录时闸门可能**同时**因为别的引用报红（那是"没查到"的连带结果，不是本用例要证明的事）；
    # 本用例只钉住一件事：**缺的那一项必须被逐条列出来**，不许静默当成"原版没有"。
    assert "未覆盖" in modguard.format_report(report), "缺目录必须逐条列出来"


def test_闸门二在快照没记某个键目录时逐条列未覆盖() -> None:
    """闸门 ② 的三个池（静态修正 / JE 分组 / JE）各自缺目录时都要逐条列出来。"""
    keys_section = vanilla_index.SECTION_KEYS
    ctx = replace(
        modguard.context(offline=True),
        vanilla=_index(
            keep=tuple(vanilla_index.SECTIONS),
            drop={keys_section: "common/static_modifiers"},
        ),
    )
    report = modguard.run(ctx)
    text = modguard.format_report(report)
    assert "未覆盖" in text, "缺目录必须逐条列出来"
    assert "static_modifiers" in text or "修正池" in text
