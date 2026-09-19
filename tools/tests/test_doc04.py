"""doc 04（脚本系统）的生成表看守。

19 张表里有六种口径（字段出现次数、取值分布、命名形态、`$PARAM$` 计数、
`placement` 写法、目录规模的两列公式），其中三处容易写错，各配一条测试：

* **`script_values` 的「顶层键」是块口径**：块 270 / 赋值 479（差的是标量赋值），
  文档那句话用的是块；
* **`$PARAM$` 先剥行内注释**：注释里提到 ``$X$`` 不是一次使用
  （实测 `00_scripted_effects.txt` 与 `ip4_negotiation_triggers.txt` 各有一处）；
* **JE 分组表的两栏是作者选定的**：实测取值集合必须与声明集合一致，
  否则新增分组会悄悄漏掉（版面没法机械重排）。
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

from pdx import config, doc04
from pdx.usage import field_occurrences, file_definition_counts

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

DOC = config.DOCS / "04-脚本系统.md"


def _skip() -> None:
    skip_if_no_game(DOC, config.GAME / "events", config.GAME / "common" / "scripted_effects")


def test_文档里的表就是生成器的输出() -> None:
    _skip()
    assert_doc_matches_generated(DOC, doc04.doc_table_specs())


def test_每一行都有人认领() -> None:
    _skip()
    assert_every_row_claimed(DOC, doc04.doc_table_specs())


def test_script_values_用的是块口径() -> None:
    """270（块）与 479（含标量赋值）必须都能算出来，且文档写的是**块**。

    这条盯的是口径而不是数字：一旦有人把 `file_definition_counts` 的
    ``blocks_only`` 默认值改掉，文档那句「共 N 个顶层键」就会整体漂走。
    """
    _skip()
    blocks = sum(file_definition_counts("common/script_values", blocks_only=True).values())
    assigns = sum(file_definition_counts("common/script_values").values())
    assert blocks < assigns, "script_values 里应当同时存在块与标量赋值（否则这条测试失去意义）"
    rows = doc_rows(DOC, "| 目录 | `.txt` 文件数 | 备注 |", 0)
    cell = next(r[2] for r in rows if r[0].strip("`") == "common/script_values/")
    assert f"**{blocks}**" in cell, (
        f"§0.2 里 script_values 的键数应写块口径 {blocks}，实得 {cell!r}"
    )


def test_参数计数不数注释里的用法() -> None:
    """注释里提到 ``$X$`` 不算一次使用 —— 两个文件各有一处，正是这条的样本。"""
    _skip()
    raw = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$")
    for rel, counted in (
        ("common/scripted_effects/00_scripted_effects.txt", 8),
        ("common/scripted_triggers/ip4_negotiation_triggers.txt", 1),
    ):
        path = config.GAME / rel
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        in_code = sum(len(raw.findall(ln.split("#", 1)[0])) for ln in text.splitlines())
        assert len(raw.findall(text)) > in_code, f"{rel} 应当至少有一处在注释里"
        assert doc04.param_counts(rel.rsplit("/", 1)[0])[path.name] == counted
        assert doc04.param_counts(rel.rsplit("/", 1)[0])[path.name] == in_code


def test_JE_分组表声明的取值没有过期() -> None:
    """两栏并排的版面是作者的，所以「游戏里有新分组」不会自己冒出来。"""
    _skip()
    measured = set(doc04.je_group_counts())
    declared = set(doc04._JE_GROUP_LEFT) | set(doc04._JE_GROUP_RIGHT)
    assert measured == declared, (
        f"JE 分组取值变了\n  游戏里有、表里没有：{sorted(measured - declared)}\n"
        f"  表里有、游戏里没有：{sorted(declared - measured)}"
    )


def test_placement_的每一行都分得掉() -> None:
    """六类相加必须等于 `placement` 字段总数 —— 出现新写法时不能悄悄漏出统计。"""
    _skip()
    from pdx.usage import field_value_counts

    total = sum(int(c[1]) for _k, c in doc04.placement_rows())
    assert total == sum(field_value_counts("events", "placement").values()), (
        "placement 的形态分类没有覆盖全部取值（出现新写法了）"
    )


def test_事件字段表覆盖全部字段() -> None:
    """表里必须有 `events/` 的**每一个**深度 1 字段（26 个）—— 不许漏。"""
    _skip()
    counted = set(field_occurrences("events"))
    listed = {
        r[0].strip("`*").split("（")[0].strip()
        for r in doc_rows(
            DOC, "| 字段 | 出现次数 | 首例 | 说明（由用法/上下文推断，非官方文档） |", 0
        )
    }
    assert counted == listed, (
        f"事件字段表与实测不一致\n  实测有、表里没有：{sorted(counted - listed)}\n"
        f"  表里有、实测没有：{sorted(listed - counted)}"
    )


def test_表名唯一且写盘幂等(tmp_path: Path) -> None:
    _skip()
    specs = doc04.doc_table_specs()
    assert_unique_names(specs)
    assert_write_free_and_idempotent(DOC, specs, tmp_path)
