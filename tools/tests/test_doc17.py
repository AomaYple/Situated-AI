"""doc 17 的 24 张生成表 —— 守住生成链，尤其是「静默不更新」这一类失效。

为什么单独一个文件
-----------------
doc 17 是**口径最杂**的一篇：字段出现次数、逐文件定义数、取值分布、文本级统计
四种口径混在同一篇里，而其中三处是「口径混在一张表里」（块内字段 + 顶层字段、
顶层字段 + 子字段、两栏并排的分布表）。这类错误**不会报错**：

* 表头指错列 → 数字写进隔壁列；
* occurrence 数错 → A 目录的次数写进 B 目录的表；
* 键的写法与计数器不一致 → 整列写 0（实测撞过：忘了过 ``norm_key``）;
* 这些表 ``append_new=False``，**未匹配的行连警告都不打**。

所以这里除了「文档 == 生成结果」之外，还要断言**每一行都有人认领** ——
没有这一条，键写错时表格看着完好、数字却已经死了。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from _table_guards import (
    assert_doc_matches_generated,
    assert_every_row_claimed,
    assert_unique_names,
    assert_write_free_and_idempotent,
)

from pdx import config, doc17, doc_tables

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

DOC = config.DOCS / "17-角色科技与呈现.md"

#: 这几张表的数据源在 `localization\` 而不是 `common\`，另有前置文件检查。
_NEEDS = (
    config.GAME / "common",
    config.GAME / "localization/english/concepts_l_english.yml",
)


def _skip_if_no_game() -> None:
    if not DOC.is_file():
        pytest.skip("doc 17 不存在")
    if not all(p.exists() for p in _NEEDS):
        pytest.skip("游戏目录不可用")


def test_文档里的表就是生成器的输出() -> None:
    """**核心**：文档现值必须等于重新生成的结果。"""
    _skip_if_no_game()
    assert_doc_matches_generated(DOC, doc17.doc_table_specs())


def test_每一行都有人认领() -> None:
    """**防静默过期**：每一张表里的每一行，都要被某条 spec 的键覆盖到。

    判定细节见 :mod:_table_guards —— 它是 doc 06 / 15 / 17 共用的那套。
    """
    _skip_if_no_game()
    assert_every_row_claimed(DOC, doc17.doc_table_specs())


def test_分布表声明的取值没有过期() -> None:
    """两栏并排的分布表：**实测取值集合必须等于声明集合**。

    这两栏的版面是作者的（哪些值放左栏没有规则可推），所以生成器只按行更新数字、
    不重排。代价是「新增取值」与「取值消失」都不会自己冒出来 ——
    这条测试就是那个代价的保险：声明的那几个值必须与游戏里实测的集合一致。
    """
    _skip_if_no_game()
    for header, occ, field, d, deep, left, right in doc17.DIST_TABLES:
        measured = set(doc17.value_counter(d, field, deep=deep))
        declared = {doc_tables.norm_key(k) for k in (*left, *right)}
        assert measured == declared, (
            f"{d} 的 {field} 取值变了（表：{header[:30]}… 第 {occ + 1} 张）\n"
            f"  游戏里有、表里没有：{sorted(measured - declared)}\n"
            f"  表里有、游戏里没有：{sorted(declared - measured)}"
        )


def test_概念键的后缀分类互斥且完备() -> None:
    """五类相加必须等于文件里的 ``concept_*`` 键总数。

    分类漏一类或重一类都不会报错，只会让某一行的数字偏小/偏大 ——
    而表格下面还写着「共 2,191 个」，两处会互相矛盾。
    """
    _skip_if_no_game()
    path = config.GAME / "localization/english/concepts_l_english.yml"
    total = len(doc17.loc_suffix_keys(path.read_text(encoding="utf-8")))
    counted = sum(int(cells[1].replace(",", "")) for _k, cells in doc17.loc_suffix_rows())
    assert counted == total, f"分类合计 {counted} ≠ 文件里的键总数 {total}"


def test_文件名模式划分完备() -> None:
    """`character_templates` 的模式行 + 「其他单例」必须恰好覆盖全部 ``.txt``。"""
    _skip_if_no_game()
    base = config.GAME / "common/character_templates"
    names = sorted(p.name for p in base.glob("*.txt"))
    rows = doc17.template_rows()
    assert sum(int(cells[1].replace(",", "")) for _k, cells in rows) == len(names), (
        "文件名模式表各行之和 ≠ 目录里的 .txt 总数 —— 有新文件不匹配任何模式"
    )


def test_生成器不写盘且幂等(tmp_path: Path) -> None:
    _skip_if_no_game()
    specs = doc17.doc_table_specs()
    assert_unique_names(specs)
    assert_write_free_and_idempotent(DOC, specs, tmp_path)


def test_表头被改动时报错而不是静默跳过(tmp_path: Path) -> None:
    broken = tmp_path / "broken.md"
    broken.write_text("# 没有表格的文档\n", encoding="utf-8")
    with pytest.raises(doc_tables.TableNotFoundError):
        doc_tables.patch_doc(broken, doc17.doc_table_specs(), write=False)
