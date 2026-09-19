"""几篇「只有一两张表」的文档共用的看守（doc 03 / 10 / 11 / 12 / 14 / 18 / 20）。

为什么合在一个文件里
-------------------
这七篇各自只贡献一到两张表，为每篇建一个测试文件只会让 `tools/tests/` 更难读。
它们共用的还是那两条判据（文档 == 生成结果、每一行都有人认领），
外加各自一两条本篇特有的恒等式：

* **doc 03**：Top 25 必须真的是前 25（没有别的 NAI 前缀比表里最小的还大）；
* **doc 10**：四类语义相加 = 字段总数 60；三形态相加也 = 60；
* **doc 11 / 18**：两张表说的是同一批数字（`common\\history\\` 的 22 个子目录），
  必须一致；
* **doc 14**：`travel_network` 的令牌数与 doc 16 §4.6 那张表同源；
* **doc 12 / 02 / 14 的 mod 前缀表**：刻意不生成，但仍在文档里（排除清单不许失效）。
"""

from __future__ import annotations

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

from pdx import ai, config, doc_tables, install_tree, usage

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_DOCS = {
    "doc03": "03-AI系统.md",
    "doc10": "10-AI策略字段参考.md",
    "doc11": "11-历史初始状态与AI策略分配.md",
    "doc18": "18-history初始状态系统.md",
    "doc20": "20-引擎共享层jomini与clausewitz.md",
    "doc14": "14-经济与生产系统.md",
}


def _doc(name: str) -> Path:
    return config.DOCS / _DOCS[name]


def _specs() -> list:
    return [
        *ai.doc_table_specs(),
        *install_tree.doc_misc_specs(),
        *(x for x in usage.doc_table_specs() if "doc14" in x.name),
    ]


@pytest.mark.parametrize("key", ["doc03", "doc10", "doc11", "doc18", "doc20", "doc14"])
def test_文档里的表就是生成器的输出(key: str) -> None:
    skip_if_no_game(_doc(key))
    prefix = "doc20" if key == "doc20" else key
    specs = [s for s in _specs() if s.name.startswith(f"{prefix} ")]
    assert specs, f"{key} 没有登记任何生成表"
    assert_doc_matches_generated(_doc(key), specs)


@pytest.mark.parametrize("key", ["doc03", "doc10", "doc11", "doc18", "doc20", "doc14"])
def test_每一行都有人认领(key: str) -> None:
    skip_if_no_game(_doc(key))
    prefix = "doc20" if key == "doc20" else key
    specs = [s for s in _specs() if s.name.startswith(f"{prefix} ")]
    assert_every_row_claimed(_doc(key), specs)


def test_doc03_的_Top25_真的是前_25() -> None:
    """表里最小的那个数，不能有别的前缀比它大（否则「Top25」名不副实）。"""
    skip_if_no_game(_doc("doc03"))
    counts = ai.nai_prefix_counts()
    listed = {r[0].strip("`") for r in doc_rows(_doc("doc03"), "| 前缀 | 数量 | 领域 |", 0)}
    smallest = min(counts[p] for p in listed)
    outside = {p: n for p, n in counts.items() if p not in listed and n > smallest}
    assert not outside, f"这些前缀比表里最小的 {smallest} 还大，却没进 Top25：{outside}"


def test_doc10_两类分类都覆盖全部字段() -> None:
    """四类语义与三种形态必须各自加总到 60（字段总数）。"""
    skip_if_no_game(_doc("doc10"))
    semantics = sum(int(c[1]) for _k, c in ai.semantic_rows())
    shapes = sum(int(c[1]) for _k, c in ai.shape_rows())
    total = len(ai._strategy_fields())
    assert total == 60, f"ai_strategy 字段数从 60 变成 {total} —— 两张表的标题要跟着改"
    assert semantics == total, f"语义四类相加 {semantics} ≠ {total}"
    assert shapes == total, f"形态三类相加 {shapes} ≠ {total}"


def test_doc11_与_doc18_说的是同一批数字() -> None:
    """两张表都描述 `common\\history\\`，逐行数字必须一致。"""
    skip_if_no_game(_doc("doc11"), _doc("doc18"))
    stats = {s.name: s.files for s in install_tree.rows_of(config.GAME / "common" / "history")}
    d11 = doc_rows(_doc("doc11"), "| 子目录 | 文件数 | 作用 |", 0)
    for row in d11:
        name = row[0].strip("*`")  # 文档里 `ai` 那一行是**加粗**的
        if " · " in name:  # 合并行：值是「各 N」
            assert row[1].startswith("各 "), f"合并行的值应当是「各 N」：{row[1]!r}"
            assert {stats[n] for n in install_tree._HISTORY_SINGLES} == {int(row[1][2:])}
            continue
        cell = row[1].strip("*")
        assert int(cell) == stats[name], f"{name}: 表 {row[1]} ≠ 实测 {stats[name]}"
    d18 = doc_rows(_doc("doc18"), "| 子目录 | 文件数 | **顶层包装块** | 主要效果 |", 0)
    assert len(d18) == len(stats), f"doc 18 列了 {len(d18)} 行，实测 {len(stats)} 个子目录"
    for row in d18:
        assert int(row[1].strip("*")) == stats[row[0].strip("*`")]


def test_doc14_的令牌数与_doc16_同源() -> None:
    """同一个文件的两张问法：doc 14 只看 `nodes`/`connections` 内部，doc 16 更全。"""
    skip_if_no_game(_doc("doc14"))
    counter = usage.all_field_occurrences("common/travel_network")
    rows = doc_rows(_doc("doc14"), "| 令牌 | 形式 | 实测次数 | 说明 |", 0)
    for row in rows:
        # ``| `x` / `y` |`` 是合并行：**逐段**剥反引号（用生成器同一个 `key_parts`），
        # 直接 ``.strip("`")`` 会剩下里层那两个，查表得 0（实测踩过）。
        for token in doc_tables.key_parts(row[0]):
            assert int(row[2].replace(",", "")) == counter[token], row


@pytest.mark.parametrize(
    ("path", "header"),
    [
        ("02-Mod结构与加载.md", "| 前缀 | 次数 | 语义（由行为推断） |"),
        ("02-Mod结构与加载.md", "| 使用次数 | 目录 |"),
        ("12-真实mod解剖与改造面地图.md", "| 前缀 | 次数 |"),
        ("14-经济与生产系统.md", "| 关键字 | 出现次数 |"),
    ],
)
def test_刻意不生成的_mod_前缀表仍在文档里(path: str, header: str) -> None:
    """这四张统计的是**本机订阅的 mod**，换机器就变 —— 排除清单不许指向不存在的表。"""
    text = (config.DOCS / path).read_text(encoding="utf-8")
    assert header in text, f"{path} 里找不到 {header!r}"


def test_表名唯一且写盘幂等(tmp_path: Path) -> None:
    skip_if_no_game(_doc("doc03"))
    specs = _specs()
    assert_unique_names(specs)
    assert_write_free_and_idempotent(
        _doc("doc10"), [s for s in specs if s.name.startswith("doc10 ")], tmp_path
    )
