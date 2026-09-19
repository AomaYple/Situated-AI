"""doc 06（本地化与界面资源）的生成表看守。

本篇的六张表跨两个模块产生：目录文件数在 :mod:`pdx.install_tree`（与 doc 08
共用同一套 ``rows_of`` / ``fmt_count``，口径必须一致），语言统计在
:mod:`pdx.localization`。另有一张表**刻意不生成**（§1.5.5 数据函数频次），
它的理由写在 :data:`pdx.localization.NOT_GENERATED` 与
``tools/tests/test_inventory.py`` 的「刻意不生成」清单里。
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

from pdx import config, install_tree, localization

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

DOC = config.DOCS / "06-本地化与界面资源.md"


def _specs() -> list:
    return [*install_tree.doc06_table_specs(), *localization.doc_table_specs()]


def _skip() -> None:
    skip_if_no_game(DOC, config.GAME / "localization", config.GAME / "gui", config.GAME / "gfx")


def test_文档里的表就是生成器的输出() -> None:
    _skip()
    assert_doc_matches_generated(DOC, _specs())


def test_每一行都有人认领() -> None:
    """防止键写错导致数字静默过期（详见 :mod:`_table_guards`）。"""
    _skip()
    assert_every_row_claimed(DOC, _specs())


def test_语言表的合计等于全树_yml_数() -> None:
    """每个 ``.yml`` 恰好归入一种语言首行 —— 分类互斥且完备。"""
    _skip()
    base = config.GAME / "localization"
    total = sum(1 for _ in base.rglob("*.yml"))
    counted = sum(localization.language_header_counts().values())
    assert counted == total, f"语言表合计 {counted} ≠ 全树 .yml 数 {total}"


def test_三张目录表的行数等于子目录数() -> None:
    """少一行 = 有个子目录没人统计（``rows_of`` 只列一级子目录，这是有意的口径）。"""
    _skip()
    for name, base, want in (
        ("localization", config.GAME / "localization", 13),
        ("gui", config.GAME / "gui", 10),
        ("gfx", config.GAME / "gfx", 19),
    ):
        got = len(install_tree.rows_of(base))
        assert got == want, f"{name} 子目录数从 {want} 变成 {got} —— 表要跟着加行了"


def test_扩展名表每一行都还在_gfx_树里() -> None:
    """节选表：文档列出的每个扩展名都必须仍存在于 ``gfx\\`` 之下。

    合并行（``.shader`` / ``.fxh``）由生成器的合并行机制处理，这里逐行验它的两部分。
    """
    _skip()
    from pdx.doc_tables import key_parts
    from pdx.scan import stats_for

    by_suffix = stats_for(config.GAME / "gfx").by_suffix
    missing: list[str] = []
    for row in doc_rows(DOC, "| 扩展名 | 数量 | 主要用途 |", 0):
        missing += [part for part in key_parts(row[0]) if part not in by_suffix]
    assert not missing, f"这些扩展名在 gfx\\ 里已经不存在了：{missing}"


def test_刻意不生成的表仍在文档里() -> None:
    """排除清单不能指向一张已经被删掉/改名的表 —— 否则它会静默失效。"""
    text = DOC.read_text(encoding="utf-8")
    for header, reason in localization.NOT_GENERATED.items():
        assert header in text, f"排除清单里的表头在文档里找不到：{header}（理由：{reason}）"


def test_表名唯一且写盘幂等(tmp_path: Path) -> None:
    _skip()
    specs = _specs()
    assert_unique_names(specs)
    assert_write_free_and_idempotent(DOC, specs, tmp_path)
