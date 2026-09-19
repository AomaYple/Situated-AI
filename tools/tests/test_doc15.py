"""doc 15（政治人口与社会）的生成表看守。

七张表：§0 的 25 目录总览（两列数字）、`laws` 的前缀与字段表、
`interest_group_traits` 的门槛取值、`ideologies` 的逐文件定义数与五档态度、
`discrimination_traits` 的四类分布。口径写在 :mod:`pdx.doc15` 里。

这里额外守住三件**只有本篇才有**的事：

* `laws` 的 `00_` / `01_` / `02_` 前缀必须**划分完备**（否则有新前缀的文件没人统计）；
* §0 总览的行集合必须与 :data:`pdx.doc15._OVERVIEW_DIRS` 一致（少一行 = 漏一个目录）；
* 四类特质的合计必须等于该目录的定义总数（196 + 118 + 10 = 324）——
  这条把「前两行是总数与子集、不是互斥分组」这个容易搞错的口径钉住。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from _table_guards import (
    assert_doc_matches_generated,
    assert_every_row_claimed,
    assert_unique_names,
    assert_write_free_and_idempotent,
    doc_rows,
    skip_if_no_game,
)

from pdx import config, doc15

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

DOC = config.DOCS / "15-政治人口与社会.md"


def _skip() -> None:
    skip_if_no_game(DOC, config.GAME / "common" / "laws")


def test_文档里的表就是生成器的输出() -> None:
    _skip()
    assert_doc_matches_generated(DOC, doc15.doc_table_specs())


def test_每一行都有人认领() -> None:
    _skip()
    assert_every_row_claimed(DOC, doc15.doc_table_specs())


def test_laws_前缀划分完备() -> None:
    """每个 ``laws/*.txt`` 都要落进某一行（前缀是类别序号，不存在「其它」）。"""
    _skip()
    base = config.GAME / "common/laws"
    names = [p.name for p in base.glob("*.txt")]
    numbered = [n for n in names if re.match(r"^\d+_", n)]
    assert len(numbered) == len(names), (
        f"这些文件名不以数字前缀开头，前缀表覆盖不到：{sorted(set(names) - set(numbered))}"
    )
    counted = sum(int(r[2].replace(",", "")) for r in doc_rows(DOC, "| 前缀 | 含义 | 文件数 |", 0))
    assert counted == len(names), f"前缀表合计 {counted} ≠ laws 目录 .txt 数 {len(names)}"


def test_第0节总览覆盖全部目录() -> None:
    """行集合必须与代码里的目录清单一致 —— 少一个目录就会静默漏统计。"""
    _skip()
    rows = doc_rows(DOC, doc15._OVERVIEW_HEADER, 0)
    listed = {r[1].strip("`*") for r in rows}
    assert listed == set(doc15._OVERVIEW_DIRS), (
        f"文档与代码的目录清单不一致：只在文档 {sorted(listed - set(doc15._OVERVIEW_DIRS))}，"
        f"只在代码 {sorted(set(doc15._OVERVIEW_DIRS) - listed)}"
    )
    missing = [d for d in doc15._OVERVIEW_DIRS if not (config.GAME / "common" / d).is_dir()]
    assert not missing, f"这些目录在游戏里已经不存在了：{missing}"


def test_五档态度的合计与散文一致() -> None:
    """把散文里的「合计 N 处」也变成可核对的数字。

    散文不在生成器射程内，但它和表说的是同一件事 —— 表变了而散文没变，
    读者就会看到两个互相矛盾的数。
    """
    _skip()
    total = sum(int(r[1].replace(",", "")) for r in doc_rows(DOC, "| 态度值 | 次数 |", 0))
    text = DOC.read_text(encoding="utf-8")
    m = re.search(r"合计\s*([\d,]+)\s*处", text)
    assert m, "找不到「合计 N 处」那句话 —— 散文被改过？"
    assert int(m.group(1).replace(",", "")) == total, (
        f"散文写「合计 {m.group(1)} 处」，表里五行相加是 {total}"
    )


def test_四类特质的合计等于目录定义数() -> None:
    """196(语言) + 118(传承**合计**) + 10(传统) = 324 = 该目录顶层定义数。

    文档的前两行是「总数 + 其中的宗教子集」，不是互斥分组；
    按互斥理解会得到 332，与目录里的定义数不符 —— 这条测试就是防这个误读。
    """
    _skip()
    rows = doc_rows(DOC, "| 特质类别 | 定义数 | 被谁引用（**【实测】**） |", 0)
    nums = [int(r[1].replace(",", "")) for r in rows]
    from pdx.usage import file_definition_counts

    total = sum(file_definition_counts("common/discrimination_traits").values())
    # 第 2 行（宗教 heritage）是第 1 行的子集，不计入合计。
    assert nums[0] + nums[2] + nums[3] == total, (
        f"表里 118 + 196 + 10 = {nums[0] + nums[2] + nums[3]} ≠ 目录定义数 {total}"
    )


def test_表名唯一且写盘幂等(tmp_path: Path) -> None:
    _skip()
    specs = doc15.doc_table_specs()
    assert_unique_names(specs)
    assert_write_free_and_idempotent(DOC, specs, tmp_path)
