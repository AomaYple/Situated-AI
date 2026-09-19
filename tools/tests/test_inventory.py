"""全仓「机械数字」的盘点看守 —— 防止又长出一张无人看守的表。

为什么需要它
-----------
这一轮反复踩到同一个形态：**文档里有一堆机械可核对的数字，而没有任何东西在看守**。
实测盘点（doc 13 整体生成、不计入）：

* 表格 578 张 —— 33 张由 `v3 tables` 生成、21 张有测试看守，
  其余里 **126 张含「真统计量列」而零看守**；
* 散文数字 133 个 —— 只有 19 个等于本文件某条断言的期望值。

数字本身会随游戏升级而漂，但**「又新增了一张无人看守的表」这件事不会有人发现** ——
除非把盘点本身变成检查。这就是本文件。

判定规则（宁可宽，别漏）
---------------------
一张表算「含真统计量列」要同时满足：

1. 有**非行号、非判读**的列（排除 `#` / `行` / `状态` / `类型` … —— 那些不是统计量）；
2. 该列名像统计量（次数 / 数量 / 文件数 / 条目 / 字节 / 定义数 / count / entries …）；
3. 该列 70% 以上的单元格是纯数字。

口径的局限（写清楚，免得被当成「全覆盖」）
--------------------------------------
* 它**只认表**，不认散文里的数字；散文那面的现状另记在下面的基线里；
* 它判不出「数字对不对」—— 那是 `v3 tables` / `v3 verify` / 各看守测试的事。
  这条只管**有没有人管**。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pdx import config, docgen

if TYPE_CHECKING:
    from pathlib import Path

#: doc 13 由 `v3 index` **整体重新生成**，其中的数字不可能过期，故不参与盘点。
FULLY_GENERATED_DOCS = frozenset({"13-common全量键名索引.md"})

#: 这些列名**不是统计量**：行号、序号、以及作者的判读标签。
NON_STAT = (
    "#",
    "行",
    "序号",
    "状态",
    "类型",
    "值类型",
    "领域",
    "作用方向",
    "首例",
    "首现位置",
    "官方 md 行",
    "建议",
    "备注",
    "说明",
)

#: 列名里出现这些词才可能是统计量。
STAT_HINT = (
    "次数",
    "数量",
    "文件数",
    "条目",
    "字节",
    "定义数",
    "键数",
    "合计",
    "总计",
    "count",
    "entries",
    "params",
    "blocks",
)

#: **未看守的机械表数量上限**。这是「欠债余额」：只许减少，不许增加。
#:
#: 进度 125 → 82：doc 05 的两张「假脚本化」表、doc 04/16 的「用了多少次」各一张、
#: doc 14 整族 20 张字段表、**doc 16 整族 23 张「键 → 计数」表**。生成表总数 31 → 77。
#:
#: 基线 125 来自 2026-09 的全仓盘点（用**本文件自己的判据**量的；
#: 早先一份临时脚本按略宽的判据量到 126，两者差在 ``NON_STAT`` 的宽窄）。
#: 做完一批就把这个数往下调 —— 调低是进度，**调高必须在提交信息里说明理由**。
UNGUARDED_TABLE_BUDGET = 82

#: 散文数字（表格之外）的现状，同样只许减少。见模块 docstring 的口径。
UNGUARDED_PROSE_BUDGET = 114


def _tables(path: Path) -> list[tuple[int, str, list[list[str]]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[tuple[int, str, list[list[str]]]] = []
    i = 0
    while i < len(lines):
        if (
            lines[i].startswith("|")
            and i + 1 < len(lines)
            and lines[i + 1].startswith("|")
            and set(lines[i + 1].strip()) <= set("|-: ")
        ):
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            out.append((i + 1, lines[i], rows))
            i = j
        else:
            i += 1
    return out


def _is_number(cell: str) -> bool:
    return bool(re.fullmatch(r"\**[\d][\d,]*\**", cell.strip()))


def _stat_columns(header: str, rows: list[list[str]]) -> list[str]:
    """表里「看起来是统计量」的列名，判据见模块 docstring。"""
    labels = [c.strip() for c in header.strip().strip("|").split("|")]
    out: list[str] = []
    for ci, label in enumerate(labels):
        low = label.lower()
        if any(x in label for x in NON_STAT):
            continue
        vals = [r[ci] for r in rows if ci < len(r)]
        if not vals or sum(_is_number(v) for v in vals) < max(2, int(len(vals) * 0.7)):
            continue
        if any(h in label or h in low for h in STAT_HINT):
            out.append(label)
    return out


def _generated_headers() -> dict[str, list[tuple[str, int]]]:
    """``文档名 → [(表头, occurrence), …]``。

    **必须带上 occurrence**：一条 spec 只覆盖**同表头的第 N 张**表。
    doc 14 里有好几张表头都是 ``| 字段 | 实测次数 | 说明 |``，而生成器只管其中一张 ——
    只按表头文本判「已看守」会把其余几张也算成有人管，于是盘点**少报**，
    给出虚假的「快做完了」。实测第一版就是这么错的（125 一下掉到 116，
    而实际只接了 3 张）。
    """
    out: dict[str, list[tuple[str, int]]] = {}
    for t in docgen.targets():
        for s in t.specs:
            out.setdefault(t.name, []).append((s.header, getattr(s, "occurrence", 0)))
    return out


def _is_guarded_by_spec(
    headers: list[str], index: int, generated: dict[str, list[tuple[str, int]]], doc: str
) -> bool:
    """第 ``index`` 张表是否落在某条 spec 的射程内。

    判定必须与 :func:`pdx.doc_tables._find_header` **同源**：那个函数用
    ``ln.startswith(spec.header)`` 找候选、再按 ``occurrence`` 取第 N 个。
    所以这里也按 ``startswith`` 逐条 spec 数匹配位置，而不是按「精确表头」数 ——
    两者在**表头互为前缀**时会得出不同的序号。实测踩过：
    ``| 令牌 | 形式 | 实测次数 |`` 是 ``| 令牌 | 形式 | 实测次数 | 说明 |``
    的前缀，文档里两张表，按精确表头数只有 1 个候选（序号 0），
    按 ``startswith`` 数有 2 个（序号 0、1）—— 于是生成器认第 2 张、
    而盘点认第 1 张，同一张表一边说已看守、一边说没看守。
    """
    for spec_header, occurrence in generated.get(doc, []):
        hits = [i for i, h in enumerate(headers) if h.startswith(spec_header[:24])]
        if occurrence < len(hits) and hits[occurrence] == index:
            return True
    return False


def _is_guarded(path: Path, header: str) -> bool:
    # 字节列由 test_docs_consistency 逐行核对
    if "字节" in header or "| B |" in header:
        return True
    # doc 16/17 的 §0 总览表由 test_doc_overview 核对
    return bool(
        path.name in {"16-外交军事与地图.md", "17-角色科技与呈现.md"}
        and header.startswith("| # | 目录 |")
    )


def _count_unguarded_tables() -> tuple[int, list[str]]:
    generated = _generated_headers()
    unguarded: list[str] = []
    for path in sorted(config.DOCS.glob("*.md")):
        if path.name in FULLY_GENERATED_DOCS:
            continue
        tables = _tables(path)
        headers = [h for _ln, h, _rows in tables]
        for index, (lineno, header, rows) in enumerate(tables):
            if not rows or _is_guarded(path, header):
                continue
            if _is_guarded_by_spec(headers, index, generated, path.name):
                continue
            if _stat_columns(header, rows):
                unguarded.append(f"{path.name}:{lineno} {header[:70]}")
    return len(unguarded), unguarded


def _count_unguarded_prose() -> int:
    """散文里「不等于本文件任何断言期望值」的不同数字个数。"""
    from pdx import verify

    bold = re.compile(r"\*\*([\d][\d,]*)\*\*")
    cnt = re.compile(r"(共|合计|总计|有)\s*\*{0,2}([\d][\d,]*)\s*个")
    claim_values: dict[str, set[int]] = {}
    for c in verify.CLAIMS:
        if isinstance(c.expected, int):
            claim_values.setdefault(c.doc, set()).add(c.expected)

    total = 0
    for md in sorted(config.DOCS.glob("*.md")):
        prose = "\n".join(
            ln
            for ln in md.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("|")
        )
        nums = {int(x.replace(",", "")) for x in bold.findall(prose)}
        nums |= {int(x.replace(",", "")) for _k, x in cnt.findall(prose)}
        total += len(nums - claim_values.get(md.name, set()))
    return total


def test_未看守的机械表不超过预算() -> None:
    """**欠债余额只许减少。**

    这条不是「有多少表」，而是「还有多少表没人管」。做完一批就把
    :data:`UNGUARDED_TABLE_BUDGET` 往下调；**上调必须说明理由** ——
    否则「又长出一张无人看守的表」永远不会有人发现。
    """
    n, examples = _count_unguarded_tables()
    assert n <= UNGUARDED_TABLE_BUDGET, (
        f"含统计量列、无人看守的表从 {UNGUARDED_TABLE_BUDGET} 涨到了 {n}。\n"
        f"要么接进 `v3 tables`／加看守测试，要么在提交信息里说明为什么允许它涨。\n"
        f"前 10 张：\n  " + "\n  ".join(examples[:10])
    )


def test_未看守的散文数字不超过预算() -> None:
    """散文数字那面的同一个余额。"""
    n = _count_unguarded_prose()
    assert n <= UNGUARDED_PROSE_BUDGET, (
        f"散文里无人看守的不同数字从 {UNGUARDED_PROSE_BUDGET} 涨到了 {n} —— "
        f"新增数字时请补断言，或说明为什么允许它涨"
    )


def test_盘点自身能跑出非零结果() -> None:
    """**元测试**：确保盘点真的在数东西，而不是恒为 0。

    一条「扫全仓、永远返回 0」的检查会让人以为已经清零了 ——
    比没有检查更糟（本仓库在哈希那件事上刚踩过同类的坑）。
    """
    n, _ = _count_unguarded_tables()
    assert n > 0, "盘点返回 0 张未看守表 —— 解析多半退化了，不是真的做完了"
    assert _count_unguarded_prose() > 0, "散文数字盘点返回 0 —— 同上"
    assert _stat_columns("| 目录 | 文件数 | 说明 |", [["a", "3", "x"], ["b", "4", "y"]]), (
        "列判定退化了"
    )
    assert not _stat_columns("| # | 项 | 状态 |", [["1", "a", "b"], ["2", "c", "d"]]), (
        "行号/状态列不该被当成统计量"
    )
