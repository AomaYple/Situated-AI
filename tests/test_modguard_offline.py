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
from typing import TYPE_CHECKING

import pytest

from pdx import config, modguard, vanilla_index

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

# 「离线通道」本身的用例都不读游戏（上面那几条在无游戏树上照跑）。但下面两条判的不是通道，
# 是**快照池与游戏池对不对得上**（`test_快照源与游戏源的键池一致`）与**薄包装的现算路径还在不在**
# （`test_薄包装在游戏源下仍然现算`）—— 没有游戏树就**做不了**这两个判据。
#
# 口径（B85 一族）：做不了就**显式跳过并点名缺了什么**（这里给出检测到的路径），
# 不许静默通过、也不许把断言放松成"看不到就当没有"。代价必须说清：CI 上没有游戏树 ⇒
# 「离线池 == 在线池」这条**在 CI 上不被守**，缺口登记在
# `docs/reports/t34-CI-环境红灯-与-n0-口径更正.md`（本机有游戏树时这两条照旧真跑）。
_GAME_TREE = config.GAME / "common"
_GAME_TREE_MISSING = (
    f"无游戏树：{_GAME_TREE} 不存在（这条判据要比对『游戏源』的键池，缺了它无从核对）"
)
_needs_game_tree = pytest.mark.skipif(not _GAME_TREE.is_dir(), reason=_GAME_TREE_MISSING)


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


@_needs_game_tree
def test_快照源与游戏源的键池一致() -> None:
    """同一批真值两个来源必须给出同一个集合（防"离线池窄于在线池"的假绿）。

    无游戏树时显式跳过（理由点名缺的路径）—— 这条判据本身要求两个来源都在场。
    """
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


@_needs_game_tree
def test_薄包装在游戏源下仍然现算() -> None:
    """`modguard.vanilla_keys` / `_vanilla_vocabulary` 是给用例与旧调用点留的薄包装，别让它烂掉。

    「现算」两个字就意味着要游戏树 ⇒ 无游戏树时显式跳过（理由点名缺的路径）。
    """
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


# ── 闸门 ② 的**变量池**（2026-09-30 新增的域）────────────────────
#
# 这一节守的是 A1 修的那条假红：`recent_capitulation` 是**原版自己写**的记号
# （common/on_actions/00_code_on_actions.txt:4222 写、events/discrimination_events.txt:222 读），
# 而闸门 ② 原来只比「我们写下过没有」⇒ 原版记号被当成"我们从未写下的变量"。
#
# 两条口径都要有用例守着，缺一条就有一半的失败方式没有对手：
# * 池子在 ⇒ 名字不在池子里必须**判红**（不许悄悄变成"池子里没有就放过"）；
# * 池子不在（旧快照没有这个域）⇒ 只说"没查"，不判红也不静默通过。
#: 对抗探针：原版不写、我们也不写的变量名（用例自己插进产物文本）。
_GATE_PROBE = "sitai_probe_gate_refs_never_written"


def _with_variable_pool(names: set[str]) -> vanilla_index.VanillaIndex:
    """真实快照 + **现读出来的变量池** —— 模拟刷新后的快照带的那个新域。"""
    real = vanilla_index.snapshot_index()
    assert real is not None, "仓库里没有精简快照"
    sections = {name: dict(body) for name, body in real.sections.items()}
    sections[vanilla_index.SECTION_VARIABLES] = {
        rel: sorted(names) for rel in vanilla_index.VARIABLE_POOL_DIRS
    }
    return vanilla_index.VanillaIndex(
        source="snapshot",
        game=config.GAME,
        version=real.version,
        origin=real.origin,
        sections=sections,
    )


def _without_variable_pool() -> vanilla_index.VanillaIndex:
    """真实快照，但**整域挖掉变量池** —— 1.14.4 及以前入库快照的形状。

    刻意从 `sections` 上删一项而不是 `_index(keep=...)`：快照里还有
    `defines` 这类**不在** `vanilla_index.SECTIONS` 里的域（由 `pdx.snapshot`
    自己写），按 keep 过滤会把它们一起丢掉 ⇒ 闸门 ② 直接报"前置条件缺失"，
    走的就不是本用例要测的那条路了。
    """
    real = vanilla_index.snapshot_index()
    assert real is not None, "仓库里没有精简快照"
    sections = {
        name: dict(body)
        for name, body in real.sections.items()
        if name != vanilla_index.SECTION_VARIABLES
    }
    return vanilla_index.VanillaIndex(
        source="snapshot",
        game=config.GAME,
        version=real.version,
        origin=real.origin,
        sections=sections,
    )


def _with_fake_variable_reference(
    ctx: modguard.Context, *, name: str = _GATE_PROBE
) -> modguard.Context:
    """在**产物文本**里插一条变量引用 —— 闸门 ② 的强度探针。

    为什么插在这里而不是改数据源：`gate_refs` 的事实表只来自 `ctx.built.files`，
    在这一层插正好只动被测的那道闸门，不会顺带把 ③④⑤（以及"产物与数据源一致"）
    带红 —— 那会让"红的是哪一条"说不清。

    形状刻意照原版冲击效果的用法（`if` → `limit` → `has_variable`）：事实表由
    `modgen.readback` 按产物**结构**反解，直接写在效果体里的 `has_variable` 不会被收录
    （它不是合法效果调用），那样探针会静默失效 —— 不能证明任何事。
    """
    files = dict(ctx.built.files)
    rel = next(rel for rel in sorted(files) if rel.startswith("common/scripted_effects/"))
    files[rel] += (
        f"\nsitai_probe_gate_refs = {{\n\tif = {{\n\t\tlimit = {{\n"
        f"\t\t\thas_variable = {name}\n\t\t}}\n\t}}\n}}\n"
    )
    return replace(ctx, built=replace(ctx.built, files=files))


def test_变量池只收原版自己写下的名字(tmp_path: Path) -> None:
    """抽取器认的只有 `set_variable = { name = X }` —— 池子宽一寸，闸门松一寸。

    三种"别收进来"的写法各钉一条：被读过的名字（`has_variable`）、全局变量
    （`set_global_variable` 是另一条读侧）、以及 `name = root.xxx` 这类表达式写法。
    """
    on_actions = tmp_path / "common" / "on_actions"
    on_actions.mkdir(parents=True)
    (on_actions / "00_probe.txt").write_text(
        "probe_action = {\n"
        "\teffect = {\n"
        "\t\tset_variable = { name = probe_written days = 30 }\n"
        "\t\tif = { limit = { always = yes }\n"
        "\t\t\tset_variable = { name = probe_deep value = yes }\n"
        "\t\t}\n"
        "\t\tset_global_variable = { name = probe_global_only value = 1 }\n"
        "\t\tset_variable = { name = root.dynamic_name value = 1 }\n"
        "\t\thas_variable = probe_read_only\n"
        "\t}\n"
        "}\n",
        encoding="utf-8",
        newline="\n",
    )
    assert vanilla_index.variable_names(tmp_path / "common") == {"probe_written", "probe_deep"}


def test_变量池在场时假变量仍然判红() -> None:
    """对抗用例：池子在场时，一个「原版不写、我们也不写」的名字必须还是红。

    池子喂的是 1.14.5 里真实存在的 `recent_capitulation`（原版自己写），
    所以这条走的是"池子在、名字不在"那条分支 —— 闸门只要松一点
    （"池子里没有就放过"），这里就会绿。
    """
    ctx = _with_fake_variable_reference(
        replace(
            modguard.context(offline=True),
            vanilla=_with_variable_pool({"recent_capitulation"}),
        )
    )
    finding = modguard.gate_refs(ctx)
    text = "\n".join(finding.details)
    assert not finding.ok, text
    assert f"引用了一个我们从未写下的变量：{_GATE_PROBE}" in text
    assert "原版写入池 1 个" in text, "要真的是‘池子在场’那条分支，而不是 None 那条"


def test_变量池整域缺席时逐条列未覆盖而不是假红() -> None:
    """1.14.4 及以前的入库快照没有 `vanilla_variables` 域 ⇒ 只说"没查"。

    P13 的两面一起钉：**不许静默通过**（每一行都得逐条列出来）也**不许假红**
    （`None` 是"没查过"，不是"原版没写过"）。
    """
    index = _without_variable_pool()
    assert index.variables() is None, "整域缺席必须是 None（没查），不是空集（原版没有）"
    finding = modguard.gate_refs(
        _with_fake_variable_reference(replace(modguard.context(offline=True), vanilla=index))
    )
    text = "\n".join(finding.details)
    assert finding.ok, text
    assert "原版变量池未覆盖" in text, "没查过的名字要逐条说出来"
    assert _GATE_PROBE in text, "要点名是哪个名字没查"
    assert "引用了一个我们从未写下的变量" not in text, "池子没读到不等于原版没写过"


@_needs_game_tree
def test_原版变量池来自现读安装目录_原版记号不假红而假变量仍判红() -> None:
    """本卡的验收本体：池子**现读**原版安装目录，且同一个池子拦得住假名字。

    无游戏树时显式跳过（理由点名缺的路径）—— 这条判据的两半都要求安装目录在场：
    一半证明 `recent_capitulation` 不再假红，另一半证明池子不是"什么都放过"。
    """
    pool: set[str] = set()
    for rel in vanilla_index.VARIABLE_POOL_DIRS:
        pool |= vanilla_index.variable_names(config.GAME / rel)
    assert "recent_capitulation" in pool, (
        "1.14.5 的 on_capitulation 自己写这个名字（common/on_actions/00_code_on_actions.txt:4222）"
    )
    game = vanilla_index.game_index(config.GAME)
    assert game is not None, "本机没有游戏本体"
    assert game.variables() == pool, "访问器与逐目录现读必须是同一个集合"

    ctx = replace(modguard.context(offline=True), vanilla=_with_variable_pool(pool))
    finding = modguard.gate_refs(ctx)
    text = "\n".join(finding.details)
    assert finding.ok, text
    assert "引用了一个我们从未写下的变量" not in text, "原版自己写的记号不许再假红"

    probe = modguard.gate_refs(_with_fake_variable_reference(ctx))
    assert not probe.ok, "同一个池子下，假名字仍然要判红"
    assert _GATE_PROBE in "\n".join(probe.details)
