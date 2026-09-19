"""看守「由工具生成的表格」这条链 —— doc 05 与 doc 19。

为什么单独一个文件（而不是并进 ``test_defines_tables.py``）
----------------------------------------------------------
上一轮只覆盖 doc 05。这一轮把替换算法抽成了 :mod:`pdx.doc_tables` 并推广到
doc 19 与 doc 08，**通用机制本身**也必须被测 —— 它现在同时托着 31 张表，
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
#: 而它们恰恰是最该在 CI 上跑的部分（通用机制一回归就是 31 张表一起烂）。
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

#: 三列表（键 / 数值 / 散文）。「新键追加」的用例必须用三列表 ——
#: 只有存在散文列时，NEW_CELL 才有意义。曾经拿两列的表头配三列的数据行，
#: 于是断言「新行里应当出现待补」永远不成立，测试却看不出自己错了。
HEAD3_LINE = "| 名称 | 数值 | 说明 |"
HEAD3 = HEAD3_LINE + "\n|---|---:|---|\n"


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
    """新行必须**带名字**，且再跑一次不能又追加一条。

    这条原先只断言「文本里出现了 NEW_CELL」—— 那太弱了：生成器把**键列**
    也填成「待补」时它照样通过，于是追加出来的是一行没有名字的垃圾
    （实测产出 `| —— **待补** | —— **待补** | 3 |`），而且下一轮认不出
    这行是自己写的，`--write` 跑几次就追加几条，表格永远红。
    """
    p = _doc(tmp_path, f"{HEAD3}| `a.txt` | 1 | 说明甲 |\n")
    spec = doc_tables.KeyedTableSpec(
        name="t", header=HEAD3_LINE, cells=lambda: [("a.txt", {1: "1"}), ("c.txt", {1: "3"})]
    )
    doc_tables.patch_doc(p, [spec], write=True)
    text = p.read_text(encoding="utf-8")

    assert "| `c.txt` | 3 |" in text, f"新行的键必须写进去，实际：\n{text}"
    assert doc_tables.NEW_CELL in text, "新行应提示人来补说明列（说明列是散文）"

    # 幂等：再跑两次，行数不能增长
    for _ in range(2):
        doc_tables.patch_doc(p, [spec], write=True)
    rows = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("| `")]
    assert len(rows) == 2, f"追加不幂等，行数变成了 {len(rows)}：{rows}"
    # 新行必须与表头**同宽**（3 列）—— 短一截的行在 Markdown 里会缺格，
    # 而作者也看不出该补哪一列。
    assert rows[1].count("|") == 4, f"新行列数与表头不一致：{rows[1]}"


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
    assert len(targets) >= 3, "至少应登记 doc 05、doc 08 与 doc 19"
    assert sum(len(t.specs) for t in targets) >= 30


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


# ── 5. 合并行与「绝不静默删行」────────────────────────────────
@_unit
def test_合并行按分隔符拆开逐个查表(tmp_path: Path) -> None:
    """``| `a.dll` / `b.dll` | 10 / 20 |`` 这种一行多条目也要能更新。

    doc 08 的 §3 就是这么写的。旧行为是**查不到就把整行删掉** ——
    实测表格短了 5 行、后面所有行的散文跟着错位。错的散文比错的数字更难发现。
    """
    doc = tmp_path / "d.md"
    doc.write_text(
        "| 文件 | 字节 | 用途说明 |\n|---|---|---|\n"
        "| `a.dll` / `b.dll` | 1 / 2 | 两个一组 |\n"
        "| `c.dll` | 3 | 单个 |\n",
        encoding="utf-8",
        newline="\n",
    )
    spec = doc_tables.KeyedTableSpec(
        name="t",
        header="| 文件 | 字节 | 用途说明 |",
        cells=lambda: [("a.dll", {1: "10"}), ("b.dll", {1: "20"}), ("c.dll", {1: "30"})],
        append_new=False,
    )
    doc_tables.patch_doc(doc, [spec], write=True)
    rows = [ln for ln in doc.read_text(encoding="utf-8").splitlines() if ln.startswith("| `")]
    assert rows[0] == "| `a.dll` / `b.dll` | 10 / 20 | 两个一组 |", rows[0]
    assert rows[1] == "| `c.dll` | 30 | 单个 |", rows[1]


@_unit
def test_查不到的键默认保留而不是删掉(tmp_path: Path) -> None:
    """未匹配的行**原样保留** —— 删行会让整张表错位。

    这是默认行为，不是可选项：把「未匹配」解释成「该删」是这类生成器
    最容易犯、也最难发现的错。
    """
    doc = tmp_path / "d.md"
    doc.write_text(
        "| 文件 | 字节 | 用途说明 |\n|---|---|---|\n"
        "| `unknown.bin` | 1 | 作者自己加的一行 |\n"
        "| `a.dll` | 2 | 正常的 |\n",
        encoding="utf-8",
        newline="\n",
    )
    spec = doc_tables.KeyedTableSpec(
        name="t",
        header="| 文件 | 字节 | 用途说明 |",
        cells=lambda: [("a.dll", {1: "20"})],
        append_new=False,
    )
    doc_tables.patch_doc(doc, [spec], write=True)
    text = doc.read_text(encoding="utf-8")
    assert "`unknown.bin` | 1 | 作者自己加的一行" in text, text
    assert "`a.dll` | 20 | 正常的" in text, text


@_unit
def test_显式开_allow_drop_才会删行(tmp_path: Path) -> None:
    doc = tmp_path / "d.md"
    doc.write_text(
        "| 文件 | 字节 | 用途说明 |\n|---|---|---|\n"
        "| `gone.txt` | 1 | 已经没了 |\n"
        "| `a.dll` | 2 | 还在 |\n",
        encoding="utf-8",
        newline="\n",
    )
    spec = doc_tables.KeyedTableSpec(
        name="t",
        header="| 文件 | 字节 | 用途说明 |",
        cells=lambda: [("a.dll", {1: "20"})],
        append_new=False,
        allow_drop=True,
    )
    doc_tables.patch_doc(doc, [spec], write=True)
    text = doc.read_text(encoding="utf-8")
    assert "gone.txt" not in text, "allow_drop=True 时该行应当被删掉"
    assert "`a.dll` | 20 | 还在" in text


@_unit
def test_未匹配行在枚举型表上会出声(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """声称枚举全部条目的表，遇到解释不了的行必须提示。

    不然就是最难发现的一类失效：游戏升级删掉某个目录，它的行带着旧数字留在
    表里，而 `v3 tables` 照样报「全部一致」—— 表格看着完整、数字却已经死了。
    """
    p = _doc(
        tmp_path,
        f"{HEAD3}| `a.txt` | 1 | 说明甲 |\n| `vanished-dir` | 2 | 这个目录没了 |\n",
    )
    spec = doc_tables.KeyedTableSpec(
        name="enum", header=HEAD3_LINE, cells=lambda: [("a.txt", {1: "1"})]
    )
    doc_tables.patch_doc(p, [spec], write=True)
    err = capsys.readouterr().err
    assert "未匹配" in err, f"没有出声，stderr={err!r}"
    assert "vanished-dir" in err, f"没点名是哪一行，stderr={err!r}"
    # 行仍然保留（默认不删）
    assert "`vanished-dir` | 2 | 这个目录没了" in p.read_text(encoding="utf-8")


@_unit
def test_子集型表不出声(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """只覆盖子集的表（节选、只更新几行）未匹配是设计使然，不该报。

    实测给全部表都出声会稳定报三张表的十几行 —— 那种噪声会训练人忽略这条
    提示，比不出声更糟。
    """
    p = _doc(tmp_path, f"{HEAD3}| `a.txt` | 1 | 说明甲 |\n| `作者加的一行` | 2 | 说明 |\n")
    spec = doc_tables.KeyedTableSpec(
        name="subset",
        header=HEAD3_LINE,
        cells=lambda: [("a.txt", {1: "1"})],
        append_new=False,
    )
    doc_tables.patch_doc(p, [spec], write=True)
    assert "未匹配" not in capsys.readouterr().err


# ── 6. 「别夺走作者信息」的四条细则（都是实测撞出来的）────────
@_unit
def test_加粗的键也能匹配上(tmp_path: Path) -> None:
    """``| **`x`** | 5 |`` 里的加粗不该挡住匹配。

    doc 16 有大量加粗的键。``_norm_key`` 不剥星号时那些行**永远匹配不上**，
    于是数字**永远不会被更新**（静默过期），而盘点还认为整张表「已看守」。
    """
    p = _doc(tmp_path, f"{HEAD3}| **`a.txt`** | 1 | 说明甲 |\n")
    spec = doc_tables.KeyedTableSpec(
        name="t", header=HEAD3_LINE, cells=lambda: [("a.txt", {1: "9"})], append_new=False
    )
    doc_tables.patch_doc(p, [spec], write=True)
    assert "| **`a.txt`** | 9 | 说明甲 |" in p.read_text(encoding="utf-8")


@_unit
def test_值没变的行连排版一起保留(tmp_path: Path) -> None:
    """``| k | 5 | ❌ | |`` 不该被重拼成 ``| k | 5 | ❌ |  |``。

    Markdown 渲染一样，但 diff 里是两行差异 —— 实测 89 行的纯空格差异
    把真正的改动淹掉了。
    """
    body = f"{HEAD3}| **`a.txt`** | 5 | ❌ | |\n"
    p = _doc(tmp_path, body)
    spec = doc_tables.KeyedTableSpec(
        name="t", header=HEAD3_LINE, cells=lambda: [("a.txt", {1: "5"})], append_new=False
    )
    doc_tables.patch_doc(p, [spec], write=True)
    assert p.read_text(encoding="utf-8") == body, "值没变却改了排版"


@_unit
def test_已有的空单元格不会被填成待补(tmp_path: Path) -> None:
    """作者故意留空的末尾列不该被写成「—— **待补**」。

    实测误伤过 69 行 —— 那是**替作者加话**，不是补全。
    """
    p = _doc(tmp_path, f"{HEAD3}| `a.txt` | 1 | |\n")
    spec = doc_tables.KeyedTableSpec(
        name="t", header=HEAD3_LINE, cells=lambda: [("a.txt", {1: "9"})], append_new=False
    )
    doc_tables.patch_doc(p, [spec], write=True)
    text = p.read_text(encoding="utf-8")
    assert doc_tables.NEW_CELL not in text, text
    # 不断言尾部空格：**值变了的行**会被重拼（``| |`` → ``|  |``），
    # 那是重拼的必然结果；要紧的是空单元格没被写成「待补」。
    assert "| `a.txt` | 9 |" in text, text


@_unit
def test_单元格里的括注被保留(tmp_path: Path) -> None:
    """``**77**（可重复）`` 更新成 ``**80**（可重复）`` —— 只换数字。"""
    p = _doc(tmp_path, f"{HEAD3}| `a.txt` | **77**（可重复） | 说明甲 |\n")
    spec = doc_tables.KeyedTableSpec(
        name="t", header=HEAD3_LINE, cells=lambda: [("a.txt", {1: "80"})], append_new=False
    )
    doc_tables.patch_doc(p, [spec], write=True)
    assert "| `a.txt` | **80**（可重复） | 说明甲 |" in p.read_text(encoding="utf-8")


@_unit
def test_N分之M的分母被保留(tmp_path: Path) -> None:
    """``**239 / 239**``（239 个条目里 239 个）→ 只换分子。"""
    p = _doc(tmp_path, f"{HEAD3}| `a.txt` | **239 / 239** | 说明甲 |\n")
    spec = doc_tables.KeyedTableSpec(
        name="t", header=HEAD3_LINE, cells=lambda: [("a.txt", {1: "240"})], append_new=False
    )
    doc_tables.patch_doc(p, [spec], write=True)
    assert "| `a.txt` | **240 / 239** | 说明甲 |" in p.read_text(encoding="utf-8")


@_unit
def test_合并行不套N分之M规则(tmp_path: Path) -> None:
    """``| `a` / `b` | 10 / 20 |`` 里的 ``/`` 是**条目分隔符**，不是「10 分之 20」。

    套用「保留分母」的规则会把它改成 ``10 / 2``（实测被本文件的原有用例抓到）。
    """
    p = _doc(tmp_path, f"{HEAD3}| `a.dll` / `b.dll` | 1 / 2 | 两个一组 |\n")
    spec = doc_tables.KeyedTableSpec(
        name="t",
        header=HEAD3_LINE,
        cells=lambda: [("a.dll", {1: "10"}), ("b.dll", {1: "20"})],
        append_new=False,
    )
    doc_tables.patch_doc(p, [spec], write=True)
    assert "| `a.dll` / `b.dll` | 10 / 20 | 两个一组 |" in p.read_text(encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
