"""`modguard` 的**定点分支**用例（B43：把覆盖率从 95.9% 推到 ≥96%）。

为什么要单列一个文件：`v3 cov` 实测 `pdx/modguard.py` 95.9% < 96%，缺的全是
"**域在、项缺**"这种形状下的分支 —— 整域缺失会走"前置条件缺失"的早退，
所以那些 `uncovered.append` / "报红并给原因"的行一直没被踩到。
**处置是补用例，不是下调 `covgate.FLOORS`**（P6 只许上调）。

写这批用例时踩到的两件事（都按**代码实际行为**写进断言，不按直觉）：

1. `VanillaIndex.missing_sections()` 判的是 ``not self.sections.get(name)``
   ⇒ **"域在但空"也算缺域**，于是会走前置条件早退。所以"某池未覆盖"的用例必须让
   该域**非空但换掉根目录**，不能把它清空。
2. `defines_params()` 在离线源上"返回 `None`"等价于"`defines` 域为空"，而那一刻
   `missing_sections` 已经早退了 ⇒ `modguard.py:542`（`defines 参数池未覆盖`）
   在**离线路径上不可达**，是防御性分支。这里不硬凑覆盖率，改为**钉住真实行为**
   （走前置条件），并在 `backlog` B43 里如实记下"该行不可达"。
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from pdx import config, modgen, modguard, vanilla_index

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _real_sections() -> dict[str, dict[str, list[str]]]:
    """真实精简快照的域，**逐域深拷贝**（改副本，不动盘上快照）。"""
    real = vanilla_index.snapshot_index()
    assert real is not None, "仓库里没有精简快照 —— 先跑 `v3 snapshot create --compact`"
    return {name: dict(body) for name, body in real.sections.items()}


def _index(sections: dict[str, dict[str, list[str]]]) -> vanilla_index.VanillaIndex:
    real = vanilla_index.snapshot_index()
    assert real is not None
    return vanilla_index.VanillaIndex(
        source="snapshot",
        game=config.GAME,
        version=real.version,
        origin=real.origin,
        sections=sections,
    )


def _ctx() -> modguard.Context:
    return modguard.context(offline=True)


def _our_icons() -> set[str]:
    """我们产物里引用到的图标路径（从**生成物反解**，不是手抄）。"""
    ctx = _ctx()
    facts = modguard._facts_map(ctx.built.files)
    return {value for path, value in facts.items() if path.endswith(".icon")}


# ────────────────────────── 闸门 ② 的三个池：未覆盖 ──────────────────────────


@pytest.mark.parametrize(
    ("dropped_dir", "expected"),
    [
        ("common/static_modifiers", "静态修正池"),
        ("common/journal_entry_groups", "JE 分组池"),
        ("common/journal_entries", "JE 池"),
    ],
)
def test_闸门二三个池各自缺目录时逐条列未覆盖(dropped_dir: str, expected: str) -> None:
    """**域在、这一项缺** ⇒ 必须点名是哪一项没查（不是当成"原版没有"）。"""
    sections = _real_sections()
    keys = dict(sections[vanilla_index.SECTION_KEYS])
    keys.pop(dropped_dir, None)
    sections[vanilla_index.SECTION_KEYS] = keys

    finding = modguard.gate_refs(replace(_ctx(), vanilla=_index(sections)))

    assert any(expected in item for item in finding.uncovered), finding.uncovered
    assert finding.ok, "没查到不等于查到冲突 —— 未覆盖不许判红"


def test_闸门二图标根目录换掉后列未覆盖() -> None:
    """`icon_paths` **非空但根不匹配** ⇒ `icon_exists()` 给 `None` ⇒ 列未覆盖。

    注意不能把 `icon_paths` 清空：`missing_sections()` 会把空域当缺域、直接早退。
    """
    sections = _real_sections()
    sections[vanilla_index.SECTION_ICONS] = {"gfx/elsewhere": ["gfx/elsewhere/x.dds"]}

    finding = modguard.gate_refs(replace(_ctx(), vanilla=_index(sections)))

    assert any("图标" in item for item in finding.uncovered), finding.uncovered


def test_闸门二_defines_域为空时走前置条件而不是未覆盖() -> None:
    """钉住**真实行为**：`defines` 域为空 ⇒ `missing_sections` 判缺域 ⇒ 前置条件缺失。

    这条同时说明为什么 `modguard.py:542` 在离线路径上不可达（见模块文档第 2 条）：
    `defines_params()` 给 `None` 的前提（域为空）已经被早退拦掉了。
    """
    sections = _real_sections()
    sections["defines"] = {}

    finding = modguard.gate_refs(replace(_ctx(), vanilla=_index(sections)))

    assert finding.precondition is True, "空域按缺域处理 ⇒ 前置条件缺失"
    assert finding.uncovered == (), "早退路径不产生未覆盖列表"


# ────────────────────────── 闸门 ② 的图标：过 / 红 ──────────────────────────


def test_闸门二图标落在自家产物里就直接过(tmp_path: Path) -> None:
    """图标文件**确实在自家产物目录里** ⇒ 直接放行（不去查原版）。"""
    icons = _our_icons()
    assert icons, "前置：我们的产物里应当引用了图标"
    icon = min(icons)
    (tmp_path / icon).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / icon).write_bytes(b"not a real dds")

    finding = modguard.gate_refs(replace(_ctx(), root=tmp_path))

    assert not any(icon in item for item in finding.details), finding.details


def test_闸门二图标不在原版里就报红() -> None:
    """图标路径原版池里没有 ⇒ 红，并点名（P13：缺引用即红）。"""
    sections = _real_sections()
    listed = list(sections[vanilla_index.SECTION_ICONS]["gfx/interface/icons"])
    ours = _our_icons()
    assert ours & set(listed), "前置：我们用的图标本来在原版池里（否则这条测的是别的东西）"
    sections[vanilla_index.SECTION_ICONS]["gfx/interface/icons"] = [
        item for item in listed if item not in ours
    ]

    finding = modguard.gate_refs(replace(_ctx(), vanilla=_index(sections)))

    assert finding.ok is False
    assert any("不存在的图标" in item for item in finding.details), finding.details


# ────────────────────────── 闸门 ⑤：两条红路径 ──────────────────────────


def test_闸门四在元数据反解失败时报红并给原因(monkeypatch: pytest.MonkeyPatch) -> None:
    """产物语法坏到读不回来 ⇒ 闸门**四**（往返净度）必须红，并说清"元数据解析失败"。

    注意是闸门 ④ 不是 ⑤：`modgen.readback` 的调用点在 `gate_roundtrip` 里
    （元数据那一段），写用例时先看清楚归属，别按名字猜。
    """

    real = modgen.readback

    def boom(files: dict[str, str]) -> object:
        # 只在**元数据那一次**反解时失败：`gate_roundtrip` 前面还会反解数据源，
        # 一上来就全抛的话会先撞上别的红，反而练不到这一段（实测踩过）。
        if list(files) == [modgen.METADATA_REL]:
            raise modgen.DataError("产物语法有错（用例造）")
        return real(files)

    monkeypatch.setattr(modgen, "readback", boom)

    finding = modguard.gate_roundtrip(_ctx())

    assert finding.ok is False
    text = finding.headline + "".join(finding.details)
    assert "元数据" in text, text


def test_闸门五在两次生成不一致时逐条点名(monkeypatch: pytest.MonkeyPatch) -> None:
    """两次生成不一致 ⇒ 红，并逐条列出不一致的产物（确定性被破坏必须被抓住）。

    ⚠️ **先取 ctx 再打桩**：`modguard.context()` 自己就会调 `modgen.build_all`，
    顺序反了的话"第一次生成"也带上那份改动、两边一模一样 ⇒ 走不到这条分支（实测踩过）。
    """
    ctx = _ctx()
    real = modgen.build_all

    def fake(*args: object, **kwargs: object) -> modgen.Built:
        built = real(*args, **kwargs)  # type: ignore[arg-type]
        files = dict(built.files)
        files["zz_sitai_probe_unstable.txt"] = "第二次生成多出来的东西"
        return dataclasses.replace(built, files=files)

    monkeypatch.setattr(modgen, "build_all", fake)

    finding = modguard.gate_determinism(ctx)

    assert finding.ok is False
    text = finding.headline + "".join(finding.details)
    assert "两次生成不一致" in text, text  # 只有 L759 那段逐条点名才会给出这个前缀


# ────────────────────────── 结论文本：红的明细块 ──────────────────────────


def test_结论文本把红的明细也打出来() -> None:
    """`format_report` 的"失败 + 有明细"分支：红不能只说一句，要给出可执行的修法。"""
    report = modguard.Report(
        findings=(
            modguard.Finding(
                gate="1",
                title="① 测试闸门",
                ok=False,
                headline="红：故意造的失败",
                details=("明细一：改这里", "明细二：再改那里"),
            ),
        )
    )

    text = modguard.format_report(report)

    assert "① 测试闸门 —— 明细" in text
    assert "明细一：改这里" in text
    assert "未通过" in text
