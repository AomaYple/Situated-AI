"""doc 16（外交军事与地图）剩下八张表的看守。

这一批的八张表统计单位都不是「字段」，各有各的坑：

* **文本级 vs 结构化**：`flags` / `settings` / `ai.*` 数的是「有多少个文件里出现过这个词」。
  两种口径只在**一个文件里出现两次**时分岔 —— 实测 `can_be_renegotiated`
  出现 27 次、只在 26 个文件里，而文档那一格写的是 27（列名却是「文件数」）。
* **任意深度**：`travel_network\\naval_network.txt` 的 `nodes` 在顶层、
  `province` 在匿名块里 —— 只看某一层都数不出那张表。
* **列名与口径不符**：`subject_types` 那一列原写「使用文件数」，但目录只有 1 个文件 ——
  那些 9 只可能是条目级出现次数（已改列名，且生成后**发现 6 行本来就写错了**）。

刻意不生成的两张表（本机 workshop mod 的快照）由
``pdx.doc16.NOT_GENERATED`` 与 ``test_inventory.NOT_GENERATED`` 各自记着理由。
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

from pdx import config, doc16
from pdx.doc_tables import norm_key
from pdx.usage import all_field_occurrences, word_file_counts

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

DOC = config.DOCS / "16-外交军事与地图.md"


def _skip() -> None:
    skip_if_no_game(DOC, config.GAME / "common" / "treaty_articles")


def test_文档里的表就是生成器的输出() -> None:
    _skip()
    assert_doc_matches_generated(DOC, doc16.doc_table_specs())


def test_每一行都有人认领() -> None:
    _skip()
    assert_every_row_claimed(DOC, doc16.doc_table_specs())


def test_两栏并排的取值集合没过期() -> None:
    """flags 与 settings 的版面是作者的，新增取值不会自己冒出来。"""
    _skip()
    for dir_rel, left, right, label in (
        ("common/treaty_articles", doc16._TREATY_FLAGS_LEFT, doc16._TREATY_FLAGS_RIGHT, "flags"),
        (
            "common/war_goal_types",
            doc16._SETTINGS_LEFT,
            doc16._SETTINGS_RIGHT,
            "settings",
        ),
    ):
        declared = {norm_key(k) for k in (*left, *right)}
        # 实测：目录里所有文件的文本里出现过的候选词 —— 用声明集合反查是否都还在
        counts = word_file_counts(dir_rel, sorted(declared))
        missing = [w for w, n in counts.items() if n == 0]
        assert not missing, f"{label} 表里这些取值在原版里已经不用了：{missing}"


def test_文件数与出现次数是两个口径() -> None:
    """`can_be_renegotiated` 正是那个「一个文件里出现两次」的样本。

    文档那一格写 27（出现次数），列名却是「文件数」—— 生成器给 26。
    这条测试把两种口径的差钉住：哪天它不再出现两次，说明游戏内容变了，
    那时该更新的是这条测试的注释，而不是悄悄让两个数相等。
    """
    _skip()
    counts = word_file_counts("common/treaty_articles", ["can_be_renegotiated"])
    assert counts["can_be_renegotiated"] == 26
    rows = doc_rows(DOC, "| flag | 文件数 | 文档 | | flag | 文件数 | 文档 |", 0)
    cell = next(r[1] for r in rows if r[0].strip("`") == "can_be_renegotiated")
    assert int(cell.strip("*")) == 26, f"那一格应当是文件数 26，实得 {cell!r}"


def test_travel_network_的两个层次都在() -> None:
    """顶层键（`nodes`/`connections`）与匿名块里的键（`province`/`from`…）缺一不可。"""
    _skip()
    counter = all_field_occurrences("common/travel_network")
    assert counter["nodes"] == 1, "顶层键 nodes 丢了"
    assert counter["connections"] == 1, "顶层键 connections 丢了"
    assert counter["province"] == counter["x"] == counter["y"] == counter["type"], "节点字段不等"
    assert counter["from"] == counter["to"], "连接字段不等"
    # ⚠️ 这个表头在本篇出现 4 次，本节那张是第 4 张（0 基下标 3）——
    # 与 `doc16.doc_table_specs()` 里的 occurrence 必须一致。
    listed = {r[0].strip("`") for r in doc_rows(DOC, "| 键 | 出现次数 | 说明 |", 3)}
    assert listed == {k for k in counter if counter[k]}, "表与实测的键集合不一致"


def test_subject_types_的列名与口径一致() -> None:
    """列名必须是「出现次数」（该目录只有 1 个文件）。"""
    _skip()
    text = DOC.read_text(encoding="utf-8")
    assert "| 键 | 出现次数 | 类型 | 备注 |" in text, "列名被改回「使用文件数」了？"
    files = sum(1 for _ in (config.GAME / "common" / "subject_types").rglob("*.txt"))
    assert files == 1, f"subject_types 现在有 {files} 个文件 —— 列名的理由要重写"


def test_刻意不生成的表仍在文档里() -> None:
    text = DOC.read_text(encoding="utf-8")
    for header, reason in doc16.NOT_GENERATED.items():
        assert header in text, f"排除清单里的表头在文档里找不到：{header}（理由：{reason}）"


def test_表名唯一且写盘幂等(tmp_path: Path) -> None:
    _skip()
    specs = doc16.doc_table_specs()
    assert_unique_names(specs)
    assert_write_free_and_idempotent(DOC, specs, tmp_path)
