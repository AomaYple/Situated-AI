"""生成表的通用看守（doc 06 / 15 / 17 共用）。

为什么抽出来
-----------
「文档现值 == 生成结果」只防得住**数字过期**，防不住**静默不更新**：

* 键的写法与生成器不一致（少一个反引号、多一个括注）→ 那一行永远匹配不上，
  而 ``append_new=False`` 的节选表对未匹配的行**既不警告也不更新**；
* 表头 occurrence 数错 → 生成器去改同表头的另一张表；
* 两栏并排的表把键列写错 → 整栏从未被写过，数字看着却「对」（那是文档原值）。

doc 17 那批实测撞出过全部三种，于是有了 :func:`assert_every_row_claimed`。
三个文档的表形状不同，但这三条判据是同一套，所以放在这里共用。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from pdx import doc_tables

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from pdx.doc_tables import KeyedTableSpec, TableSpec


def doc_rows(doc: Path, header: str, occurrence: int) -> list[list[str]]:
    """文档里第 ``occurrence`` 张该表的数据行（拆成单元格）。"""
    lines = doc.read_text(encoding="utf-8").splitlines()
    hits = [n for n, ln in enumerate(lines) if ln.startswith(header)]
    assert occurrence < len(hits), f"{header!r} 只出现 {len(hits)} 次，取不到第 {occurrence + 1} 张"
    out: list[list[str]] = []
    n = hits[occurrence] + 2
    while n < len(lines) and lines[n].startswith("|"):
        out.append(doc_tables.split_row(lines[n]))
        n += 1
    return out


def assert_doc_matches_generated(
    doc: Path, specs: Sequence[TableSpec | KeyedTableSpec], *, at_most: int = 6
) -> None:
    """**核心**：文档现值必须等于重新生成的结果。"""
    diff = doc_tables.check_doc(doc, specs)
    assert not diff, (
        f"{doc.name} 有 {len(diff)} 行与生成器不一致（跑 `v3 tables --write` 可修）：\n"
        + "\n".join(
            f"  {name} 第 {ln} 行\n    文档: {a}\n    生成: {b}"
            for name, ln, a, b in diff[:at_most]
        )
    )


def assert_every_row_claimed(doc: Path, specs: Iterable[TableSpec | KeyedTableSpec]) -> None:
    """**防静默过期**：每一张表里的每一行，都要被某条 spec 的键覆盖到。

    判定与生成器同源：键都过一遍 :func:`pdx.doc_tables.norm_key`，
    且按 ``(表头, occurrence)`` 分组 —— 一张表可以由多条 spec 各管一半
    （左右两栏、块内字段 + 顶层字段、不同文件切分的分类行）。
    """
    keyed = [s for s in specs if isinstance(s, doc_tables.KeyedTableSpec)]
    groups: dict[tuple[str, int], set[str]] = {}
    for spec in keyed:
        keys = {doc_tables.norm_key(k) for k, _cells in spec.cells()}
        assert keys, f"{spec.name} 没生成任何键 —— 多半是目录写错或游戏不可用"
        groups.setdefault((spec.header, spec.occurrence), set()).update(keys)

    orphans: list[str] = []
    for (header, occurrence), covered in groups.items():
        key_cols = sorted(
            {s.key_column for s in keyed if (s.header, s.occurrence) == (header, occurrence)}
        )
        for row in doc_rows(doc, header, occurrence):
            # 没有数字的行不可能「数字静默过期」—— 混合表里那些纯散文行
            # （doc 04 对照表的「规则键」「否定后缀」两行）是作者写的，不要求被认领。
            if not any(re.search(r"\d", cell) for cell in row):
                continue
            # 一张表可能有多条 spec、各以不同的列为键 —— 每行被其中任一键列认领即可。
            # 判定顺序与生成器一致：**先整键**，再拆合并行（``| `a` / `b` |``）。
            # 反过来会把「键本身被认领、但键里有 ` / ` 散文」的行误报成孤儿
            # （doc 04 的「以 `_effect` / `_effects` 结尾」就是这种，实测被误报）。
            for col in key_cols:
                if len(row) <= col:
                    continue
                if doc_tables.norm_key(row[col]) in covered or all(
                    p in covered for p in doc_tables.key_parts(row[col])
                ):
                    break
            else:
                orphans.append(f"{header[:40]}… {row}")
    assert not orphans, (
        f"{doc.name} 里这些行没有任何 spec 认领（数字会静默过期）：\n  " + "\n  ".join(orphans[:10])
    )


def assert_write_free_and_idempotent(
    doc: Path, specs: Sequence[TableSpec | KeyedTableSpec], tmp_path: Path
) -> None:
    """``write=False`` 不落盘；``write=True`` 跑两次结果相同。"""
    import shutil

    copy = tmp_path / doc.name
    shutil.copyfile(doc, copy)
    before = copy.read_text(encoding="utf-8")
    replaced = doc_tables.patch_doc(copy, specs, write=False)
    assert len(replaced) == len(specs), "有 spec 没跑到（表名重复会互相覆盖）"
    assert copy.read_text(encoding="utf-8") == before, "write=False 却改了文件"
    doc_tables.patch_doc(copy, specs, write=True)
    once = copy.read_text(encoding="utf-8")
    doc_tables.patch_doc(copy, specs, write=True)
    assert copy.read_text(encoding="utf-8") == once, "跑两次结果不同"


def assert_unique_names(specs: Sequence[TableSpec | KeyedTableSpec]) -> None:
    names = [s.name for s in specs]
    assert len(names) == len(set(names)), f"表名重复：{names}"


def skip_if_no_game(*paths: Path) -> None:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"游戏目录不可用：{missing}")
