"""看守「由工具生成的表格」这条链 —— doc 05 与 doc 19。

为什么单独一个文件（而不是并进 ``test_defines_tables.py``）
----------------------------------------------------------
上一轮只覆盖 doc 05。这一轮把替换算法抽成了 :mod:`pdx.doc_tables` 并推广到
doc 19，**通用机制本身**也必须被测 —— 它现在同时托着 9 张表，
一个回归会让全部 9 张一起烂掉，而它们的共同症状是「文档悄悄过期、没人发现」。

三层各测一次：

1. **通用机制**（:mod:`pdx.doc_tables`）—— 用合成文档测，跑得快、边界清楚；
2. **登记表**（:mod:`pdx.docgen`）—— 每张登记的表都必须在文档里找得到；
3. **文档现值** == 生成结果 —— 这条是核心，失败说明有人手改了表。
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from pdx import config, doc_tables, docgen, game_root

if TYPE_CHECKING:
    from pathlib import Path

#: 合成文档那几条**不需要游戏** —— 它们是通用机制的单元测试。
#: 早先整个文件打了 module 级 ``integration``，于是 CI 上连它们也一起跳过，
#: 而它们恰恰是最该在 CI 上跑的部分（通用机制一回归就是 9 张表一起烂）。
_unit = pytest.mark.unit

#: 要读游戏本体的用例：打 ``integration``（conftest 在无游戏时自动跳过）
#: 并附 ``skipif``（本机跳过时给出原因，而不是静默）。
_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")


# ── 1. 通用机制（合成文档，不需要游戏）──────────────────────
def _doc(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "d.md"
    p.write_text(body, encoding="utf-8")
    return p


HEAD_LINE = "| 名称 | 数值 |"
HEAD = HEAD_LINE + "\n|---|---:|\n"


@_unit
def test_整表替换只动数据行(tmp_path: Path) -> None:
    p = _doc(
        tmp_path,
        f"# 标题\n\n{HEAD}| a | 1 |\n| b | 2 |\n\n> 表后的说明\n",
    )
    spec = doc_tables.TableSpec(name="t", header=HEAD_LINE, rows=lambda: ["| a | 9 |", "| b | 8 |"])
    doc_tables.patch_doc(p, [spec], write=True)
    text = p.read_text(encoding="utf-8")
    assert "| a | 9 |" in text
    assert "| b | 8 |" in text
    assert "# 标题" in text, "表头之外的散文被动了"
    assert "> 表后的说明" in text, "表后的散文被动了"


@_unit
def test_行数可以变长(tmp_path: Path) -> None:
    """游戏升级后多出一条映射 —— 表**必须**跟着变长。

    第一版把「生成行数 == 文档现有行数」当成功条件，于是恰恰在
    最需要它的时候拒绝工作。
    """
    p = _doc(tmp_path, f"{HEAD}| a | 1 |\n\n尾部\n")
    spec = doc_tables.TableSpec(name="t", header=HEAD_LINE, rows=lambda: ["| a | 1 |", "| b | 2 |"])
    doc_tables.patch_doc(p, [spec], write=True)
    text = p.read_text(encoding="utf-8")
    assert "| b | 2 |" in text
    assert text.index("| b | 2 |") < text.index("尾部"), "新行插到了表外"


@_unit
def test_按键合并保留散文与行序(tmp_path: Path) -> None:
    """doc 19 根目录文件表就是这个形状：数字列由工具管，说明列是散文。

    两条都在这里钉死：**散文保留**、**行序沿用文档**（文档按语义排，
    生成器按文件名排会把它打乱）。
    """
    p = _doc(tmp_path, f"{HEAD}| `b.txt` | 1 | 说明乙 |\n| `a.txt` | 2 | 说明甲 |\n")
    spec = doc_tables.KeyedTableSpec(
        name="t",
        header=HEAD_LINE,
        cells=lambda: [("a.txt", {1: "20"}), ("b.txt", {1: "10"})],
    )
    doc_tables.patch_doc(p, [spec], write=True)
    text = p.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.startswith("| `")]
    assert lines[0].startswith("| `b.txt` | 10 | 说明乙"), lines[0]
    assert lines[1].startswith("| `a.txt` | 20 | 说明甲"), lines[1]


@_unit
def test_新键会追加并标注待补(tmp_path: Path) -> None:
    p = _doc(tmp_path, f"{HEAD}| `a.txt` | 1 | 说明甲 |\n")
    spec = doc_tables.KeyedTableSpec(
        name="t", header=HEAD_LINE, cells=lambda: [("a.txt", {1: "1"}), ("c.txt", {1: "3"})]
    )
    doc_tables.patch_doc(p, [spec], write=True)
    assert doc_tables.NEW_CELL in p.read_text(encoding="utf-8"), "新行应提示人来补说明列"


@_unit
def test_同表头的第N张靠_occurrence_区分(tmp_path: Path) -> None:
    """doc 19 的三张「逻辑名 | 实际路径」表头相同 —— 不区分就永远只改第一张。"""
    p = _doc(tmp_path, f"{HEAD}| a | 1 |\n\n中间\n\n{HEAD}| a | 2 |\n")
    spec = doc_tables.TableSpec(
        name="t2", header=HEAD_LINE, rows=lambda: ["| a | 99 |"], occurrence=1
    )
    doc_tables.patch_doc(p, [spec], write=True)
    text = p.read_text(encoding="utf-8")
    assert "| a | 1 |" in text, "第一张表不该被改"
    assert "| a | 99 |" in text


@_unit
def test_表头找不到时报错而不是静默跳过(tmp_path: Path) -> None:
    p = _doc(tmp_path, "# 没有表格\n")
    spec = doc_tables.TableSpec(name="t", header=HEAD_LINE, rows=lambda: ["| a | 1 |"])
    with pytest.raises(doc_tables.TableNotFoundError):
        doc_tables.patch_doc(p, [spec], write=False)


@_unit
def test_生成空表时报错(tmp_path: Path) -> None:
    p = _doc(tmp_path, HEAD + "| a | 1 |\n")
    spec = doc_tables.TableSpec(name="t", header=HEAD_LINE, rows=list)
    with pytest.raises(doc_tables.TableMalformedError):
        doc_tables.patch_doc(p, [spec], write=False)


@_unit
def test_check_不写盘(tmp_path: Path) -> None:
    body = f"{HEAD}| a | 1 |\n"
    p = _doc(tmp_path, body)
    spec = doc_tables.TableSpec(name="t", header=HEAD_LINE, rows=lambda: ["| a | 2 |"])
    diff = doc_tables.check_doc(p, [spec])
    assert len(diff) == 1
    assert p.read_text(encoding="utf-8") == body, "check_doc 不该改文件"


# ── 2. 登记表 ──────────────────────────────────────────────
@_unit
def test_每张登记的表都能在文档里找到() -> None:
    for target in docgen.targets():
        assert target.path.is_file(), f"{target.name} 不存在"
        text = target.path.read_text(encoding="utf-8")
        for spec in target.specs:
            hits = [ln for ln in text.splitlines() if ln.startswith(spec.header)]
            assert len(hits) > spec.occurrence, (
                f"{target.name} 里找不到表 {spec.name!r} 的表头第 {spec.occurrence + 1} 次出现"
            )


@_unit
def test_登记表非空() -> None:
    targets = docgen.targets()
    assert len(targets) >= 2, "至少应登记 doc 05 与 doc 19"
    assert sum(len(t.specs) for t in targets) >= 10


# ── 3. 生成结果非空（要读游戏，故需游戏）────────────────────
@pytest.mark.integration
@_game
def test_生成结果非空() -> None:
    for target in docgen.targets():
        for spec in target.specs:
            rows = spec.rows() if isinstance(spec, doc_tables.TableSpec) else spec.cells()
            assert rows, f"{target.name} 的 {spec.name!r} 生成了 0 行"


# ── 4. 与真实游戏比对（需要游戏）────────────────────────────
@pytest.mark.integration
@_game
def test_全部生成表都与文档一致() -> None:
    """**核心**：文档现值必须等于重新生成的结果。

    失败通常意味着两件事之一：改了生成器却没跑 `v3 tables --write`，
    或者游戏升级后数据真的变了（那就该连带更新文档里的散文数字）。
    """
    diff = docgen.check_all()
    detail = "\n".join(
        f"  {n}:{ln}\n    文档: {a[:80]}\n    生成: {b[:80]}" for n, ln, a, b in diff[:8]
    )
    assert not diff, f"{len(diff)} 行与生成结果不一致（跑 `v3 tables --write` 可修）：\n{detail}"


@pytest.mark.integration
@_game
def test_生成是幂等的() -> None:
    for target in docgen.targets():
        before = target.path.read_text(encoding="utf-8")
        try:
            doc_tables.patch_doc(target.path, target.specs, write=True)
            once = target.path.read_text(encoding="utf-8")
            doc_tables.patch_doc(target.path, target.specs, write=True)
            assert target.path.read_text(encoding="utf-8") == once, f"{target.name} 跑两次结果不同"
        finally:
            target.path.write_text(before, encoding="utf-8", newline="\n")


@pytest.mark.integration
@_game
def test_paths_settings_分组覆盖全部映射() -> None:
    """doc 19 三张分组表的键加起来必须**恰好**是 `paths.settings` 的全部映射。

    漏一个键 → 那条映射在文档里查不到；多一个键 → 生成时会抛 LookupError。
    这是「39 条映射」那句话的机械对应物。
    """
    declared = {
        *game_root._GFX_GROUP,
        *game_root._CONTENT_SOURCE_GROUP,
        *game_root._UI_AUDIO_GROUP,
    }
    actual = {name for name, _ in game_root.paths_settings()}
    assert not actual - declared, f"paths.settings 里这些映射没进文档：{sorted(actual - declared)}"
    assert not declared - actual, (
        f"文档里这些映射在 paths.settings 里已不存在：{sorted(declared - actual)}"
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
